# Euron Open DataQuality: plan for 0.1.0

Source brief: `euron-open-source/briefs/09-dataquality.md` (received 2026-10-30). The brief's
14 core requirements and 15 features are all in scope for 0.1.0; anything beyond them is in
the Roadmap. Where the brief and the program rules differ, the rules win: MIT licence (the
brief suggested Apache 2.0), Next.js for the frontend (the brief suggested plain React).

## Purpose

DataQuality is a self-hosted data quality platform for developers and data teams. They
connect a database (PostgreSQL, MySQL, SQLite, SQL Server), upload a file (CSV, Excel, JSON,
Parquet), point it at a REST endpoint, or push records from their own application, and within
seconds get a profile of the data, a set of suggested checks, and a quality score that says
exactly what is wrong: how many emails are missing, which customer ids are duplicated, which
phone numbers are invalid, which prices are negative, whether yesterday's load arrived. Scans
then run on a schedule, every result is kept, unusual changes are flagged, and the team is
alerted when quality drops. It removes two problems: bad records reaching applications and
reports unnoticed, and having to send production data to a SaaS (or pay for one) to find
them. The outcome it guarantees: **every record that breaks a declared rule is found and
counted exactly, the team hears about it, and the data never leaves their infrastructure.**

The name is the contract. *Data quality* must (1) find the defects, counted exactly, not
estimated; (2) show them (which rows, which values); (3) measure quality as a number people
can track; (4) keep watching, so a defect introduced tomorrow is caught tomorrow.

## Comparable products and what users expect

| Product | Kind | Licence | Notes |
| --- | --- | --- | --- |
| Great Expectations (GX Core) | Python validation library | Apache 2.0 | Expectation suites in code, data docs; GX Cloud closed to the public on 2026-06-01, so the OSS has no hosted UI |
| Soda Core | YAML checks (SodaCL) | Elastic License 2.0 since v4 (2026-01) | No longer open source; cannot be bundled in an MIT project |
| Elementary | dbt package + report | open source | dbt-only; anomaly tests for freshness, volume, schema |
| Deequ / PyDeequ | Spark library | Apache 2.0 | Spark-only, metrics repository, anomaly checks |
| ydata-profiling | profiling report | MIT | Profiles a DataFrame in memory; no checks, schedule or history |
| Monte Carlo, Bigeye, Anomalo, Metaplane | observability SaaS | proprietary | ML monitors, lineage, incidents; data or metadata leaves the customer |

Expected by users of this category: connect a source in a minute, automatic profiling,
checks for completeness, uniqueness, validity, ranges, patterns, referential integrity,
freshness and volume, custom SQL checks, failing-row samples, scheduled runs, a history of
every metric, anomaly detection on those metrics, schema-change detection, alerts to email,
Slack and webhooks with incident tracking, checks as code for CI, and an API.

**Why ours is worth starring:**

1. **Checks run inside the database, not in memory.** Every check compiles to SQL for the
   source's own dialect and returns counts and a bounded sample, so a 10 lakh row table is
   checked with a few aggregate queries and the worker's memory stays flat. Files are loaded
   into an embedded DuckDB and checked by the same compiler, so a CSV and a Postgres table
   with the same defect give the same numbers. Where a dialect cannot express a check (regex
   on SQL Server), the worker streams that one column and evaluates it exactly; results are
   never estimated.
2. **Read-only by construction.** The platform only ever generates `SELECT` statements,
   runs them in a read-only transaction or session where the database supports it, with a
   statement timeout; custom SQL checks are parsed and refused unless they are one `SELECT`.
   Source credentials are sealed (envelope encryption, KMS on AWS) and never returned by the
   API.
3. **Useful with zero AI.** Suggested checks come from the profile with deterministic rules,
   anomaly detection is plain robust statistics with an explanation in words. An optional,
   bring-your-own-model assistant turns plain language into a check and explains incidents,
   and it is off by default.
4. **MIT, self-hosted, one `make up`**, with checks as code (YAML) and a CLI that fails a CI
   build when quality drops.

## Acceptance criteria (each one is an automated test)

