# Data model

PostgreSQL 16, SQLAlchemy 2 models per domain, one Alembic revision for 0.1.0
(`apps/api/src/dataquality/migrations/versions/`). Timestamps are timezone-aware. Every
filter and sort the API exposes has an index, and the work queues (scans, due schedules,
leases, due notifications, open incidents) use partial indexes so they stay small however
much history accumulates.

## People and settings

| Table | Holds | Keys and indexes |
| --- | --- | --- |
| `users` | email, name, argon2id hash, role (`user`/`admin`), disabled, last login, failed logins, locked until, session version | Unique email. `session_version` is bumped on a password change, which ends every other session |
| `revoked_sessions` | Signed-out session ids (`jti`) until they would have expired | Primary key `jti`, index on `expires_at` for pruning. Postgres, never a cache, so eviction cannot bring a signed-out session back |
| `org_settings` | One row: site name, sign-up allowed, AI on or off, AI base URL and model, the sealed AI key | `CHECK (id = 1)`: a singleton |
| `audit_log` | Who (user id, email or `api-key:<name>`), what action, which target, details, IP, when | Bigint id, index on `at`. A trigger (`audit_log_append_only`) refuses every UPDATE and DELETE: history cannot be rewritten through the app's own login |

## Projects and access

| Table | Holds | Keys and indexes |
| --- | --- | --- |
| `projects` | name, slug, description, `sample_size` (failing rows kept per check, default 20, 0 to 200), `retention_days` (default 90), `ai_allow_samples` (default false), `anomaly_sensitivity` (default 3.5) | Unique slug |
| `project_members` | project, user, role (`viewer`/`editor`/`owner`) | Primary key `(project_id, user_id)`, index on `user_id` (the project list), `CHECK` on role |
| `api_keys` | project, name, 12 hex character `prefix`, `secret_hash` (HMAC-SHA256 with `API_KEY_PEPPER`), scopes, last used, revoked | Unique prefix (the lookup), index on `project_id`. The plaintext key is shown once and never stored |

## Sources and datasets

| Table | Holds | Keys and indexes |
| --- | --- | --- |
| `connections` | project, name, kind (`postgresql`/`mysql`/`sqlite`/`mssql`), `config` (host, port, database, username, SSL mode, default schema: nothing secret), `secret_sealed` (the password), SQLite file key, name and size, `max_concurrent_scans` (default 2), last test result and server version | Unique `(project_id, name)`, index on `project_id`, `CHECK` on kind. The sealed password uses `connection:<id>:password` as its context |
| `datasets` | project, name, slug, kind (`table`/`query`/`file`/`rest`/`push`), connection, schema and table or query SQL, `options` (file reader options, REST URL and records path), `secret_sealed` (REST headers), current file version, dataset filter, masked columns, tags, profile on or off, scan timeout (default 1800 s), cron schedule, time zone and `next_run_at`, and the latest scan denormalised (`last_scan_id`, `last_scan_at`, `last_status`, `last_score`, `last_row_count`, `last_failed_checks`) | Unique `(project_id, slug)`, indexes on `project_id` and `connection_id` (`ON DELETE RESTRICT`: a connection in use cannot be deleted), and the partial index `ix_datasets_due (next_run_at) WHERE schedule_enabled` the scheduler reads |
| `dataset_files` | One uploaded version or pushed batch: version number, filename, format, size, SHA-256, object storage key, record count, uploader | Unique `(dataset_id, version)`. The file itself is in object storage under `projects/<project>/datasets/<dataset>/<file>.<format>` |
| `checks` | dataset, name, description, type, column, `params` (validated per type), filter SQL, severity, `tolerance` (`max_count`, `max_percent`), dimension, enabled, origin (`manual`/`suggested`/`ai`/`yaml`) | Unique `(dataset_id, name)` (checks as code upserts by name), indexes on `dataset_id` and `project_id` |

## Scans and results

