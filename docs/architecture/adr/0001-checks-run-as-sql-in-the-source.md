# ADR-0001: Checks run as SQL inside the source, not in pandas

- **Status:** Accepted
- **Date:** 2026-10-30

## Context

The product's promise is that every record breaking a declared rule is found and counted
exactly. The common way to build a data quality tool in Python is to read the data into a
DataFrame (pandas, Polars, Spark) and evaluate rules there. That makes memory grow with the
table, means a 10 lakh row table crosses the network on every scan, and pushes teams towards
sampling, which breaks "exactly". The data already sits in a database that is built to scan
it.

## Decision

Every check compiles to SQL for the source's own dialect (`engine/compiler.py`,
`engine/dialects.py`) and returns counts plus a bounded sample of failing rows. Row-level
checks are folded into one aggregate query per dataset (`COUNT(CASE WHEN ...)` pairs), so a
table is scanned once however many checks it has; grouped, shape, outlier, reference and
custom checks get one query each. The few constructs whose SQL differs per database
(regex full match, length, value shape, exact text, blank) have one compiled form per
dialect. Where a database cannot express a check at all (regex on SQL Server), the engine
streams that column once and evaluates it exactly in Python, never estimating.

## Consequences

**Good**
- Worker memory does not grow with the table: 93 MB peak at both 100,000 and 1,000,000
  PostgreSQL rows, with 15 checks in 4.5 s on 1,000,000 rows (`make bench`).
- Data stays in the database; only counts and a few sample rows leave it.
- The same compiler serves files through DuckDB ([ADR-0003](0003-duckdb-for-files.md)), so
  every backend reports identical numbers, which the parity test enforces.

**Bad / caveats**
- Every check type needs a SQL formulation that means the same thing on five dialects;
  collations, regex engines and length functions differ and each difference is code
  ([engine.md](../engine.md#per-dialect-differences)).
- Scans put load on the source. Statement timeouts and `max_concurrent_scans` per connection
  bound it, and teams can point a connection at a replica.
- SQL Server regex checks move the evaluated rows to the worker (streamed, so memory stays
  flat, but the network carries them).

## Alternatives considered

- **pandas or Polars in the worker**: simplest to write, but memory and transfer grow with
  the data, which defeats the scale goal.
- **Sampling large tables**: fast, but the counts become estimates. Profiles may sample
  (they describe); checks may not (they count).
- **Spark (Deequ)**: exact at scale, but a cluster is far more than a self-hosted tool should
  require.
