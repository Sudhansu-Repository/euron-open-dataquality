# Configuration

Every setting of the API and the scan worker is an environment variable, read once at start
and validated (`apps/api/src/dataquality/core/config.py`); names are case-insensitive. The
API and the worker read the same settings. In production (`ENVIRONMENT=production`) both
refuse to start with demo or short secrets (under 32 characters), equal `SESSION_SECRET` and
`API_KEY_PEPPER`, a demo `LOCAL_MASTER_KEY` with `KEY_MODE=local`, `COOKIE_SECURE=false`,
`MAIL_BACKEND=log`, `STORAGE=local`, or an `AWS_ENDPOINT_URL` with `DATAQUALITY_CLOUD=aws`.

Settings that belong to an organisation, a project or a dataset are not environment
variables: they are edited in the app ([below](#settings-in-the-app)).

## API and scan worker (`Settings`)

### Runtime and database

| Variable | Default | Meaning |
| --- | --- | --- |
| `ENVIRONMENT` | `development` | `development`, `test` or `production` (production enables the guards above) |
| `LOG_LEVEL` | `INFO` | Log level of the JSON logs |
| `DATAQUALITY_CLOUD` | `local` | `local`, `floci` or `aws`: where AWS calls go (informational, plus the guard above) |
| `DATABASE_URL` | `postgresql+asyncpg://dataquality:dataquality@localhost:4942/dataquality` | The platform's own Postgres (asyncpg driver) |
| `DB_POOL_SIZE`, `DB_MAX_OVERFLOW` | `10`, `20` | Connection pool per process |
| `REDIS_URL` | empty | Rate limits and the dashboard cache. Optional: empty keeps them in process memory, exact for one replica ([ADR-0010](../architecture/adr/0010-redis-is-optional.md)) |
| `MEMORY_CACHE_MAX_BYTES` | `64000000` | Byte budget of the in-process cache used without Redis (at least 1,000,000) |
| `OTEL_ENABLED` | `false` | Install an OpenTelemetry SDK with an OTLP exporter, configured by the standard `OTEL_EXPORTER_OTLP_ENDPOINT` and `OTEL_SERVICE_NAME` |

### Sessions and links

| Variable | Default | Meaning |
| --- | --- | --- |
| `SESSION_SECRET` | dev value | Signs session tokens (HS256). At least 32 random characters in production |
| `API_KEY_PEPPER` | dev value | HMAC key for API key hashes. At least 32 random characters, different from `SESSION_SECRET` |
| `SESSION_TTL_HOURS` | `12` | Session lifetime |
| `COOKIE_SECURE` | `false` | Secure flag on the `dq_session` cookie; must be true in production |
| `CORS_ORIGINS` | `http://localhost:4910` | Comma separated origins allowed to call the API from a browser |
| `PUBLIC_URL` | `http://localhost:4910` | Where people open the app; used for links in alert emails, Slack messages and webhook payloads |

### Sealing, AWS and storage

| Variable | Default | Meaning |
| --- | --- | --- |
| `KEY_MODE` | `local` | `local` (AES-256-GCM with `LOCAL_MASTER_KEY`) or `kms` |
| `LOCAL_MASTER_KEY` | dev value | Key material for local sealing. Losing it makes every sealed password unreadable |
| `KMS_KEY_ID` | `alias/dataquality-local` | The KMS key or alias for `KEY_MODE=kms` |
| `AWS_REGION` | `us-east-1` | Region for KMS, S3 and SES |
| `AWS_ENDPOINT_URL` | unset | An AWS-compatible endpoint (Floci locally). Must be unset with `DATAQUALITY_CLOUD=aws` in production |
| `S3_FORCE_PATH_STYLE` | `false` | Path-style S3 addressing (needed by the emulator) |
| `STORAGE` | `local` | `local` (a directory) or `s3`. Production requires `s3` (replicas share uploads) |
| `LOCAL_STORAGE_DIR` | `./.data/objects` | Directory for `STORAGE=local` |
| `OBJECTS_BUCKET` | `dataquality-local-objects` | Bucket for `STORAGE=s3`: uploaded files and versions, pushed batches, SQLite databases |

AWS credentials come from the standard chain (task role, profile, environment); nothing in
the app reads a static key.

### Mail

| Variable | Default | Meaning |
| --- | --- | --- |
| `MAIL_BACKEND` | `log` | `log` (logged, kept in a small in-memory outbox; development and tests), `smtp` or `ses`. Production refuses `log` |
| `MAIL_FROM` | `DataQuality <alerts@dataquality.local>` | Sender of alert emails |
| `SMTP_HOST`, `SMTP_PORT` | `localhost`, `1025` | SMTP relay for `MAIL_BACKEND=smtp` (the Compose stack uses `mailpit`, `1025`) |

### Sources, uploads and limits

| Variable | Default | Meaning |
| --- | --- | --- |
| `SOURCE_ALLOW_PRIVATE` | `true` | Database hosts may resolve to private addresses (databases usually live on private networks). Metadata and link-local addresses are always refused |
| `OUTBOUND_ALLOW_PRIVATE` | `false` | REST datasets, Slack and webhooks may reach private and loopback addresses |
| `STATEMENT_TIMEOUT_S` | `300` | Upper bound of the per-statement timeout on source databases (1 to 86,400); SQLite and DuckDB have no per-statement timeout, the scan deadline applies there |
| `PROFILE_MAX_ROWS` | `5000000` | Larger datasets are profiled over their first rows (checks stay exact) |
| `DUCKDB_MEMORY_LIMIT` | `2GB` | Memory limit of the DuckDB that holds file, REST and push data during a scan |
| `WORK_DIR` | `./.data/work` | Temp directories for downloaded files, REST records and DuckDB spill files; removed after each scan |
| `MAX_BODY_BYTES` | `2000000` | Request body limit for ordinary routes (413 above it) |
| `MAX_UPLOAD_BYTES` | `500000000` | File and SQLite uploads (streamed, never buffered), for authenticated callers |
| `MAX_PUSH_BYTES` | `25000000` | Body limit for pushed records and YAML check files, for authenticated callers |
| `MAX_PUSH_RECORDS` | `50000` | Records per push request |
| `REST_MAX_BYTES` | `50000000` | Largest REST response a REST dataset may return |
| `SCAN_RPM` | `30` | Scan requests per project per minute (pushes are not counted) |

### Scan worker

| Variable | Default | Meaning |
| --- | --- | --- |
| `WORKER_CONCURRENCY` | `4` | Scans one worker runs at once (1 to 64) |
| `LEASE_S` | `60` | Scan lease; renewed every third of it. A worker silent for longer loses the scan to the reaper (10 to 3,600) |
| `MAX_ATTEMPTS` | `3` | Attempts before a scan whose worker keeps dying is failed (1 to 10) |
| `WORKER_POLL_INTERVAL_S` | `2` | How long an idle scanner waits before looking at the queue again |
| `TASK_INTERVAL_S` | `15` | How often the periodic tasks run (scheduler, reaper, notifications, retention, queue gauges) |
| `WORKER_METRICS_PORT` | `9464` | Prometheus endpoint of the worker; `0` disables it |

### AI (optional)

AI is off until an admin turns it on in instance settings, where the endpoint, model and key
are set (the key is sealed). Two environment variables bound it:

| Variable | Default | Meaning |
| --- | --- | --- |
| `AI_ALLOW_PRIVATE_ENDPOINTS` | `true` | Allow an AI base URL on a private host (a model inside your network). Metadata addresses are always refused |
| `AI_TIMEOUT_S` | `30` | Timeout of a model call |

## Process and container variables

| Variable | Default | Used by | Meaning |
| --- | --- | --- | --- |
| `PORT` | `8080` | `dataquality serve` | Listening port of the API |
| `FORWARDED_ALLOW_IPS` | `127.0.0.1` | `dataquality serve` | Addresses whose `X-Forwarded-For` is trusted (the Compose network uses `*`, AWS the VPC CIDR) |
| `DATAQUALITY_ADMIN_PASSWORD` | prompt | `dataquality create-admin` | The password, instead of a prompt (for one-off tasks) |
| `API_INTERNAL_URL` | `http://localhost:4930` | web | Where the Next.js server proxies `/api/*` and the probes |

## The `dq` CLI

| Variable | Default | Meaning |
| --- | --- | --- |
| `DQ_URL` | `http://localhost:4930` | The API (or the web origin, which proxies `/api`) |
| `DQ_API_KEY` | none | A project API key (`dq_...`) |
| `DQ_PROJECT` | none | The project id |
| `DQ_TIMEOUT` | `300` | Seconds to wait for a scan |

See [checks-as-code.md](checks-as-code.md).

## Local stack (`deploy/compose/.env`)

Generated by `make env` (`scripts/gen-local-env.sh`) with random values; never committed.

| Variable | Meaning |
| --- | --- |
| `SESSION_SECRET`, `API_KEY_PEPPER`, `LOCAL_MASTER_KEY` | The secrets above |
| `DQ_DEMO_PASSWORD` | Password of every demo account |
| `DQ_SOURCE_ADMIN_PASSWORD` | Admin password of the demo source databases (the seed writes their data with it) |
| `DQ_READER_PASSWORD` | Password of the read-only `dq_reader` login the demo connections use |
| `DQ_WEB_PORT`, `DQ_API_PORT`, `DQ_PG_PORT`, `DQ_REDIS_PORT`, `DQ_MAILPIT_PORT`, `DQ_MOCK_AI_PORT`, `DQ_FLOCI_PORT` | Host ports: 4910, 4930, 4942, 4979, 4925, 4950, 4966 |
| `DQ_SOURCE_PG_PORT`, `DQ_SOURCE_MYSQL_PORT`, `DQ_SOURCE_MSSQL_PORT` | Demo source ports: 4943, 4906, 4933 |
| `DQ_LOG_LEVEL`, `DQ_WORKER_CONCURRENCY` | Passed to the containers as `LOG_LEVEL` and `WORKER_CONCURRENCY` |
| `DQ_MSSQL_SA_PASSWORD` | SA password of the optional SQL Server source (`make up MSSQL=1`) |

The demo seed (`dataquality seed-demo`) also reads `DQ_DEMO_API_URL` (default
`http://api:8080`), `DQ_DEMO_MOCK_URL` (`http://mock-ai:4950`), `DQ_DEMO_READER_PASSWORD`,
`DQ_DEMO_SOURCE_PG_ADMIN`, `DQ_DEMO_SOURCE_MYSQL_ADMIN` and `DQ_DEMO_DAYS` (`30`), which the
Compose file sets. The local stack also sets `SCAN_RPM=600` so the demo can replay 30 days
quickly, and `OUTBOUND_ALLOW_PRIVATE=true` for the demo webhook sink. For `make up-aws`,
`deploy/compose/.env.aws` holds `AWS_REGION`, `AWS_PROFILE`, `OBJECTS_BUCKET` and
`KMS_KEY_ID` ([local-with-aws.md](local-with-aws.md)).

## Settings in the app

| Scope | Setting | Default | Who |
| --- | --- | --- | --- |
| Instance | Site name, open sign-up, AI on or off, AI base URL, model and key | sign-up closed, AI off | Admin |
| Project | `sample_size`: failing rows kept per check (0 to 200) | 20 | Owner |
| Project | `retention_days`: how long scan results are kept (1 to 3,650) | 90 | Owner |
| Project | `anomaly_sensitivity`: robust z-score threshold (2 to 10) | 3.5 | Owner |
| Project | `ai_allow_samples`: send sample values to the AI model | false | Owner |
| Connection | `max_concurrent_scans` (1 to 20), SSL mode (`disable`, `prefer`, `require`, `verify-full`), default schema | 2, `prefer` | Editor |
| Dataset | Filter, masked columns, tags, profile on or off, scan timeout (10 to 86,400 s), cron schedule and time zone | timeout 1,800 s, profile on, schedule off | Editor |
