# ADR-0007: Robust z-score for anomaly detection

- **Status:** Accepted
- **Date:** 2026-10-30

## Context

Anomaly detection watches each dataset's own history (row count, missing values per column,
score, failing share per check) and must flag a broken load without paging the team for
normal variation. Histories are short (a nightly table has 30 points a month) and dirty: the
history contains the very incidents we want to detect. The result has to be explainable in a
sentence, and the platform must be useful with no AI and no training.

## Decision

The modified z-score of Iglewicz and Hoaglin over the last 30 points of the series: the
distance from the median in units of the median absolute deviation scaled by 1.4826. A value
is anomalous above the project's sensitivity (3.5 by default), with guards: at least 6
points of history, a minimum relative change (10% for row count and score, 50% for missing
values and failing share), at least one percentage point for percentages, and only the
relative change deciding when the history never varied. Each finding carries a sentence such
as "Row count is 4,100, 59% below the typical 10,050 (median of the last 7 scans); that is
57.3 robust deviations". Details in [anomalies.md](../anomalies.md).

## Consequences

**Good**
- One bad day in the history does not widen the band and hide the next one, as it would with
  a mean and standard deviation.
- Deterministic, cheap (a few dozen numbers per series), and explainable to anyone.
- Works from the sixth scan, with no training step.

**Bad / caveats**
- No seasonality: a table that is always small on Sundays may be flagged on Sundays until
  the history holds enough Sundays to move the median. Seasonal models are on the roadmap.
- Gradual drift that moves a little every day is not an anomaly by this test; checks with
  explicit bounds (`row_count`, `range`) catch it.

## Alternatives considered

- **Mean and standard deviation (classic z-score)**: the outliers in the history inflate the
  standard deviation and mask new ones.
- **Forecasting models (Prophet, ARIMA, ML monitors)**: better with long seasonal histories,
  but heavy, slow to warm up, and harder to explain in one sentence.
- **Fixed thresholds only**: already available as checks; they do not adapt to each
  dataset's normal.
