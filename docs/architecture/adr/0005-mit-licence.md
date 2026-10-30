# ADR-0005: MIT licence

- **Status:** Accepted
- **Date:** 2026-10-30

## Context

The project brief suggested Apache 2.0. Every project in the Euron open-source programme is
MIT licensed, so that companies, teams and individuals can adopt and adapt it with the
fewest conditions, and the programme's rules take precedence over a brief.

## Decision

MIT, copyright ENGAGESPHERE TECHNOLOGY PRIVATE LIMITED and the Euron Open DataQuality
contributors. Dependencies keep their own licences. Most are permissive, such as DuckDB,
Polars, sqlglot, SQLAlchemy and FastAPI (MIT) and reportlab (BSD). Two source drivers,
psycopg (PostgreSQL) and pymssql (SQL Server), are LGPL: they are installed unmodified as
separate packages and used through their public interfaces, which the LGPL allows in an MIT
project. The databases themselves are the customer's.

## Consequences

**Good**
- The simplest terms to adopt, the same as the rest of the programme.
- No copyleft obligations for companies embedding the engine or the `dq` CLI in their own
  tooling.

**Bad / caveats**
- No explicit patent grant, which Apache 2.0 would have included. Accepted for consistency
  with the programme.
- Components under non-permissive licences (Soda Core under the Elastic License 2.0 since
  v4) cannot be bundled ([ADR-0004](0004-own-check-engine.md)).