| Table | Holds | Keys and indexes |
| --- | --- | --- |
| `scans` | The queue and the record of each scan: project, dataset, connection, status (`queued`/`running`/`succeeded`/`failed`/`cancelled`), `cancel_requested`, trigger (`manual`/`schedule`/`api`/`push`), `scheduled_for`, `idempotency_key`, requester (user or API key), file version, profile on or off, `attempt`, `worker`, `lease_until`, queued, started and finished times, duration, row count, score, `dimension_scores`, counts (total, passed, failed, warned, errored), failing rows, duplicate rows, the columns as this scan saw them, error | `CHECK` on status. Unique `(dataset_id, scheduled_for)`: one scan per schedule slot however many schedulers race. Unique `(dataset_id, idempotency_key)`: a retried request returns the same scan. Partial `ix_scans_queue (queued_at) WHERE status = 'queued'` (claim), partial `ix_scans_lease (lease_until) WHERE status = 'running'` (reaper), `(dataset_id, created_at)` and `(project_id, created_at)` for the lists (keyset pagination), `connection_id` for the per-connection limit |
| `check_results` | One per check per scan, with a copy of the check as it was (name, type, column, params, severity, dimension) so history survives edits and deletion; status, evaluated, failed, failed percent, `observed` (check-specific numbers), `sample` (bounded failing rows, masked columns replaced), message, error, milliseconds | Indexes on `scan_id` (scan detail) and `(check_id, scan_id)`. `ON DELETE CASCADE` from scans; `check_id` set null when a check is deleted |
| `scan_profiles` | The column profile a scan computed: row count, rows profiled, sampled flag, time, `columns` (one JSON object per column) | Primary key `scan_id`, index on `dataset_id`. Its own table so dataset and scan lists never pull a profile |
| `metric_points` | History: dataset, scan, metric (`row_count`, `score`, `dimension`, `check_failed_pct`, `null_rate`, `distinct`, `mean`), key (the dimension, check id or column), value, time | Bigint id, index `(dataset_id, metric, key, at)` (one series in time order). Kept when scan results are purged, so trends and anomaly baselines outlive them |
| `anomalies` | Metric anomalies and schema changes: kind (`metric`/`schema`), metric, key, value, expected (the median), robust z, direction, the explanation in words, details | Indexes `(project_id, created_at)` and `(dataset_id, created_at)`; `scan_id` set null when the scan is purged |
| `daily_scores` | A rollup per dataset and day: scans, score sum, last score, failed checks, rows scanned | Primary key `(dataset_id, day)`, index `(project_id, day)`. Upserted in the scan's completion transaction; the dashboard trend reads only this |

## Alerts

| Table | Holds | Keys and indexes |
| --- | --- | --- |
| `alert_channels` | project, name, kind (`email`/`slack`/`webhook`), `config` (email recipients: nothing secret), `secret_sealed` (Slack or webhook URL and the webhook signing secret), `target_hint` (the host only, shown instead of the URL), enabled | Unique `(project_id, name)`, index on `project_id`, `CHECK` on kind |
| `alert_rules` | project, name, kind (`check_failed`/`score_below`/`anomaly`/`schema_change`/`scan_failed`), dataset (null: every dataset), minimum severity, score threshold, channel ids, notify on resolve, enabled | Index on `project_id`, `CHECK` on kind |
| `incidents` | project, dataset, rule, problem `key`, status (`open`/`acknowledged`/`resolved`), severity, title, detail, first and last scan, occurrences, opened, last seen, acknowledged (when, by whom), resolved, resolution (`cleared`/`manual`) | **Partial unique index `uq_incidents_open_key (rule_id, key) WHERE status <> 'resolved'`**: one unresolved incident per rule and problem, enforced by the database. Indexes `(project_id, opened_at)` and `(dataset_id, status)` |
| `notifications` | The outbox: incident, channel, event (`opened`/`resolved`), status (`pending`/`sent`/`failed`/`skipped`), attempts, next attempt, last error, sent at | **Unique `(incident_id, channel_id, event)`**: one notification per incident, channel and event. Partial `ix_notifications_due (next_attempt_at) WHERE status = 'pending'`, index on `project_id` |

## Why some things are where they are

- **The queue is a table.** A scan is created and queued in one commit, its history is the
  same row, and the claim, lease and reaper are SQL. See [queue.md](queue.md) and
  [ADR-0002](adr/0002-postgres-as-the-scan-queue.md).
- **Latest state is denormalised on `datasets`.** The dataset list and the dashboard read
  one row per dataset instead of the newest scan per dataset.
- **Results copy their check.** Editing or deleting a check does not rewrite what past scans
  measured.
- **Profiles, results and history are separate tables.** Each page reads only what it shows:
  the scan list never loads samples, the dataset list never loads profiles, and history
  survives result retention.
- **Uniqueness that matters is a constraint, not a check in code.** Schedule slots,
  idempotency keys, open incidents and notifications are all unique in the database, so two
  workers racing cannot create a second scan, incident or email.

## Retention

The worker's `retention` task deletes finished scans older than each project's
`retention_days`, 500 per project per tick, keeping every dataset's latest scan however old.
Deleting a scan cascades to its `check_results` and `scan_profiles`. `metric_points`,
`daily_scores` and `anomalies` stay, so trends and anomaly baselines outlive the results.