| # | Criterion | Test |
| --- | --- | --- |
| AC1 | Every built-in check finds exactly the defects planted in a golden dataset (missing values, duplicate ids, duplicate rows, invalid emails and phones, negative prices, out-of-range dates, unknown categories, wrong types in text columns, broken references, inconsistent formats, outliers, end before start) and reports the exact failing count | integration: golden corpus |
| AC2 | The same golden data loaded into PostgreSQL, MySQL, SQLite, SQL Server, CSV, Excel, JSON and Parquet gives identical check results on every backend | integration: source parity matrix |
| AC3 | The platform never writes to a source: a custom SQL check containing a write, a second statement or a function call that modifies data is refused, and the scan session is read-only on every database that supports it (a write attempted through the session fails) | unit (SQL guard) + integration per dialect |
| AC4 | Source credentials are sealed at rest (the database holds ciphertext only) and no API response or log line contains them | integration |
| AC5 | Profiling reports per column type, null and empty counts, distinct count, min, max, mean, quantiles, top values and value patterns that match the data | unit + integration |
| AC6 | Suggested checks come from the profile without AI, and accepting them gives a passing scan on clean data and a failing one on the golden defects | integration |
| AC7 | The quality score follows the documented formula: per dimension (completeness, validity, consistency, uniqueness, freshness, volume) and overall, and the dashboard shows the same numbers as the API | unit (scoring) + e2e |
| AC8 | Scheduled scans run on time and exactly once with several worker replicas; a worker killed mid-scan does not lose the scan, which is retried and completed once | integration |
| AC9 | Freshness: a dataset whose newest timestamp is older than its threshold fails the freshness check | integration |
| AC10 | Anomaly detection flags a sudden drop in row count or jump in null rate against the history, explains it in words, and does not flag normal variation | unit + integration |
| AC11 | Schema validation reports an added, removed or retyped column against the expected schema and against the previous scan | integration |
| AC12 | Alerts: a failing error-severity check opens one incident and sends exactly one notification per channel (email, Slack, signed webhook) until it is resolved; the incident resolves automatically when the check passes again | integration with Mailpit and a webhook sink |
| AC13 | Reports: a scan downloads as CSV (one row per check, failing samples) and as a PDF whose numbers match the API | integration |
| AC14 | API integration: an API key with the `scan` scope triggers a scan and waits for its result; another application pushes a batch of records to a push dataset and gets the check results back; keys are scoped to one project | integration |
| AC15 | Multi-user: project roles (owner, editor, viewer) are enforced on every endpoint; a user never sees another project's datasets | integration |
| AC16 | AI is optional: with AI off (the default) no LLM request is ever made; with it on, a plain-language rule becomes a valid check that must still be accepted by a person, and raw row values are never sent unless the project allows it | integration with a mock LLM |
| AC17 | Scale: a 1,000,000 row PostgreSQL table is profiled and checked with 15 checks, with worker memory independent of row count; the time is in the README | `make bench` |
| AC18 | A developer can clone, `make up && make demo`, connect a source or upload a file, run a scan and see the issues, all in the browser | e2e (the five-minute path) |

## Scope of 0.1.0

**In:**

- **Sources:** PostgreSQL, MySQL/MariaDB, SQLite (uploaded file), SQL Server; uploads of
  CSV, TSV, Excel (xlsx), JSON (array or lines) and Parquet with versions; REST pull (JSON
  from a URL with an optional sealed auth header and a records path); push datasets
  (records posted by an application through the API).
- **Datasets:** a table, view or read-only SQL query in a connection; a file and its
  versions; a REST endpoint; a push dataset. Table browser for connections.
- **Profiling:** per column inferred type, nulls, empty strings, distinct, min, max, mean,
  standard deviation, quantiles, length, top values, value patterns, histogram; full scan or
  a configured sample on very large tables.
- **Checks:** not null, unique (single or composite key), duplicate rows, schema (expected
  columns and types), type validity (text values parse as integer, decimal, date, datetime,
  boolean, uuid), range (numbers and dates), pattern (regex, with presets for email, phone,
  URL, UUID, postal codes), accepted values, length, freshness, row count (volume),
  referential integrity (values exist in another dataset of the same connection), column
  comparison (`end_date >= start_date`), format consistency (share of the dominant value
  pattern), outliers (z-score), and custom SQL (one read-only `SELECT` returning failing
  rows). Each check has a severity (warn or error), a tolerance (allowed failing rows as a
  count or percent), a dimension and an optional filter.
- **Scans:** manual, scheduled (cron with time zone), via API or CLI; a queue in PostgreSQL
  with leases, retries and per-connection concurrency limits; cancel; timeouts.
- **Results:** per check counts, pass or fail, failing-row samples (masked columns
  supported), metrics stored per scan, history and trends.
- **Score:** per dimension and per dataset, project and instance, with the formula in
  `docs/architecture/scoring.md`.
- **Anomalies:** robust statistics on the metric history (row count, missing values per
  column, failing rows per check, score; distinct counts and means are recorded for the
  charts); schema drift between scans.
- **Alerts and incidents:** rules (check failed, which covers freshness checks, score
  below, anomaly, schema change, scan failed) to email, Slack and signed webhooks;
  incidents open once, acknowledge, resolve automatically (no repeat notification while
  open); test send.
- **Reports:** per scan CSV and PDF, per dataset CSV history, project summary PDF.
- **API:** REST with OpenAPI docs, API keys with scopes, idempotent scan trigger, push
  validation, checks as code (YAML import and export), a CLI (`dq scan --wait --fail-on
  error`) for CI.
- **Accounts:** users, admins, projects with owner, editor and viewer roles (members are
  added by email once an admin has created their account), API keys, audit log.
- **Optional AI:** plain-language rule to check, incident explanation; OpenAI-compatible
  provider; off by default.
- **Web:** dashboard, datasets, dataset detail (overview with open incidents, profile,
  checks, scans, settings), scan detail, connections, alerts, incidents, reports, API keys, members,
  settings, audit, admin.

