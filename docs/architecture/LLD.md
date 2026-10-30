# Low-level design

Module by module, what each package owns and the decisions inside it. Paths are relative to
`apps/api/src/dataquality/` unless they say otherwise.

## Layout

Package by domain: each domain owns its `router.py` (HTTP only), `schemas.py` (the public
contract), `service.py` (rules) and `models.py` (its tables). Dependencies point inward:
router, service, data. A domain calls another domain's service, never its tables. Code that
must not import the web layer (the engine, the sources) has no FastAPI imports at all.

| Package | Owns |
| --- | --- |
| `core/` | `config.py` (every setting, `guard()`), `db.py` (engine, session, `Base`), `container.py` (the dependency container), `kv.py` (Redis or memory key value store), `sealing.py`, `storage.py`, `mail.py`, `net.py` (outbound URL rules), `middleware.py`, `errors.py`, `logs.py`, `tracing.py`, `tasks.py` (periodic task registry), `security.py` (passwords, sessions, API keys) |
| `auth/` | Sign in and out, session revocation, the current user, CSRF |
| `users/`, `org/` | Accounts (admin managed), first-run sign-up, instance settings (sign-up, AI) |
| `projects/` | Projects, members and roles, API keys, `access.py` (the `Principal` every project route resolves) |
| `connections/` | Database connections: create, test, list tables, sealed passwords, SQLite uploads, `friendly()` driver messages |
| `datasets/` | Datasets of every kind, file versions, uploads, push batches, preview, schedules, and `source.py` (stored dataset to open relation) |
| `checks/` | Check CRUD, bulk create, checks as code (YAML) |
| `engine/` | The check engine: specs, compiler, dialects, runner, profiler, relations, SQL guard, patterns, scoring, anomaly detection, suggestions. Pure Python plus SQLAlchemy Core; no database of its own |
| `sources/` | Opening sources: `sql.py` (read-only database sessions), `files.py` (DuckDB), `rest.py` (fetching records) |
| `scans/` | The queue, the executor, completion, history, reports, periodic tasks, the scan API |
| `alerts/` | Channels, rules, incidents, the notification outbox and its delivery |
| `dashboard/` | The cached project dashboard |
| `audit/` | The append-only audit log |
| `ai/` | The optional assistant (plain language to a check, incident explanations) |
| `system/` | Health, readiness, metrics, system info |
| `client/cli.py` | The `dq` command for CI |
| `cli.py` | The `dataquality` command: `serve`, `worker`, `migrate`, `revision`, `create-admin`, `seed-demo`, `openapi` |
| `demo/seed.py` | The demo, built through the real API |
| `apps/api/src/mockai/` | A test fixture: an OpenAI-compatible stand-in, a webhook sink and a demo REST feed. Never deployed to AWS |

## `core/`

- **`config.py`**: one `Settings` (pydantic-settings), read from the environment only here.
  `guard()` refuses to boot in production with demo or short secrets, equal session secret
  and API key pepper, `COOKIE_SECURE=false`, `MAIL_BACKEND=log`, `STORAGE=local`, a local
  master key that is a demo value (unless `KEY_MODE=kms`), or `AWS_ENDPOINT_URL` with
  `DATAQUALITY_CLOUD=aws`. Every variable is in [configuration.md](../guides/configuration.md).
- **`container.py`**: `Container.build(settings)` wires the database, the KV store, one
  shared `httpx.AsyncClient` (redirects off), the sealer and the object storage. Routes get
  it through `Depends`; tests build their own.
- **`kv.py`**: the `KV` protocol (`get`, `set`, `incr`, `hit`, `ping`) with `RedisKV` and
  `MemoryKV`. The memory backend is an LRU bounded by entries and bytes plus fixed window
  rate counters, exact for one process.
- **`middleware.py`**: pure ASGI. `RequestContextMiddleware` sets the request id, adds
  security headers and logs one line per request. `BodySizeLimitMiddleware` refuses bodies
  over `MAX_BODY_BYTES` with 413; upload routes (`datasets/upload`, `datasets/{id}/files`,
  `connections/sqlite`) get `MAX_UPLOAD_BYTES` and are streamed, never buffered; push and
  YAML routes get `MAX_PUSH_BYTES`. The larger limits apply only when the request carries a
  valid session token or something shaped like an API key, so anonymous requests stay small.
