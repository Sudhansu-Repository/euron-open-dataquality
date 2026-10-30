# ADR-0004: Our own check engine instead of bundling Great Expectations or Soda Core

- **Status:** Accepted
- **Date:** 2026-10-30

## Context

Two well-known open-source tools already validate data: Great Expectations (GX Core) and
Soda Core. Building on one of them would save writing check types. The platform needs:
checks executed in the source as SQL with exact counts, identical semantics on PostgreSQL,
MySQL, SQLite, SQL Server and files, bounded samples, a quality score per dimension, an MIT
licence for the whole product, and a small, typed surface that the API, the YAML format and
the web app share.

- **Soda Core** moved to the Elastic License 2.0 with version 4 (January 2026). ELv2 is not
  an open-source licence and restricts offering the software as a managed service; it cannot
  be bundled into an MIT project.
- **GX Core** is Apache 2.0, but its execution model centres on Python DataFrames and
  expectation suites with their own configuration, data docs and stores. It is a large
  dependency, its SQL execution path does not give the per-dialect guarantees above
  (exact text on MySQL and SQL Server, portable regex, NULL and blank semantics), and its
  hosted UI (GX Cloud) closed to the public on 2026-06-01.

## Decision

Write a focused engine (`engine/`): 16 check types with one strict Pydantic parameter model
each, a compiler to SQLAlchemy Core, per-dialect constructs, a runner that folds row-level
checks into one aggregate query, a profiler, deterministic suggestions, scoring and anomaly
detection. Checks as code use our own YAML format, which maps one to one to the API's check
model ([checks-as-code.md](../../guides/checks-as-code.md)).

## Consequences

**Good**
- Every semantic decision (NULL is never invalid, blank counts as missing, exact text,
  full-match portable regex) is ours, documented in [checks.md](../checks.md) and tested
  across eight backends.
- The whole product stays MIT with permissively licensed dependencies.
- The engine is small enough to read in an afternoon.

**Bad / caveats**
- Fewer check types than GX's catalogue of expectations; adding one means a parameter model,
  a compiler branch and parity tests.
- Teams with existing GX suites cannot import them yet (on the roadmap).

## Alternatives considered

- **Bundle Soda Core**: excluded by its licence since v4.
- **Bundle GX Core as the engine**: Apache 2.0 is compatible, but the DataFrame-first model,
  the size of the dependency and the gaps in per-dialect exactness would have meant wrapping
  and patching more than writing.
- **Import GX suites as an input format later**: kept on the roadmap; it does not need GX at
  runtime.
