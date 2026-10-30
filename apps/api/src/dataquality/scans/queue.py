"""The scan queue, in PostgreSQL.

* ``enqueue`` inserts a ``queued`` row in the caller's transaction: creating a scan and
  queueing it are one commit, so nothing is lost between a database and a broker.
* ``claim`` takes the oldest queued scan with ``FOR UPDATE SKIP LOCKED`` (workers never
  wait on each other), skipping scans whose connection already runs its maximum number of
  scans. The connection row is locked while counting, so two workers cannot both take the
  last slot.
* A running scan holds a lease that its worker renews; ``reap`` re-queues scans whose
  lease expired (the worker died) until ``max_attempts``, then fails them.
* Every write a worker makes is conditional on ``(id, attempt, worker)``, so a worker that
  lost its lease can never overwrite the retry's result.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from dataquality.connections.models import Connection
from dataquality.datasets.models import Dataset
from dataquality.scans.models import Scan


async def enqueue(
    session: AsyncSession,
    dataset: Dataset,
    *,
    trigger: str,
    requested_by: uuid.UUID | None = None,
    requested_by_key: uuid.UUID | None = None,
    file_id: uuid.UUID | None = None,
    idempotency_key: str | None = None,
    scheduled_for: datetime | None = None,
    profile: bool | None = None,
) -> tuple[Scan, bool]:
    """Queue a scan (not committed). Returns it and whether it is new: the same idempotency
    key, or the same schedule slot, returns the scan that already exists."""
    values = {
        "id": uuid.uuid4(),
        "project_id": dataset.project_id,
        "dataset_id": dataset.id,
        "connection_id": dataset.connection_id,
        "status": "queued",
        "trigger": trigger,
        "requested_by": requested_by,
        "requested_by_key": requested_by_key,
        "file_id": file_id,
        "idempotency_key": idempotency_key,
        "scheduled_for": scheduled_for,
        "profile": dataset.profile_enabled if profile is None else profile,
    }
    row_id = await session.scalar(
        insert(Scan).values(**values).on_conflict_do_nothing().returning(Scan.id)
    )
    if row_id is not None:
        scan = await session.get(Scan, row_id)
        assert scan is not None
        return scan, True
    existing = await session.scalar(
        select(Scan).where(
            Scan.dataset_id == dataset.id,
            (Scan.idempotency_key == idempotency_key)
            if idempotency_key
            else (Scan.scheduled_for == scheduled_for),
        )
    )
    assert existing is not None
    return existing, False


async def claim(
    session: AsyncSession, worker: str, lease_s: float, *, candidates: int = 20
) -> Scan | None:
    """The next scan this worker may run, leased to it and committed; None when idle."""
    rows = (
        await session.scalars(
            select(Scan)
            .where(Scan.status == "queued")
            .order_by(Scan.queued_at)
            .limit(candidates)
            .with_for_update(skip_locked=True)
        )
    ).all()
    now = datetime.now(UTC)
    for scan in rows:
        if scan.cancel_requested:
            scan.status, scan.finished_at, scan.error = (
                "cancelled",
                now,
                "Cancelled before it started",
            )
            continue
        if scan.connection_id is not None:
            conn = await session.scalar(
                select(Connection).where(Connection.id == scan.connection_id).with_for_update()
            )
            if conn is not None:
                running = await session.scalar(
                    select(func.count())
                    .select_from(Scan)
                    .where(Scan.connection_id == conn.id, Scan.status == "running")
                )
                if (running or 0) >= conn.max_concurrent_scans:
                    continue
        scan.status = "running"
        scan.attempt += 1
        scan.worker = worker
        scan.started_at = now
        scan.lease_until = now + timedelta(seconds=lease_s)
        await session.commit()
        return scan
    await session.commit()
    return None


async def renew(
    session: AsyncSession, scan_id: uuid.UUID, attempt: int, worker: str, lease_s: float
) -> tuple[bool, bool]:
    """Extend the lease. Returns (still ours, cancel requested)."""
    row = (
        await session.execute(
            update(Scan)
            .where(
                Scan.id == scan_id,
                Scan.attempt == attempt,
                Scan.worker == worker,
                Scan.status == "running",
            )
            .values(lease_until=datetime.now(UTC) + timedelta(seconds=lease_s))
            .returning(Scan.cancel_requested)
        )
    ).first()
    await session.commit()
    return (row is not None, bool(row[0]) if row else False)


def owned(scan_id: uuid.UUID, attempt: int, worker: str):  # type: ignore[no-untyped-def]
    return and_(
        Scan.id == scan_id, Scan.attempt == attempt, Scan.worker == worker, Scan.status == "running"
    )


async def reap(session: AsyncSession, max_attempts: int) -> tuple[int, list[uuid.UUID]]:
    """Re-queue scans whose worker stopped renewing the lease. Returns how many were
    re-queued and the ids of those out of attempts, which the caller fails (and alerts)."""
    now = datetime.now(UTC)
    rows = (
        await session.scalars(
            select(Scan)
            .where(Scan.status == "running", Scan.lease_until < now)
            .with_for_update(skip_locked=True)
        )
    ).all()
    requeued, exhausted = 0, []
    for scan in rows:
        if scan.attempt >= max_attempts:
            exhausted.append(scan.id)
            continue
        scan.status = "queued"
        scan.queued_at = now
        scan.worker = None
        scan.lease_until = None
        requeued += 1
    await session.commit()
    return requeued, exhausted
