# Testing

Every gate runs locally against Docker; nothing needs a cloud account.

| Command | What it runs | Needs |
| --- | --- | --- |
| `make lint` | ruff check and ruff format check (API), ESLint (web) | uv, pnpm |
| `make typecheck` | mypy `--strict` (API), `tsc --noEmit` (web) | uv, pnpm |
| `make test` | API unit tests (no database, no network); web Vitest | uv, pnpm |
| `make test-integration` | API unit and integration tests against real Postgres, Redis and the source databases (started if needed by `scripts/test-db.sh`), with an 85% coverage floor on `dataquality` | Docker, uv |
| `make test-integration MSSQL=1` | The same, plus the SQL Server source (an amd64 image, emulated on Apple silicon) | Docker |
| `make test-matrix` | The integration suite under every key and storage backend: local AES-GCM or Floci KMS, local disk or Floci S3 | `make up` (Floci) |
| `make bench` | Profile and check a 1,000,000 row PostgreSQL table, with peak memory | `make up` |
| `make e2e` | Playwright (Chromium) against the running stack | `make up && make demo` |
| `make qa` | Puppeteer: every page in light and dark at desktop and phone width | `make up && make demo` |
| `make openapi` | Regenerates `docs/api/openapi.yaml`; a unit test fails when it drifts from the app | uv |
| `make tf-validate tf-lint tf-security` | `terraform validate` (3 environments), tflint, checkov | Docker |
| `make tf-aws-on-floci` | The full `aws-dev` environment planned, applied, re-planned and destroyed against a throwaway Floci | Docker |
| `make sanitize` | Credentials, cloud ids, env files and em or en dashes in committed files | bash |

## Unit tests (`apps/api/tests/unit/`)

| Suite | Covers |
| --- | --- |
| `engine/test_pure.py` | The SQL guard (read-only SQL passes; writes, `INTO`, locks, side-effect functions and tricks refused; filters must be plain conditions), presets match their examples, non-portable regex refused, parameter validation per type, tolerance, each dialect's spelling of the helpers, logical types, scoring, anomaly detection (drops flagged, noise not), suggestions |
| `engine/test_runner.py` | The runner on in-process DuckDB and SQLite: the golden counts, bounded and masked samples, referential checks, errors landing on the check that caused them, the dataset filter, stop and deadline, query relations, the Python regex path used for SQL Server |
| `core/test_config.py` | Production refuses demo secrets and unsafe options; development never does; KMS mode needs no local key |
| `core/test_kv.py` | The memory KV: expiry, LRU, byte budget, counters, rate windows |
| `core/test_net_private.py` | Names that resolve to loopback are refused when private addresses are off; metadata always |
| `mail/test_mail.py` | The log, SMTP and SES mail backends |
| `system/test_openapi_drift.py` | The committed OpenAPI document matches the app |

## Integration tests (`apps/api/tests/integration/`)

`conftest.py` serves the real API over HTTP on a thread and runs the real scan worker
(`dataquality.worker.serve`) on another, against real Postgres, Redis and source databases.
The database is built by the migrations on every run (so they are tested too) and every table
and the Redis index are emptied between tests. Each file maps to acceptance criteria from
[docs/PLAN.md](../PLAN.md):

