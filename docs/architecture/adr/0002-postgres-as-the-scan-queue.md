# ADR-0002: PostgreSQL as the scan queue, not Celery

- **Status:** Accepted
- **Date:** 2026-10-30

## Context

The brief suggested Celery for background scans. Scans must not be lost between the
request and the worker, must run exactly once per schedule slot with several worker
replicas, must survive a worker dying mid-scan, and must respect a per-connection limit so
a production database is not hit by ten scans at once. The scan row (status, timings,
results) has to live in Postgres anyway.

## Decision

The `scans` table is the queue. `enqueue` inserts a `queued` row in the caller's
transaction; workers claim with `SELECT ... FOR UPDATE SKIP LOCKED` on a partial index, hold
a lease they renew every third of its length, and write only while `(id, attempt, worker)`
still matches. A reaper re-queues expired leases up to `MAX_ATTEMPTS`. Schedules are claimed
the same way, with a unique `(dataset_id, scheduled_for)` so a slot yields one scan.
Per-connection limits are checked under a lock on the connection row during the claim.
Details in [queue.md](../queue.md).

## Consequences

**Good**
- Creating and queueing a scan is one commit: nothing is lost between a database and a
  broker, and nothing is queued for a scan that rolled back.
- Exactly-once scheduling and idempotent requests are database constraints, not
  coordination code.
- No broker to run, secure and monitor; Redis stays optional
  ([ADR-0010](0010-redis-is-optional.md)).
- The queue is queryable: depth, age of the oldest scan, which worker holds what.

**Bad / caveats**
- Idle workers poll (every `WORKER_POLL_INTERVAL_S`, 2 s by default, plus a wake-up after
  the scheduler runs). At the scale of data quality scans (seconds to minutes each) the
  polling load is negligible; at thousands of jobs per second it would not be.
- Each worker holds Postgres connections for claims, heartbeats and results; size the pool
  (`DB_POOL_SIZE`) and RDS accordingly.

## Alternatives considered

- **Celery with Redis or RabbitMQ**: a second system whose state can disagree with the scan
  rows (a task acknowledged but its row never written, or the reverse); per-connection
  concurrency and exactly-once schedules (Celery beat runs once, not per replica) would still
  need database locks.
- **SQS**: fine on AWS, but local development would need the emulator in the hot path and
  the same dual-write problem remains.
- **A Redis Stream**: what CodeJudge uses, where jobs are fire-and-forget; here every scan is
  already a row with history, so a second store adds nothing.
