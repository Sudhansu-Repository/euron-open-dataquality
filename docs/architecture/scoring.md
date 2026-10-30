# The quality score

One number per scan, between 0 and 100, that says how much of the data passes its rules,
plus one number per quality dimension. It is computed in `engine/scoring.py` from the check
results of a single scan, stored on the scan (`score`, `dimension_scores`) and copied to the
dataset (`last_score`).

## The formula

For every check result of the scan:

```
pass rate = 1 - failed / evaluated     row-level checks (never below 0)
pass rate = 1 if passed, else 0        schema, freshness, row count
no pass rate                           status "error", or evaluated = 0
```

Then:

```
dimension score = 100 x mean(pass rates of the checks in that dimension)
dataset score   = mean(dimension scores of the dimensions that have a pass rate)
```

Both are rounded down to one decimal, so 100% always means nothing failed: 2 failing rows
out of 50,000 score 99.9%, never a rounded-up 100%. A scan with no pass rate at all (no checks, or only
errors) has no score (`null`), not 0 and not 100.

Things that deliberately do not move the score:

- **Severity.** A `warn` check counts as much as an `error` check. Severity decides alerts,
  CI gates and the pass or fail counts; the score measures the data.
- **Tolerance.** A check that passes within its tolerance still lowers the score by its
  failing share: 3% invalid emails with `max_percent: 5` is a pass, and validity is 97,
  not 100.
- **Errors.** A check that could not run measures nothing, so it is left out rather than
  counted as a failure. The scan counts it in `checks_errored`, the results page shows it
  first after failures, and a `check_failed` alert rule does not fire for it.

Grouped checks score by their extra copies (`unique` with 5 duplicated ids among 1,000 rows
scores 0.995), `format_consistency` by the dominant shape's share, and `custom_sql` by
returned rows over the dataset's row count.

## Worked example

A dataset of 1,000 rows and eight checks:

| Check | Dimension | Status | Evaluated | Failed | Pass rate |
| --- | --- | --- | --- | --- | --- |
| email not null | completeness | fail | 1,000 | 20 | 0.980 |
| phone not null | completeness | pass | 1,000 | 0 | 1.000 |
| email pattern | validity | fail | 980 | 49 | 0.950 |
| price range (min 0) | validity | fail | 1,000 | 10 | 0.990 |
| custom SQL (bad query) | validity | error | 0 | 0 | none |
| customer_id unique | uniqueness | fail | 1,000 | 5 | 0.995 |
| updated_at freshness | freshness | fail | 1 | 1 | 0 |
| row count (min 500) | volume | pass | 1 | 0 | 1 |

The email pattern evaluates 980 rows because the 20 missing emails are not judged twice
([checks.md](checks.md#null-and-blank)).

| Dimension | Calculation | Score |
| --- | --- | --- |
| completeness | 100 x (0.980 + 1.000) / 2 | 99.0 |
| validity | 100 x (0.950 + 0.990) / 2 (the error is left out) | 97.0 |
| uniqueness | 100 x 0.995 | 99.5 |
| freshness | 100 x 0 | 0.0 |
| volume | 100 x 1 | 100.0 |

Dataset score: (99.0 + 97.0 + 99.5 + 0.0 + 100.0) / 5 = **79.1**.

The stale table costs a fifth of the score even though every row is otherwise nearly
perfect. That is the intent: data that stopped arriving is a quality problem of the same
order as data that arrives broken.

## Why the mean of dimensions

The obvious alternative is the mean over all checks. With ten `not_null` checks and one
freshness check, a stale table would then lose at most a eleventh of its score, and adding
more column checks would keep diluting it. Averaging within each dimension first means a
dimension weighs the same however many checks it has, so the score cannot be steered by
adding easy checks, and a team sees which kind of quality moved.

Pass rates rather than pass or fail per check keep the score proportional: one invalid
email among a million rows is 99.9999% valid, not a failed check worth the same as a column
that is entirely wrong.

## Project and dashboard numbers

| Number | Definition | Where |
| --- | --- | --- |
| Project score (dashboard and project list) | Mean of the latest score of every dataset that has one | `dashboard/router.py`, `projects/service.py` |
| Dimension scores (dashboard) | Per dimension, the mean over datasets of their latest scan's dimension score; `null` for a dimension no dataset measures | `dashboard/router.py` |
| Trend (30 days) | Per day, the sum of scan scores divided by the number of scored scans that day, from `daily_scores` | `dashboard/router.py` |
| Score change | The project score minus the trend's score 7 days ago (or the trend's first day when there is no point that old) | `dashboard/router.py` |

The project score weighs every dataset equally, like dimensions within a dataset. The trend
weighs every scan equally, so a dataset scanned hourly moves it more than one scanned daily;
it shows how the measurements moved, while the headline score shows where every dataset
stands now. The dashboard reads the same rows as the API (`GET /api/v1/projects/{p}/dashboard`),
so the numbers on screen are the API's numbers.
