# ADR-0006: Nearest-rank quantiles in profiles

- **Status:** Accepted
- **Date:** 2026-10-30

## Context

Profiles show p5, p25, p50, p75 and p95 for numeric columns, and they must agree across
PostgreSQL, MySQL, SQLite, SQL Server and DuckDB (a CSV and the same table in Postgres show
the same profile). Databases disagree on quantiles: PostgreSQL and DuckDB have both
`percentile_cont` (interpolated) and `percentile_disc` (a value of the column), SQL Server's
`PERCENTILE_CONT` is a window function, MySQL and SQLite have neither. Interpolation also
produces values that never occur (a median of 2.5 for an integer id column).

## Decision

Nearest rank: the quantile q of n present values is the value at position `ceil(q x n)` in
sorted order. PostgreSQL and DuckDB compute it with `percentile_disc(q) WITHIN GROUP (ORDER
BY x)`, all in one query; the other databases run one `ORDER BY x OFFSET ceil(q x n) - 1
LIMIT 1` per quantile over non-NULL values. Every backend returns the same element of the
column.

## Consequences

**Good**
- Identical quantiles on every backend, and each is a real value of the column.
- No window functions or user-defined aggregates needed.

**Bad / caveats**
- On MySQL, SQLite and SQL Server a profile costs five sorted lookups per numeric column;
  the profiler limits very large tables to `PROFILE_MAX_ROWS` rows.
- Nearest rank is coarser than interpolation on small samples. Profiles describe; they never
  decide a check's outcome.

## Alternatives considered

- **Interpolated quantiles (`percentile_cont`)**: unavailable on two databases and a window
  function on a third, and they invent values.
- **Approximate quantiles (t-digest, `approx_quantile`)**: fast, but they differ by backend
  and by run.
- **Quantiles computed in Python over a sample**: breaks the rule that the engine does not
  pull data into the worker.
