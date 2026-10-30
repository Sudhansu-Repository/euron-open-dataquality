# Anomalies and schema drift

Checks catch what a team declared. Anomaly detection catches what nobody declared: a load
that delivered a third of the usual rows, a column whose missing values jumped overnight, a
score that fell off a cliff. It uses plain robust statistics on each dataset's own history,
and explains every finding in one sentence. No model is trained and nothing leaves the
deployment ([ADR-0007](adr/0007-robust-z-score-for-anomalies.md)).

## What is recorded

Every successful scan writes metric points (`metric_points`), at the scan's start time, in
its completion transaction (`scans/history.py`):

| Metric | Key | Source | Watched for anomalies |
| --- | --- | --- | --- |
| `row_count` | none | the scan | yes |
| `score` | none | the scan | yes |
| `dimension` | the dimension | the scan | no (history only) |
| `check_failed_pct` | the check id | each check that ran | yes |
| `null_rate` | the column | the profile, when the scan profiled | yes |
| `distinct` | the column | the profile | no (history only) |
| `mean` | the column | the profile | no (history only) |

Points are kept when scan results are purged by retention, so baselines and trend charts
outlive the results (`GET .../datasets/{id}/metrics?metric=row_count`).

## The test: robust z-score

For each watched series, the new value is compared with the previous points of the same
series (same dataset, metric and key), up to the last 30:

```
median = median(history)
MAD    = median(|x - median| for x in history) x 1.4826
z      = (value - median) / MAD
```

This is the modified z-score of Iglewicz and Hoaglin. The median and the median absolute
deviation (scaled by 1.4826 so that it matches a standard deviation on normal data) ignore
the outliers the history already contains: one broken load last week does not widen the
band and hide the next one, which a mean and standard deviation would do.

A value is an anomaly when `|z|` is above the project's sensitivity
(`anomaly_sensitivity`, default 3.5, settable from 2 to 10 per project) **and** it passes the
guards below.

## Guards: quiet on normal data

| Guard | Rule | Why |
| --- | --- | --- |
| Minimum history | At least 6 previous points; until then the result is "Not enough history yet (n of 6 scans)" | Medians of two or three points mean nothing |
| Minimum relative change | The change from the median must be at least 10% of the median for `row_count` and `score`, and at least 50% for `null_rate` and `check_failed_pct` | A row count of 10,001 against a perfectly flat 10,000 has an enormous z-score and means nothing |
| Minimum absolute change for percentages | `null_rate`, `score` and `check_failed_pct` must also move by at least one percentage point | 0.02% to 0.05% missing is a large relative change and still noise |
| Flat history | When the MAD is 0 (the value never changed), there is no z-score; only the relative change decides | Otherwise any change from a constant would be infinite |

## Worked example

The last seven row counts of a nightly table: 10,000, 10,120, 9,980, 10,050, 10,210, 9,900,
10,080. The median is 10,050; the absolute deviations are 50, 70, 70, 0, 160, 150, 30, whose
median is 70, so the MAD is 70 x 1.4826 = 103.8.

- Tonight's load has **4,100** rows: z = (4,100 - 10,050) / 103.8 = -57.3, and the change
  is 59% of the median. Anomaly:
  > Row count is 4,100, 59% below the typical 10,050 (median of the last 7 scans); that is
  > 57.3 robust deviations
- Tonight's load has **10,150** rows: z = 0.96. Normal: "Row count is within its normal
  range".

## What happens to an anomaly

Each anomaly is stored in `anomalies` with its value, the median as `expected`, z, the
direction (`up` or `down`) and the sentence. It shows on the dataset and in
`GET /api/v1/projects/{p}/anomalies`, and an `anomaly` alert rule turns it into an incident
(severity `warn`) keyed by dataset, metric and key. The incident resolves on its own at the
next successful scan that does not flag that series again ([alerts.md](alerts.md)). Note
that a scan without a profile records no `null_rate`, so it cannot flag a missing values
anomaly either.

## Schema drift

After each successful scan, the columns it saw (name and logical type, stored on the scan)
are compared with those of the previous successful scan of the same dataset:

| Change | Sentence |
| --- | --- |
| added | Column `loyalty_tier` was added (text) |
| removed | Column `phone` was removed |
| retyped | Column `price` changed type from decimal to text |

Each change is an anomaly of kind `schema` and, with a `schema_change` alert rule, an
incident (severity `error`). Drift needs no configuration. To pin the schema to an
**expected** list rather than to the previous scan, add a `schema` check
([checks.md](checks.md#schema)); the two are complementary: drift tells you something
changed, the check tells you whether the result is still acceptable.
