# ADR-0008: Sealed credentials, and read-only by construction

- **Status:** Accepted
- **Date:** 2026-10-30

## Context

A data quality platform holds logins to an organisation's most important databases and runs
SQL against them, some of it written by users (custom checks, query datasets, filters). A
platform bug, a careless custom check or a compromised editor account must not be able to
change production data, and a leaked platform database must not leak the logins.

## Decision

**Read-only by construction**, with three independent locks
([security.md](../security.md#read-only-by-construction)):

1. The engine only generates `SELECT` statements.
2. User SQL is parsed with sqlglot in the source's dialect and refused unless it is exactly
   one read-only query: no writes, `INTO`, locking clauses, SET or PRAGMA, no functions with
   side effects, sleeps or file and network access, no table functions; filters must be
   plain conditions.
3. Sessions are read-only where the database supports it (PostgreSQL
   `default_transaction_read_only`, MySQL `SET SESSION TRANSACTION READ ONLY`, SQLite
   `mode=ro` and `query_only`, DuckDB with external access off and configuration locked),
   always inside a transaction that is rolled back, with statement timeouts.

**Sealed credentials**: passwords, REST headers, Slack and webhook URLs, webhook secrets and
the AI key are sealed before storage, with AES-256-GCM (local key) or KMS, and an encryption
context bound to the row, so a ciphertext copied to another row fails to open. The API never
returns them; it says `has_password` or shows the host only.

## Consequences

**Good**
- A write needs all three locks to fail at once, and on the three databases with read-only
  sessions the database itself refuses it.
- A dump of the platform database holds ciphertext only; with `KEY_MODE=kms`, opening it
  needs KMS decrypt rights and the right context.

**Bad / caveats**
- SQL Server has no read-only session mode: there, locks 1 and 2 carry the guarantee.
  Operators should connect with a `db_datareader` login, and the docs say so.
- The SQL guard refuses some legitimate queries (a function that happens to be on the deny
  list, a filter with a subquery). The refusal says why, and a query dataset can carry the
  logic instead.
- Local sealing is only as safe as `LOCAL_MASTER_KEY`; production should use KMS.

## Alternatives considered

- **Trust the login's grants only**: the right first line, but many teams connect with
  whatever login they have, and the platform cannot verify grants on every database.
- **A regex or keyword deny list on user SQL**: easy to bypass with comments, quoting or
  dialect syntax; a real parser sees the statement's structure.
- **Store credentials in Secrets Manager per connection**: AWS only, and every scan would
  call it; sealing with KMS gives the same protection with the row as the store.
