# ADR-0003: DuckDB for files, REST and push data

- **Status:** Accepted
- **Date:** 2026-10-30

## Context

Files (CSV, TSV, JSON, NDJSON, Parquet, Excel), REST responses and pushed records have no
database to run SQL in. The engine runs checks as SQL
([ADR-0001](0001-checks-run-as-sql-in-the-source.md)), and the acceptance criteria require a
CSV and a PostgreSQL table with the same defects to give identical results.

## Decision

The worker loads them into an **in-memory DuckDB** per scan and checks them with the same
compiler, as the `duckdb` dialect. CSV, JSON and Parquet are read by DuckDB itself (types
inferred from every row, `sample_size = -1`); Excel goes through Polars with the calamine
reader into Arrow. REST and push records are written as NDJSON first, nested values
flattened to JSON text. Files named by referential checks are loaded into the same DuckDB so
they can be joined. After loading, DuckDB is locked down: `enable_external_access = false`,
`autoload_known_extensions = false`, `lock_configuration = true`, a `memory_limit`, four
threads, spill files in the scan's private temp directory, and a timer that interrupts it at
the timeout ([engine.md](../engine.md#files-duckdb-inside-the-worker)).

## Consequences

**Good**
- One engine for every source; the parity test runs the same checks on CSV, Excel, JSON and
  Parquet and gets the same counts as the databases.
- Columnar, vectorised and able to spill: large files are checked without holding them in
  Python memory.
- MIT licensed and embedded: nothing to deploy.

**Bad / caveats**
- Files are copied to the worker's disk for each scan (the AWS worker task gets ephemeral
  storage for that).
- Type inference is DuckDB's: a CSV column with one stray letter becomes text, which is
  usually what a quality check wants to see, but it is not the file author's intent.
- Custom SQL on files is DuckDB SQL, whatever the file came from.

## Alternatives considered

- **pandas or Polars only**: no SQL, so a second implementation of every check, and the
  parity guarantee would rest on two engines agreeing.
- **SQLite as the scratch database**: no native Parquet or JSON reading, weak typing, and
  slower scans.
- **Loading files into the platform's own Postgres**: mixes customer data with application
  data and makes every file upload a database write.
