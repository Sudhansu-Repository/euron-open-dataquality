# The check engine

`apps/api/src/dataquality/engine/` turns checks into SQL for the source's own database,
runs them where the data lives, and returns exact counts and bounded samples. It never
loads a table into Python. This page explains how the SQL is generated, what differs per
database, where the engine falls back to Python, how files become tables, and how scans stay
read-only and bounded in time. What each check means is in [checks.md](checks.md).

## From a check to SQL

1. **Relation.** `engine/relation.py` describes what the dataset is: a reflected table or
   view, a read-only query wrapped as a subquery (its column types inferred from its first
   500 rows), or a file loaded into DuckDB. Each column gets a logical type (`integer`,
   `decimal`, `boolean`, `date`, `datetime`, `text`, `uuid`, `other`) from the database's
   native type.
2. **Plan.** `compiler.compile_check(spec, relation, dialect)` validates the check against
   the relation (the column exists and has a type the check applies to) and returns a
   `Plan`: either a pair of SQLAlchemy boolean expressions (`evaluated`, `failed`) or a
   kind the runner executes on its own.
3. **Dialect.** The few constructs whose SQL differs per database are SQLAlchemy elements
   with one `@compiles` function per dialect (`engine/dialects.py`), so the compiler is
   written once and SQLAlchemy prints the right SQL for `postgresql`, `mysql`, `sqlite`,
   `mssql` or `duckdb`.

| Plan kind | Checks | How it runs |
| --- | --- | --- |
| `AGGREGATE` | `not_null`, `range`, `length`, `accepted_values`, `compare`, `type`, `pattern` | Two `COUNT(CASE WHEN ...)` columns in the shared aggregate query |
| `PYTHON` | `type` and `pattern` on SQL Server | Evaluated count in SQL, the match itself in one streamed Python pass |
| `GROUPS` | `unique`, `duplicate_rows` | `GROUP BY key HAVING COUNT(*) > 1`, summed in an outer query |
| `SHAPES` | `format_consistency` | `GROUP BY shape(value)`, top 5 |
| `OUTLIERS` | `outliers` | Mean, then variance around it, then a count outside the bounds |
| `COUNT` | `referential` | `COUNT(*) WHERE NOT EXISTS (reference match)` in its own query (SQL Server cannot put a subquery inside `SUM`) |
| `CUSTOM` | `custom_sql` | `SELECT COUNT(*) FROM (<guarded SQL>)`, then a sample |
| `DATASET` | `schema`, `row_count`, `freshness` | Judged once from the relation, the row count and a `MAX` in the aggregate query |

## Order of work for one scan

`engine/runner.py`, `CheckRunner.run`:

1. **One aggregate query.** The row count, an evaluated and a failed count for every
   `AGGREGATE` check, an evaluated count for every other row-level check, and `MAX` for
   every freshness column, all in one `SELECT` over the dataset. The table is scanned once
   however many checks it has. For three checks on PostgreSQL it reads:

   ```sql
   SELECT count(*) AS rows,
          count(*) AS e0,
          count(CASE WHEN (NOT (email IS NOT NULL AND ltrim(rtrim(email)) != '')) THEN 1 END) AS f0,
          count(CASE WHEN (email IS NOT NULL AND ltrim(rtrim(email)) != '') THEN 1 END) AS e1,
          count(CASE WHEN (email IS NOT NULL AND ltrim(rtrim(email)) != ''
                           AND NOT (email ~ '^(?:[A-Za-z0-9._%+-]+@...)$')) THEN 1 END) AS f1,
          count(CASE WHEN (price IS NOT NULL) THEN 1 END) AS e2,
          count(CASE WHEN (price IS NOT NULL AND price < 0) THEN 1 END) AS f2
   FROM customers
   ```

   If that statement fails (one check's filter names a missing column, say), each
   expression is counted on its own so the error lands on the check that caused it. If even
   the row count fails, the dataset itself is unreadable and the scan fails with the
   database's message.
2. **One query per grouped, shape, outlier, reference or custom check.**
3. **One streamed pass** for checks evaluated in Python (regex on SQL Server).
4. **A bounded sample** of failing rows for every failing check: `SELECT <columns> WHERE
   <filter> AND <evaluated> AND <failed> LIMIT sample_size`, or the most repeated groups for
   grouped checks.

Between queries the runner checks the stop flag (cancel or a lost lease) and the scan's
deadline, and raises `ScanStopped`. Errors are per check: a missing column or a database
error marks that check `error` with the database's first message line, and the rest of the
scan carries on.

## Per-dialect differences

| Construct | PostgreSQL | MySQL, MariaDB | SQLite | SQL Server | DuckDB |
| --- | --- | --- | --- | --- | --- |
| Full regex match (`FullMatch`) | `value ~ '^(?:p)$'` | `REGEXP_LIKE(value, '^(?:p)$', 'c')` (case-sensitive whatever the collation) | `value REGEXP '^(?:p)$'`, a function the engine registers on the connection (Python `re.search`) | None: evaluated in Python (below) | `regexp_full_match(value, '^(?:p)$')` |
| Length (`StrLen`) | `char_length` | `char_length` | `length` | `LEN(value + N'x') - 1` (`LEN` alone ignores trailing spaces) | `length` |
| Value shape (`Shape`) | `translate(value, 'a..zA..Z0..9', 'a..aA..A9..9')` | Three `REGEXP_REPLACE` calls with the `c` flag | `dq_shape(value)`, registered from `patterns.shape` | `TRANSLATE(value COLLATE Latin1_General_BIN2, ...)` (a case-insensitive collation would map `A` through `a` first) | `translate(...)` |
| Exact text (`Exact`) | the value (byte comparison) | `CAST(value AS BINARY)` | the value | `value COLLATE Latin1_General_BIN2` (case-sensitive; `=` still ignores trailing spaces) | the value |
| Blank | `ltrim(rtrim(value)) = ''` on every database: a plain comparison, because SQL Server has no boolean values and only a predicate can be negated or put in a `CASE` | | | | |
| Number or date as text (`as_text`) | `CAST(x AS VARCHAR)` | `CAST(x AS CHAR)` | `CAST(x AS VARCHAR)` | `CAST(x AS VARCHAR(4000))` | `CAST(x AS VARCHAR)` |
| Quantiles (profile) | `percentile_disc(q) WITHIN GROUP (ORDER BY x)` | `ORDER BY x OFFSET k LIMIT 1` per quantile | same as MySQL | same as MySQL | `percentile_disc` |
| Statement timeout | `statement_timeout` session option | `MAX_EXECUTION_TIME` (MySQL) or `max_statement_time` (MariaDB) | progress handler deadline | driver query timeout | a timer that interrupts the connection |
| Read-only | `default_transaction_read_only=on` | `SET SESSION TRANSACTION READ ONLY` | `mode=ro` and `PRAGMA query_only` | none at session level | external access off, configuration locked |

The golden parity test runs the same checks on the same planted defects in PostgreSQL,
MySQL, SQLite, SQL Server, CSV, Excel, JSON and Parquet and requires identical counts
([testing.md](../guides/testing.md#the-golden-dataset-and-the-parity-matrix)). One known edge
remains outside it: a value that ends in a newline. PostgreSQL and DuckDB anchor `$` at the
very end of the value; Python's `re.search` (SQLite) and ICU (MySQL) also let `$` match
before a final newline, so `"abc\n"` matches `^(?:abc)$` there.

## The SQL Server fallback

SQL Server has no regular expressions in the versions the platform supports, and emulating
them with `LIKE` would change what a pattern means. Instead, for `type` and `pattern` checks
on SQL Server:

- the **evaluated** condition (present, non-blank, the check's filter) stays in SQL and is
  counted in the aggregate query like any other check;
- the runner then makes **one streamed pass** over the dataset (`stream_results`,
  `yield_per` 10,000 rows) that selects every column plus, for each such check, the
  evaluated flag and the value as text;
- each value is tested with Python's `re.fullmatch` against the same portable pattern, and
  failing rows are counted and sampled.

All regex checks of a dataset share the one pass. The result is exact, not estimated; the
cost is that those rows travel to the worker once, a batch at a time, so memory stays flat
but the network carries the dataset. The stop flag and deadline are checked every batch.

## Files: DuckDB inside the worker

File, REST and push datasets become DuckDB tables, so they go through the same compiler as
databases ([ADR-0003](adr/0003-duckdb-for-files.md)):

1. `datasets/source.prepare` downloads the file version (or writes REST and push records as
   NDJSON) into a private temp directory under `WORK_DIR`. Files named by referential
   checks are fetched too.
2. `sources/files.open_files` creates an **in-memory** DuckDB with `memory_limit`
   (`DUCKDB_MEMORY_LIMIT`, default 2GB), 4 threads, and spill files in the scan's temp
   directory, then loads each file as a table named after the dataset's slug:
   - CSV and TSV with `read_csv(header = true, sample_size = -1)` (types inferred from every
     row, an optional delimiter from the dataset options);
   - JSON (`format = 'auto'`, an array or one object per line) and NDJSON
     (`newline_delimited`) with `read_json(sample_size = -1)`;
   - Parquet with `read_parquet`;
   - Excel through Polars with the calamine reader (an optional sheet), handed to DuckDB as
     Arrow.
3. Then it **locks DuckDB down**: `SET enable_external_access = false` (no file or network
   access), `SET autoload_known_extensions = false`, and `SET lock_configuration = true` so
   nothing can switch those back. A custom SQL check can read the loaded tables and nothing
   else; the SQL guard also refuses DuckDB's file-reading functions and paths in FROM.

The format comes from the extension and is confirmed by magic bytes where they can tell
(`PAR1` for Parquet, a ZIP header for `.xlsx`); a file without a known extension is read as
JSON when it starts with `[` or `{`. REST and push records are flattened one level: nested
objects and arrays become JSON text, so every column is checkable.

## Read-only enforcement

See [security.md](security.md#read-only-by-construction) for the three locks (generated SQL
is `SELECT` only, user SQL is parsed and refused unless read-only, sessions are read-only
where the database allows) and the per-database table. In addition every source connection
runs inside a transaction that is always rolled back, and is closed after use (`NullPool`):
a scan holds one connection to the customer's database and gives it back.

## Timeouts

| Limit | Default | Where it applies |
| --- | --- | --- |
| Scan deadline (`scan_timeout_s` per dataset) | 1,800 s | Checked by the runner between queries; past it the scan stops with "the scan ran past its time limit" |
| Statement timeout | `min(scan_timeout_s, STATEMENT_TIMEOUT_S)`, default 300 s | Per statement on PostgreSQL, MySQL and SQL Server (`LOCK_TIMEOUT` too). SQLite and DuckDB have no per-statement timeout: there the scan deadline itself interrupts whatever runs (a progress handler, and a timer that interrupts DuckDB) |
| Connect timeout | 10 s | Every database driver |
| Connection test | 20 s | `POST .../connections/{id}/test` |

## Profiling

`engine/profiler.py` profiles a dataset in the source with a fixed number of queries,
independent of the row count:

- one aggregate query for every column's present count, distinct count (exact text),
  minimum and maximum (ordered types), mean (numbers), blanks and lengths (text);
- one for the variances around those means (numerically stable), giving standard deviations;
- quantiles p5, p25, p50, p75 and p95 by **nearest rank**: the value at position
  `ceil(q x n)` in sorted order, so every quantile is a real value of the column on every
  backend ([ADR-0006](adr/0006-nearest-rank-quantiles.md)). PostgreSQL and DuckDB use
  `percentile_disc`; the others one `ORDER BY ... OFFSET ... LIMIT 1` per quantile;
- one for 10 bin histograms of numeric columns;
- one `GROUP BY` per column for the 10 most common values (skipped when every value is
  distinct) and, for text, the 5 most common shapes;
- semantic hints for text columns: the share of values that fully match email, phone, URL,
  UUID, date, datetime, integer, decimal and boolean patterns, over the first 20,000 rows
  (on SQL Server a fixed random sample of 2,000 of those, evaluated in Python).

Datasets larger than `PROFILE_MAX_ROWS` (default 5,000,000) are profiled over their first
rows and the profile says `sampled`. **Checks are always exact over every row.** Masked
columns have their top values, minimum, maximum and quantiles replaced before the profile is
stored.

## Suggestions

`engine/suggest.py` reads a profile and proposes checks with plain rules, each with a reason
a person can judge, and no AI:

| Suggestion | When |
| --- | --- |
| `schema` with the current columns and types | Always (extra columns allowed) |
| `row_count` with `min` half of today's rows (`warn`) | Always; an empty dataset gets `min: 1` and nothing else |
| `duplicate_rows` | Always |
| `not_null` | No missing values (`error`), or at most 1% missing (`warn`) |
| `unique` | Integer, text or UUID column, at least 10 values, a key-like name (`id`, `*_id`, `uuid`, `code`, `sku`, `*_no`...) or a UUID column, and every value distinct (keys tolerate up to 2% repeats) |
| `pattern` preset | 90% or more of a text column are emails, UUIDs, URLs or phone numbers (E.164 or Indian, by the dominant shape) |
| `type` | Otherwise, 95% or more of a text column parse as dates, datetimes, integers, decimals or booleans |
| `format_consistency` (`warn`) | Otherwise, a text column with more than 10 distinct values where 95% share one shape |
| `accepted_values` | Text column with 2 to 12 distinct values, at least 20 values, not key-like |
| `range` with `min: 0` | Numeric column never negative so far |
| `outliers` with `z: 4` (`warn`) | Numeric, not key-like, more than 20 distinct values, some spread |
| `freshness` (`warn`) | Date or timestamp column with a name like `updated`, `created`, `*_at`, `date`..., newest value at most 7 days old; limit 26 hours, or twice the current age |
| `length` (`warn`) | Text column where every value has the same length and no pattern or type was suggested |

Accepting suggestions on clean data gives a passing scan, and on the golden defects a
failing one: that is an integration test (AC6).