| File | Acceptance criteria |
| --- | --- |
| `test_golden_parity.py` | AC1, AC2, AC9: exact counts for every planted defect on every backend (below) |
| `test_safety.py` | AC3, AC4: write SQL in a custom check refused; scan sessions refuse writes on each database; passwords sealed and never returned or logged; actionable messages for wrong passwords; metadata hosts refused |
| `test_profiling.py` | AC5, AC6: profiles describe the data; suggestions from clean data catch the defects |
| `test_queue.py` | AC8: racing schedulers create one scan per slot; a dead worker's scan is retried and finishes once; out of attempts fails with a reason; cancel; idempotency keys; per-connection limits |
| `test_monitoring.py` | AC10, AC11, AC14: push records and a volume drop anomaly; API keys scoped to one project; a `scan` key triggers and waits; schema drift between uploads; REST datasets |
| `test_alerts.py` | AC12: one incident and one notification per channel until resolved, auto-resolve, signed webhooks; score and scan failure rules; test sends; private webhooks refused unless allowed; many incidents on one connection (the `ON CONFLICT` predicate, [alerts.md](../architecture/alerts.md#exactly-one-incident-and-one-notification)) |
| `test_access_and_reports.py` | AC13, AC15, AC16: CSV and PDF match the API; project roles hold on every route; AI off by default and careful with data when on (mock LLM) |
| `test_api.py` | Checks as code round trip, tolerance and filters, validation messages, first sign-up becomes admin, unreadable uploads, large bodies need a real session, query datasets and masking, a missing table fails the scan with a reason, audit and system |
| `test_crud.py` | Channels and rules, manual resolve, AI explanations on and off, projects, members and sessions, the server CLI |
| `test_cli.py` | The `dq` CLI as a CI gate and for checks as code |

### Isolation

`TEST_DATABASE_URL` (default `.../dataquality_test` on port 4942) and `TEST_REDIS_URL`
(default Redis index 15 on port 4979) choose where the suite runs. It drops and recreates its
database, so it refuses any database whose name lacks `test`, and any non-local host unless
`ALLOW_REMOTE_TEST_DB=true`. Two suites with different databases and Redis indexes can run
at once. `TEST_KEY_MODE`, `TEST_STORAGE`, `TEST_AWS_ENDPOINT`, `TEST_KMS_KEY_ID` and
`TEST_OBJECTS_BUCKET` switch the backends (`make test-matrix` sets them).
`TEST_SOURCE_ADMIN_PASSWORD` overrides the source admin password read from
`deploy/compose/.env`.

## The golden dataset and the parity matrix

`apps/api/tests/golden.py` builds a `customers` table of 203 rows (200 base rows with
defects planted at known positions, then two exact copies of clean rows and one repeated id
with other values) and an `orders` table of 60 rows. Every expected number follows from how
the rows are built, not from running the engine. `apps/api/tests/sources.py` loads the same
rows into every source and gives each database a read-only login, which the platform uses.

| Check | Planted | Expected (status, evaluated, failed) |
| --- | --- | --- |
| `email` not null | 5 NULL and 3 blank emails | fail, 203, 8 |
| `customer_id` unique | ids 101, 121 and 151 twice | fail, 203, 3 |
| no duplicate rows | two exact copies | fail, 203, 2 |
| `email` pattern (email) | 4 invalid emails; blanks are not judged | fail, 195, 4 |
| `phone` pattern (E.164) | 6 invalid phones | fail, 203, 6 |
| `price` range (min 0) | 4 negative prices | fail, 203, 4 |
| `country` accepted values | 5 unknown codes (`XX`, `India`, `in`, `us`, `ZZ`) | fail, 203, 5 |
| `code` length 6 | 2 codes of the wrong length | fail, 203, 2 |
| `signup_date <= last_login` | 3 logins before signup | fail, 203, 3 |
| `zip_code` format consistency (0.99) | 5 zips of another shape | fail, 203, 5 |
| `price` outliers (z 3) | 2 prices of 99,999.99 | fail, 203, 2 |
| `age_text` type integer | 3 non-integers; 1 blank not judged | fail, 202, 3 |
| row count (min 1,000) | 203 rows | fail, 1, 1 |
| freshness (365 days) | recent logins | pass, 1, 0 |
| freshness (1 hour) | no login in the last hour | fail, 1, 1 |
| schema with `loyalty_tier` | the column does not exist | fail, 2, 1 |
| custom SQL `price > 1000` | the 2 outliers | fail, 203, 2 |
| `orders.customer_id` referential | 4 orders for missing customers | 4 failed |

`test_golden_parity.py` creates these checks on each backend, scans, and requires exactly
these results:

| Backend | How | When |
| --- | --- | --- |
| PostgreSQL | The demo source container | Always |
| MySQL | The demo source container | Always |
| SQLite | An uploaded database file | Always |
| SQL Server | The `source-mssql` container | With `MSSQL=1` (skipped otherwise, with a message) |
| CSV, Excel, JSON, Parquet | Uploaded files written from the same rows with Polars | Always |

The same counts on eight backends is what proves the per-dialect SQL means the same thing
everywhere ([engine.md](../architecture/engine.md#per-dialect-differences)). The `fresh
logins` check uses fixed timestamps from October 2026 and a 365 day limit, so it passes only
until about October 2027; move the timestamps or the limit before then.

## Benchmark

`make bench` (`apps/api/tests/bench/bench_million.py`) builds `bench_customers` once in the
demo source PostgreSQL, then runs the engine exactly as a scan does, through a read-only
login: 15 checks, then a profile, first on 100,000 rows and then on 1,000,000, reporting time
per phase and the process's peak memory. Measured on a laptop (Apple silicon, Docker
Postgres 16): 15 checks on 1,000,000 rows in 4.5 s, a 9 column profile in 9.8 s, peak memory
93 MB at both sizes. Memory that does not grow with ten times the rows shows the work stays
in the database.

## Browser tests

`make e2e` runs the Playwright suites in `e2e/` against the stack from `make up && make demo`
(the demo password comes from `deploy/compose/.env`). `make qa` runs `scripts/qa/qa.mjs`,
which visits every page in light and dark mode at desktop and phone width and fails on
console errors, failed requests, broken images, horizontal overflow or empty unexplained
states. `make screenshots` produces the curated screenshots and the tour GIF.
