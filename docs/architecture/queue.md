# The scan queue

Scans are queued, claimed, leased and retried in PostgreSQL: the `scans` table is the queue
([ADR-0002](adr/0002-postgres-as-the-scan-queue.md)). The guarantees: a requested scan is
never lost, a scheduled slot produces one scan however many workers race, a scan whose worker
dies is retried and its result written once, and no source database runs more scans at once
than its connection allows. Code: `apps/api/src/dataquality/scans/queue.py`, `tasks.py`,
`executor.py`, `complete.py`, `worker.py`.

## States

```
queued ──claim──▶ running ──complete──▶ succeeded
  ▲                 │ ├──fail─────────▶ failed
  │                 │ └──cancel───────▶ cancelled
  └──reap (lease expired, attempts left)
queued ──cancel──▶ cancelled
running ──reap (lease expired, out of attempts)──▶ failed
```

## Enqueue

`queue.enqueue` inserts a `queued` row with `INSERT ... ON CONFLICT DO NOTHING RETURNING id`
in the **caller's transaction**. Creating a scan and queueing it are one commit, so there is
no window in which a scan exists but its message was lost (or a message exists for a scan
that rolled back), as there would be with a separate broker.

Two unique constraints make enqueueing idempotent:

- `(dataset_id, idempotency_key)`: an API client that retries `POST .../scans` with the same
  `idempotency_key` gets the scan that already exists;
- `(dataset_id, scheduled_for)`: the scheduler passes the schedule slot, so two schedulers
  racing on the same slot create one scan.

When the insert conflicts, `enqueue` returns the existing row and `new = false`.

## Claim

`queue.claim` runs in a short transaction:

1. `SELECT ... FROM scans WHERE status = 'queued' ORDER BY queued_at LIMIT 20 FOR UPDATE
   SKIP LOCKED`. Rows another worker is claiming are skipped, not waited on; the partial
   index `ix_scans_queue (queued_at) WHERE status = 'queued'` keeps this cheap however many
   finished scans the table holds.
2. For each candidate in order: a scan with `cancel_requested` becomes `cancelled`; a scan
   on a connection is checked against the connection's limit (below); the first one that
   may run is set `running`, `attempt + 1`, `worker = <host>:<pid>#<slot>`, `started_at`,
   `lease_until = now + LEASE_S`, and committed.
3. No candidate: commit (releasing the locks) and return nothing.

## Per-connection limits

`connections.max_concurrent_scans` (default 2, 1 to 20) caps how many scans run at once
against one database, to protect production servers. During the claim the worker locks the
connection row (`SELECT ... FOR UPDATE`) and counts that connection's `running` scans; at the
limit, the scan is skipped and the next candidate tried. Because the connection row is
locked while counting, two workers cannot both take the last slot. File, REST and push
datasets have no connection and no limit (they run in the worker's own DuckDB).

## Lease and heartbeat

While a scan runs, the executor's heartbeat renews the lease every `LEASE_S / 3` seconds
(20 s with the default 60 s lease):

```sql
UPDATE scans SET lease_until = now() + <lease>
WHERE id = :id AND attempt = :attempt AND worker = :worker AND status = 'running'
RETURNING cancel_requested
```

No row back means the scan is no longer this worker's (the reaper re-queued it while this
worker was stalled): the heartbeat sets the stop flag and the engine stops at the next query.
`cancel_requested` set means a person cancelled it: the same stop flag, and the scan ends
`cancelled`. A failed renewal (Postgres briefly unreachable) is logged and retried at the
next beat.

## Ownership on every write

Every write a worker makes about a scan is conditional on `(id, attempt, worker, status =
'running')` (`queue.owned`). `complete.complete` starts by selecting the scan with that
condition `FOR UPDATE`; if it is gone, the transaction is rolled back and nothing is written.
So a worker that lost its lease, then woke up and finished, can never overwrite the result of
the retry that now owns the scan. The whole outcome (results, profile, history, anomalies,
rollup, dataset state, incidents, notifications) is one transaction: a scan is either fully
recorded or not at all.

## Reaper and crash recovery

The worker's `reap` task, every tick:

```sql
SELECT ... FROM scans WHERE status = 'running' AND lease_until < now() FOR UPDATE SKIP LOCKED
```

- with attempts left (`attempt < MAX_ATTEMPTS`, default 3): back to `queued` with a fresh
  `queued_at`, `worker` and `lease_until` cleared;
- out of attempts: failed with "The worker running this scan stopped responding 3 times",
  which also opens a `scan_failed` incident if a rule asks for one.

A worker killed mid-scan (OOM, node lost, `docker kill`) therefore loses nothing: within
`LEASE_S` plus one task interval its scan is queued again, and the retry runs from the start
and completes once. The source sees the interrupted work a second time; checks are read-only,
so that costs time, not correctness. A graceful stop (SIGTERM) stops claiming and lets
running scans finish.

## Cancel

`POST .../scans/{id}/cancel`: a queued scan is set `cancelled` at once (conditional on still
being `queued`); a running scan gets `cancel_requested = true`, which its heartbeat sees
within a third of the lease and turns into a stop between queries.

## Scheduling exactly once

Datasets have a five-field cron expression, an IANA time zone and `next_run_at` (UTC). The
worker's `schedule` task, every tick:

1. `SELECT ... FROM datasets WHERE schedule_enabled AND next_run_at <= now() ORDER BY
   next_run_at LIMIT 50 FOR UPDATE SKIP LOCKED` (partial index `ix_datasets_due`);
2. for each, `enqueue(trigger = 'schedule', scheduled_for = next_run_at)`;
3. sets `next_run_at` to the cron's next fire time **after now** in the dataset's time zone;
4. commits once.

Exactly once holds on two levels: replicas never claim the same dataset row (`SKIP LOCKED`),
and even if two did, the unique `(dataset_id, scheduled_for)` makes the second insert a
no-op. Because the next run is computed after *now*, a worker that was down for days queues
one catch-up scan, not one per missed slot. Time zones follow the IANA database, so a
`0 6 * * *` schedule in `Asia/Kolkata` runs at 06:00 there all year.

## Worker loop

Each worker runs `WORKER_CONCURRENCY` scanner loops (default 4) and one periodic loop:

- a scanner claims and runs scans back to back; when the queue has nothing for it, it waits
  up to `WORKER_POLL_INTERVAL_S` (default 2 s) or until the periodic loop wakes it;
- the periodic loop runs `schedule`, `reap`, `notify`, `retention` and `queue_depth` every
  `TASK_INTERVAL_S` (default 15 s), and again after 0.5 s when any task did work, waking the
  scanners because the scheduler may have queued scans.

Each scan's blocking source work runs in a thread; the lease heartbeat and Postgres writes
stay on the event loop. After every scan the worker increments the project's dashboard
version counter so the dashboard is recomputed.

## Observing the queue

- `GET /api/v1/system` (admins): queued, running, age of the oldest queued scan.
- `dataquality_queue_depth{status="queued"|"running"}` on the worker's `/metrics`.
- `dataquality_scans_total{status, trigger}` and `dataquality_scan_seconds{source}`.
- On AWS, the `observability` module alarms on re-queued scans (a `reaped scans` log line)
  and on bursts of failed scans.

The tests in `tests/integration/test_queue.py` race several schedulers on one slot, kill a
worker mid-scan and check the retry completes once, exhaust attempts, cancel, reuse an
idempotency key and hold a connection at its limit.