- **`errors.py`**: typed errors (`AppError`, `NotFoundError`, `ConflictError`,
  `AuthenticationError`, `PermissionDeniedError`, `RateLimitedError`, `GoneError`) mapped once
  to `{"error": {"code", "type", "message", "details"}}`. Validation errors are 422 with a
  list of field errors; integrity races are 409; anything unhandled is a logged 500 with no
  stack trace in the body.
- **`net.py`**: `check_url` (http or https, no link-local or metadata host, numeric IPv4
  spellings canonicalised first), `resolves_safely` (every resolved address checked at call
  time, private and loopback refused when the caller says so).
- **`sealing.py`**, **`storage.py`**, **`mail.py`**: one Protocol each with a local and an
  AWS implementation chosen by config (`KEY_MODE`, `STORAGE`, `MAIL_BACKEND`).

## `engine/`

The engine is the product. Its only inputs are a SQLAlchemy `Connection`, a dialect name and
a `Relation`; it returns `Outcome` objects. Details in [engine.md](engine.md) and
[checks.md](checks.md).

| Module | Role |
| --- | --- |
| `spec.py` | `CheckType` (16 types), `Dimension`, `Severity`, one strict parameter model per type (`extra="forbid"`), `Tolerance`, `CheckSpec`. `parse_params` is the only way parameters enter the system |
| `patterns.py` | Presets (email, phones, URL, UUID, IPv4, PIN, ZIP, PAN, ISO date, slug), type patterns, the portable regex rules (`validate_regex`), `shape()` |
| `relation.py` | `Relation` and `ColumnInfo`; reflection of tables (DuckDB through its own `information_schema`), read-only query relations typed from a sample of 500 rows, logical types |
| `dialects.py` | `FullMatch`, `StrLen`, `Shape`, `Exact` and `blank`: the constructs whose SQL differs per database, compiled per dialect with `@compiles` |
| `compiler.py` | `compile_check(spec, relation, dialect) -> Plan`: the evaluated and failed conditions, or the plan kind the runner executes separately (`AGGREGATE`, `PYTHON`, `COUNT`, `GROUPS`, `SHAPES`, `OUTLIERS`, `CUSTOM`, `DATASET`) |
| `runner.py` | `CheckRunner.run(checks)`: compile, one aggregate query, the separate plans, the streamed Python pass, samples, masking. `ScanStopped` on cancel or deadline; `DatasetUnreadableError` when even the row count fails |
| `profiler.py` | Column profiles computed in the source: counts, distinct, min and max, mean and standard deviation, nearest-rank quantiles, histograms, top values, shapes, lengths, semantic hints |
| `sqlguard.py` | `check_read_only` and `check_predicate` with sqlglot ([security.md](security.md)) |
| `scoring.py` | Pass rates, dimension and dataset scores ([scoring.md](scoring.md)) |
| `anomaly.py` | `detect()`: robust z-score with guards ([anomalies.md](anomalies.md)) |
| `suggest.py` | Suggested checks from a profile with plain rules, each with a reason |

## `sources/` and `datasets/source.py`

Opening a source is split in two so blocking drivers never run on the event loop and secrets
and network calls never run in a thread:

1. `prepare()` (async): finds the datasets referenced by referential checks (same project
   and same source), opens sealed secrets, downloads files from object storage into a
   private temp directory under `WORK_DIR`, fetches REST records and writes them as NDJSON,
   checks the database host with `resolves_safely`. Yields a plain `SourceSpec`.
2. `with_relation(spec, fn)` (sync, in a worker thread): opens the database with
   `sources/sql.open_sql` or DuckDB with `sources/files.open_files`, builds the relation and
   a reference resolver (cached per scan), and calls `fn`. The connection is closed and the
   temp directory removed afterwards.

