# Operations

## Health

| Endpoint | Meaning |
| --- | --- |
| `GET /healthz` (and `/health`, which adds the version) | The API process is up |
| `GET /readyz` | Postgres answers within 2 s (503 otherwise). Redis, when configured, is probed and reported; its failure shows as `degraded` with 200, because rate limits and caches fall back to memory |
| `GET /api/v1/system` (admins) | Version, environment, storage, key mode, cache and mail backends, whether Redis answers, the queue (queued, running, age of the oldest queued scan), counts of projects, datasets, users and scans |
| Worker `:9464/metrics` | The worker serves no HTTP API; Compose treats it as healthy while its metrics endpoint answers |
| Web `/api/healthz` | The Next.js server is up (its own route, not proxied) |

## Metrics

Prometheus metrics on the API's `/metrics` and the worker's `WORKER_METRICS_PORT`. Each
process has its own registry, and almost every series below is produced by the worker, so
scrape the workers.

| Metric | Type | Labels | Meaning |
| --- | --- | --- | --- |
| `dataquality_scans_total` | counter | `status`, `trigger` | Scans finished (`succeeded`, `failed`, `cancelled`) by trigger (`manual`, `schedule`, `api`, `push`) |
| `dataquality_scan_seconds` | histogram | `source` | Scan duration from claim to result, by dataset kind (`table`, `query`, `file`, `rest`, `push`) |
| `dataquality_rows_scanned_total` | counter | `source` | Rows covered by finished scans |
| `dataquality_check_results_total` | counter | `type`, `status` | Check results by check type and `pass`, `fail`, `error` |
| `dataquality_queue_depth` | gauge | `status` | Scans `queued` and `running`, refreshed every task interval |
| `dataquality_notifications_total` | counter | `channel`, `result` | Alert deliveries by channel kind, `sent` or `error` |
| `dataquality_anomalies_total` | counter | `kind` | Anomalies found (`metric`, `schema`) |
| `dataquality_dependency_errors_total` | counter | `dependency`, `operation` | Failed calls to a dependency (for example alert evaluation in Postgres) |

On AWS the worker's metrics stay inside its task; the `observability` module derives
CloudWatch metrics from the worker's JSON logs instead (`ScansTotal`, `ScansFailed`,
`ScansRequeued`, `ScanErrors`) and alarms on 5xx, API latency, unhealthy targets, CPU and
memory per service, database CPU, storage and connections, cache memory and CPU, worker
errors, a burst of failed scans and any re-queued scan. To alarm on queue depth, add a
Prometheus or ADOT sidecar to the worker task.

Logs are one JSON object per line with a request id (`x-request-id` is accepted from the
caller or generated, and returned). Useful worker lines: `scan finished` (scan, status, ms),
`reaped scans` (requeued, failed), `notification failed` (channel, attempt, error),
`alert evaluation failed`.

## Scaling

| Signal | Action |
| --- | --- |
| `dataquality_queue_depth{status="queued"}` stays above zero, or the oldest queued scan is old (`/api/v1/system`) | More worker capacity: raise `WORKER_CONCURRENCY` (scans per worker, default 4) or run more worker replicas |
| Scans of one database queue while workers are idle | That connection is at its `max_concurrent_scans` (default 2); raise it if the database can take it, or point the connection at a replica |
| Worker memory grows during file scans | Lower `DUCKDB_MEMORY_LIMIT` (DuckDB spills to the scan's temp directory) or give the worker more memory and disk |
| Slow profiles on very large tables | Lower `PROFILE_MAX_ROWS` (profiles sample, checks stay exact), or turn profiling off per dataset |
| Many API replicas | Run Redis (`REDIS_URL`), so rate limits and dashboard invalidation are shared |

Database connections: every process holds a pool of `DB_POOL_SIZE + DB_MAX_OVERFLOW`; keep
(API replicas + worker replicas + migrate) x that number under the database's connection
limit. Each running scan also holds one connection to its source database, closed when the
scan ends.

Locally: `DQ_WORKER_CONCURRENCY=8 make up`, or `docker compose ... up --scale worker=3`.
On AWS: `worker_count` in the environment's `main.tf`, `api_extra_environment` for
`WORKER_CONCURRENCY`.

## Retention

Each project keeps scan results for `retention_days` (default 90, project settings). The
worker's `retention` task deletes up to 500 finished scans per project per tick, never a
dataset's latest scan; their check results and profiles go with them. Metric points, daily
rollups and anomalies are kept, so trend charts and anomaly baselines outlive the results.
Incidents and the audit log are not purged. Pushed batches (each push is a new version of
a push dataset) older than the retention are deleted, rows and stored objects, except the
batch the dataset currently points at. Uploaded file versions are kept until their dataset
is deleted: they are the data, not a by-product.

## Backup and restore

Locally:

```bash
make backup                                   # backups/<timestamp>/: pg_dump + the objects bucket
make restore BACKUP=backups/20261030T060000Z  # stops api, worker and web, restores, starts them
```

`scripts/backup.sh` takes a consistent `pg_dump --format=custom` (one transaction, the app
keeps serving) and syncs the bucket from Floci. `scripts/restore.sh` runs `pg_restore
--clean --if-exists` and syncs the objects back.

On AWS: RDS automated backups and snapshots (retention set in the environment), and S3
versioning with noncurrent versions kept for `noncurrent_retention_days`. Back up the
secrets too: without the KMS key (or `LOCAL_MASTER_KEY` in local mode) and the original
`SESSION_SECRET` and `API_KEY_PEPPER`, a restored database has unreadable source passwords
and every API key stops working. The KMS key has a deletion window; never schedule its
deletion while data sealed by it exists.

## Upgrading

1. Read the `CHANGELOG.md` entry.
2. Back up.
3. Deploy the new image: locally `make up` rebuilds and runs `migrate` before the API and
   worker start; on AWS `make aws-deploy ENV=... TAG=<new>` runs migrations as a one-off task
   before the services roll.
4. Migrations are forward-only Alembic revisions, never edited once released.

Workers stop gracefully on SIGTERM (no new claims, running scans finish). If a deployment
kills a worker mid-scan, the scan's lease expires and another worker re-runs it.

## Rotating secrets

| Secret | Effect of rotating |
| --- | --- |
| `SESSION_SECRET` | Every session ends; people sign in again |
| `API_KEY_PEPPER` | Every API key stops working; owners create new keys |
| `LOCAL_MASTER_KEY` | Sealed values become unreadable: re-enter connection passwords, REST headers and channel URLs. Prefer `KEY_MODE=kms`, where KMS rotates key material without re-sealing |
| A source database password | Edit the connection and enter the new password; it is sealed again |
| A webhook signing secret | Edit the channel and set a new secret; update the receiver |

## Common admin tasks

| Task | How |
| --- | --- |
| Create or reset an admin | `make admin EMAIL=you@example.com` locally; `make aws-admin` on AWS |
| Open or close self sign-up, turn AI on | Admin, **Instance settings** |
| See who changed what | Admin, **Audit log** (append-only) |
| Find why a scan failed | The scan page shows the message; `make logs SERVICE=worker` has the details |
| A notification failed | The incident shows each notification with its attempts and last error. After 8 attempts it stays `failed` and is not re-sent; fix the channel and confirm with **Send test**, and later events are delivered normally |
