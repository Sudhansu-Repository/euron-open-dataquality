# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-10-30

First public release: the check engine, sources, profiling, suggestions, scoring, history and
anomaly detection, alerts and incidents, reports, the API and CLI, the web app, and the AWS
Terraform.

### Added

- Sources: PostgreSQL, MySQL and MariaDB, SQL Server, and uploaded SQLite databases through
  connections with sealed passwords, connection tests with actionable messages, and a table
  browser; uploaded files (CSV, TSV, JSON, NDJSON, Parquet, Excel) with versions; REST
  endpoints (JSON, a records path, sealed request headers); and push datasets that
  applications post records to.
- Datasets of five kinds: a table or view, a read-only SQL query, a file, a REST endpoint, a
  push dataset; each with an optional filter, masked columns, tags, a scan timeout and a cron
  schedule with a time zone.
- A check engine that compiles 16 check types to SQL for the source's own dialect and runs
  them inside the source: `not_null`, `unique` (single or composite), `duplicate_rows`,
  `schema`, `type`, `range`, `pattern` (twelve presets or a portable regex), `accepted_values`,
  `length`, `freshness`, `row_count`, `referential`, `compare`, `format_consistency`,
  `outliers` and `custom_sql`. Row-level checks share one aggregate query per dataset; counts
  are exact; samples of failing rows are bounded and masked.
- Identical semantics on every backend: NULL is never invalid, blank text counts as missing,
  text compared exactly (binary comparison on MySQL and SQL Server), regex matching the whole
  value with a portable subset, and an exact streamed Python evaluation for regex on SQL
  Server. A golden dataset with planted defects gives the same counts on PostgreSQL, MySQL,
  SQLite, SQL Server, CSV, Excel, JSON and Parquet.
- Files, REST and push data checked in an in-memory DuckDB inside the worker, with external
  access switched off and the configuration locked after loading.
- Read-only by construction: generated SQL is `SELECT` only; custom SQL, query datasets and
  filters are parsed with sqlglot and refused unless they are one read-only query; sessions
  are read-only on PostgreSQL, MySQL and SQLite; statement timeouts on every source.
- Profiling in the source: counts, nulls, blanks, distinct values, minimum and maximum, mean,
  standard deviation, nearest-rank quantiles, histograms, top values, value shapes, text
  lengths and semantic hints; very large tables profiled over their first rows.
- Suggested checks derived from the profile with deterministic rules, each with its reason.
- Severity (`warn`, `error`), tolerance (a count or a percent of failing rows), dimension and
  per-check filters.
- The quality score: per dimension (completeness, validity, consistency, uniqueness,
  freshness, volume) and per dataset and project, from pass rates, documented with a worked
  example.
- A scan queue in PostgreSQL: claims with `FOR UPDATE SKIP LOCKED`, leases renewed by a
  heartbeat, a reaper that re-queues scans whose worker died (three attempts), writes guarded
  by attempt and worker, per-connection concurrency limits, cancel, idempotency keys, and a
  scheduler that creates each scheduled scan exactly once across worker replicas.
- History: metric points per scan (row count, score, dimensions, failing share per check,
  null rate, distinct count and mean per column), kept after results expire; a daily rollup
  for dashboards.
- Anomaly detection with a robust z-score (median and MAD) on row count, missing values,
  score and failing share, with guards against noise and a one-sentence explanation; schema
  drift (columns added, removed or retyped) between scans.
- Alerts: email, Slack and signed webhook channels (`X-DQ-Signature`, HMAC-SHA256 with a
  timestamp); rules for failed checks, score thresholds, anomalies, schema changes and failed
  scans; incidents that open once per problem, count occurrences, can be acknowledged, and
  resolve automatically; a notification outbox with retries and backoff; test sends.
- Reports: a scan as CSV (with formula neutralisation) and PDF, a dataset's history as CSV,
  a project summary as PDF.
- A REST API with OpenAPI documentation, project API keys with `read`, `scan`, `push` and
  `manage` scopes, scans that wait for their result (`?wait=`), push validation, and a
  consistent error envelope.
- Checks as code: YAML export and idempotent import with optional pruning, and the `dq` CLI
  (`dq scan --fail-on error`, `dq checks apply`, `dq push`) for CI.
- Accounts: users and admins, projects with owner, editor and viewer roles, an append-only
  audit log; argon2id passwords, lockout and throttling, sign-out revocation, CSRF header on
  cookie mutations, and production boot guards that refuse unsafe configuration.
- Sealed credentials: source passwords, REST headers, Slack and webhook URLs, webhook secrets
  and the AI key sealed with AES-256-GCM or AWS KMS, bound to their row; outbound URLs
  checked against metadata and, where configured, private addresses at save and call time.
- An optional AI assistant (any OpenAI-compatible endpoint, off by default): a plain-language
  rule drafted into a check that a person accepts, and incident explanations; sample values
  sent only when a project allows it.
- A web app (Next.js 15): dashboard, datasets with overview, profile, checks with suggestions,
  scans and settings, scan results with failing samples and downloads, connections, alerts,
  incidents, project settings with members and API keys, and admin pages for users, system,
  audit and instance settings; light and dark themes.
- A dashboard cache keyed by a per-project version counter that every finished scan bumps,
  and Redis that is optional (rate limits and caches fall back to process memory).
- Prometheus metrics, structured JSON logs with request ids, health and readiness probes,
  optional OpenTelemetry tracing.
- A local stack on Docker Compose with Floci provisioned by the same Terraform as AWS, demo
  source databases, Mailpit, and a demo seed with two projects and 30 days of real scans.
- Terraform modules and `aws-dev` and `aws-prod` environments: network, RDS PostgreSQL,
  ElastiCache, S3, KMS, Secrets Manager, SES, ECR, ECS Fargate behind an ALB with WAF, and
  CloudWatch logs, metrics and alarms; a one-command deploy script.
- Tests: unit tests, integration tests against real databases (including the golden parity
  matrix and the queue under crashes and races), a backend matrix (local or KMS sealing, local
  or S3 storage), browser end-to-end tests, a browser QA sweep, Terraform gates, and a
  1,000,000 row benchmark (15 checks in 4.5 s, a 9 column profile in 9.8 s, 93 MB peak worker
  memory at both 100,000 and 1,000,000 rows).

[Unreleased]: https://github.com/euron-sde-team/euron-open-dataquality/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/euron-sde-team/euron-open-dataquality/releases/tag/v0.1.0