`sources/sql.py` creates one engine per use with `NullPool` (no pooled connections to a
customer's database), sets read-only and timeouts per dialect, wraps everything in a
transaction that is always rolled back, and lists tables and views outside system schemas.
`sources/files.py` detects the format from the extension and magic bytes, loads each file as
a DuckDB table and then locks DuckDB down. `sources/rest.py` fetches JSON without following
redirects, with a byte cap, and flattens nested values to JSON text.

## `scans/`

| Module | Role |
| --- | --- |
| `queue.py` | `enqueue`, `claim`, `renew`, `owned`, `reap` ([queue.md](queue.md)) |
| `executor.py` | Runs one claimed scan: loads the dataset and its enabled checks, prepares the source, ends the read transaction before the long part, runs checks and the profile in a thread, keeps a heartbeat, and maps every failure to a final status and a message a person can act on |
| `complete.py` | Writes the outcome in one transaction guarded by `(id, attempt, worker)`; alerts in a savepoint so an alerting failure never costs the results |
| `history.py` | Metric points per scan, anomaly detection against the last 30 points per series, schema drift against the previous successful scan |
| `tasks.py` | Periodic tasks: `schedule`, `reap`, `notify`, `retention`, `queue_depth` |
| `reports.py` | Scan CSV and PDF, dataset history CSV, project summary PDF |
| `service.py`, `router.py` | Request, list (keyset on `created_at`), get, cancel, wait, profiles, suggestions, metric series, anomalies, reports |

## `worker.py`

`serve()` starts `WORKER_CONCURRENCY` scanner loops and one periodic loop. A scanner claims
and runs scans until the queue is empty, then waits up to `WORKER_POLL_INTERVAL_S` or until
the periodic loop wakes it (the scheduler may have queued work). The periodic loop runs every
registered task each `TASK_INTERVAL_S`, at once again when a task did work. SIGTERM stops
claiming, lets running scans finish, and exits; a scan killed mid-way is safe because its
lease expires and the reaper re-queues it. Metrics are served on `WORKER_METRICS_PORT`.

## `alerts/`

`engine.evaluate` turns a finished scan into incidents and notification rows, keyed so that
one problem has one open incident and one notification per channel and event.
`delivery.deliver_due` sends due rows with retries and backoff; `delivery.sign` and
`delivery.verify` implement the webhook signature. See [alerts.md](alerts.md).

## `projects/access.py`

Every project route depends on `Viewer`, `Editor`, `Owner`, `Scanner` or `Pusher`. Each
resolves a `Principal` (project, role, actor, API key) first: an API key from `X-API-Key` or
a bearer token starting `dq_`, otherwise the signed-in user. A project the caller cannot see
answers 404. API keys have scopes instead of roles; routes that need the owner role refuse
every key. Details in [security.md](security.md).

## `checks/service.py`

`validate()` is the single gate for a check's shape: the type's parameter model, the column
rule, the filter (`check_predicate`), and for custom SQL the read-only guard, all in the
connection's dialect (`duckdb` for file, REST and push datasets). Names are unique per
dataset; a missing name is built from the type and column. Checks as code: `export_yaml`,
`parse_yaml`, `apply_yaml` (upsert by name, optional prune, idempotent). See
[checks-as-code.md](../guides/checks-as-code.md).

## `ai/`

Off by default (instance settings). With it off, the draft and explain endpoints answer 409
before any network code runs. With it on, the model sees column names, types and profile
statistics, and sample values only when the project sets `ai_allow_samples` (masked columns
never). A drafted check goes through `checks/service.validate` and is returned to the person,
never saved by the assistant.

## Web (`apps/web/src/`)

`app/` holds routes only; `features/<domain>/` holds components, hooks and API calls per
domain; `lib/api` is the client generated from `docs/api/openapi.yaml`
(`openapi-typescript`), `lib/query-keys.ts` the query keys and `STALE` times. Server state
goes through TanStack Query hooks per feature. Cookie mutations send `X-DQ-CSRF: 1`.
`middleware.ts` sets the Content-Security-Policy and redirects signed-out visitors to
`/login`.