**Roadmap (not 0.1.0):** MongoDB, BigQuery, Snowflake, Redshift, Databricks connectors;
dbt and Airflow integrations; Great Expectations suite import; column-level lineage;
seasonal anomaly models; SSO (OIDC); data contracts; PagerDuty and Teams channels.

## Architecture

```
web (Next.js) --> api (FastAPI) --> PostgreSQL (app data, scan queue, results, history)
                        |        --> Redis (rate limits, dashboard cache; optional)
                        |        --> S3 (uploaded files, reports, push batches)
                        |        --> KMS (data keys sealing source credentials)
worker (same package) --claims scans--> sources (read only) / DuckDB for files
scheduler (in the worker, multi-replica safe) --> creates scans when due
```

- **One Python package, two processes:** `api` and `worker` (the worker also runs the
  scheduler and alert delivery). Both are stateless; run N of each.
- **Queue:** the `scans` table is the queue (`status`, `lease_until`, `attempt`); workers
  claim with `UPDATE ... WHERE id = (SELECT ... FOR UPDATE SKIP LOCKED)`, renew the lease
  while running, and a reaper re-queues expired leases. Creating a scan and enqueueing it
  are one transaction, so a scan is never lost between a database and a broker. ADR 0002
  explains why not Celery.
- **Scheduler:** due schedules are claimed with the same `SKIP LOCKED` pattern and
  `next_run_at` is advanced in the same transaction, so N replicas create each scheduled
  scan once.
- **Check engine:** `engine/` turns a check into a SQLAlchemy Core expression and compiles
  it for the source dialect (`postgresql`, `mysql`, `sqlite`, `mssql`, `duckdb`). One query
  per dataset computes all the aggregate counts at once (sum of case expressions); sample
  queries fetch up to N failing rows per failing check. Dialect gaps (regex, quantiles,
  standard deviation) have per-dialect implementations or an exact streamed fallback.
  `sqlglot` parses custom SQL to enforce a single read-only `SELECT`.
- **Connectors:** a `Connector` protocol, one file per backend; adding a database is a file.
- **Files:** uploads go to S3; the worker downloads to a temp dir and DuckDB reads CSV,
  JSON and Parquet natively; Excel goes through Polars (calamine) into DuckDB.

## Data model (main tables)

`users`, `revoked_sessions`, `projects`, `project_members`, `api_keys`, `connections`
(sealed secret), `datasets` (kind, connection, relation or query or file, schedule,
settings), `dataset_files` (versions), `checks` (type, column, params JSON validated by type,
severity, tolerance, dimension, enabled), `scans` (status, trigger, lease, timings, score,
counts, the columns it saw: schema drift is the diff), `check_results` (scan, check,
evaluated, failed, sample JSON, error), `scan_profiles` (scan, column stats JSON),
`metric_points` (dataset, metric, key, value, at: the history), `daily_scores` (the
dashboard rollup), `anomalies`, `alert_channels` (sealed config), `alert_rules`,
`incidents`, `notifications` (the outbox, one per incident, channel and event),
`audit_log`, `org_settings`. Indexes on every filter and sort the API exposes; keyset pagination for scans,
results and audit.

## API surface (v1)

Auth (`/auth/*`), users and admin, projects and members, API keys, connections (CRUD, test,
tables, columns), datasets (CRUD, upload, versions, preview, profile, suggestions),
checks (CRUD, bulk, YAML import and export, AI draft), scans (create, list, get, cancel,
results, samples, CSV, PDF, wait), push (`POST /datasets/{id}/records`), metrics and
history, anomalies, incidents (list, ack, resolve), alert channels and rules (CRUD, test),
dashboard summaries, reports, audit, settings, system (`/healthz`, `/readyz`, `/metrics`).

## Screens

Login, signup (first user is admin), dashboard (score, datasets, records scanned, failed
checks, duplicates, dimension breakdown, trend, recent issues), datasets, new dataset
(connection table picker or file upload or REST or push), dataset detail with tabs
(overview, profile, checks with suggestions, scans, incidents, settings), scan detail
(results with failing samples, download), connections, alerts (channels and rules),
incidents, reports, API keys, members, project settings, audit, admin users and system.

## Terraform modules

`network`, `database` (RDS PostgreSQL), `cache` (ElastiCache), `storage` (S3), `kms`,
`secrets`, `email` (SES), `ecr`, `service` (ECS Fargate api, worker, web behind an ALB),
`observability` (CloudWatch logs, alarms). Envs `local-floci`, `aws-dev`, `aws-prod`.

## Test plan

Unit (check compiler per dialect, SQL guard, scoring, anomaly maths, suggestions, cron,
profiling against in-memory DuckDB, sealing, schemas), integration (every endpoint with
roles, the golden corpus across all source backends, the queue under crash and
concurrency, scheduling with replicas, alerts with Mailpit and a webhook sink, reports,
push, API keys, mock LLM), `test-matrix` (storage local and S3, sealing local and KMS),
OpenAPI drift, e2e Playwright journeys, Puppeteer QA, Terraform gates,
`make bench`.
