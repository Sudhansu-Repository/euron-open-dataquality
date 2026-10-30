"""Periodic work the worker runs on every tick (see core/tasks.py). Each task is safe with
several worker replicas: rows are claimed with ``FOR UPDATE SKIP LOCKED``."""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, or_, select, update

from dataquality.alerts.delivery import deliver_due
from dataquality.core.container import Container
from dataquality.core.tasks import periodic
from dataquality.datasets.models import Dataset, DatasetFile
from dataquality.datasets.service import next_run
from dataquality.observability.metrics import QUEUE_DEPTH
from dataquality.projects.models import Project
from dataquality.scans import complete, queue
from dataquality.scans.models import MetricPoint, Scan

log = logging.getLogger("dataquality.tasks")
QUEUE_LOG_EVERY_S = 60.0
_last_queue_log = -QUEUE_LOG_EVERY_S


@periodic("schedule")
async def schedule_due(container: Container) -> int:
    """Queue a scan for every dataset whose schedule is due. The schedule slot is part of
    the scan's unique key, so replicas racing on one dataset still create one scan. A
    worker that was down for days queues one catch-up scan, not one per missed slot."""
    now = datetime.now(UTC)
    async with container.db.sessionmaker() as session:
        rows = (
            await session.scalars(
                select(Dataset)
                .where(Dataset.schedule_enabled.is_(True), Dataset.next_run_at <= now)
                .order_by(Dataset.next_run_at)
                .limit(50)
                .with_for_update(skip_locked=True)
            )
        ).all()
        for d in rows:
            slot = d.next_run_at
            await queue.enqueue(session, d, trigger="schedule", scheduled_for=slot)
            d.next_run_at = (
                next_run(d.schedule_cron, d.schedule_tz, after=now) if d.schedule_cron else None
            )
        await session.commit()
    return len(rows)


@periodic("reap")
async def reap_lost(container: Container) -> int:
    async with container.db.sessionmaker() as session:
        requeued, exhausted = await queue.reap(session, container.settings.max_attempts)
    for scan_id in exhausted:
        async with container.db.sessionmaker() as session:
            await complete.fail(
                session,
                scan_id,
                f"The worker running this scan stopped responding "
                f"{container.settings.max_attempts} times",
            )
    if requeued or exhausted:
        log.warning("reaped scans", extra={"requeued": requeued, "failed": len(exhausted)})
    return requeued + len(exhausted)


@periodic("notify")
async def notify(container: Container) -> int:
    async with container.db.sessionmaker() as session:
        return await deliver_due(container, session)


@periodic("retention")
async def purge(container: Container) -> int:
    """Delete scan results past each project's retention. History metrics, daily rollups
    and anomalies stay (their scan reference becomes null), so trends outlive results.
    Pushed batches past retention go too (rows and stored objects), except the batch a
    dataset currently points at; uploaded file versions are kept, they are the data."""
    now = datetime.now(UTC)
    total = 0
    keys: list[str] = []
    async with container.db.sessionmaker() as session:
        for pid, days in (await session.execute(select(Project.id, Project.retention_days))).all():
            cutoff = now - timedelta(days=int(days))
            ids = (
                await session.scalars(
                    select(Scan.id)
                    .where(
                        Scan.project_id == pid,
                        Scan.created_at < cutoff,
                        Scan.status.in_(("succeeded", "failed", "cancelled")),
                        # A dataset's latest scan is kept, however old: its page shows it.
                        Scan.id.not_in(
                            select(Dataset.last_scan_id).where(Dataset.last_scan_id.is_not(None))
                        ),
                    )
                    .limit(500)
                )
            ).all()
            if ids:
                await session.execute(
                    update(MetricPoint).where(MetricPoint.scan_id.in_(ids)).values(scan_id=None)
                )
                await session.execute(delete(Scan).where(Scan.id.in_(ids)))
                total += len(ids)
            old_batches = (
                await session.execute(
                    select(DatasetFile.id, DatasetFile.storage_key)
                    .join(Dataset, Dataset.id == DatasetFile.dataset_id)
                    .where(
                        Dataset.project_id == pid,
                        Dataset.kind == "push",
                        DatasetFile.created_at < cutoff,
                        or_(
                            Dataset.current_file_id.is_(None),
                            Dataset.current_file_id != DatasetFile.id,
                        ),
                    )
                    .limit(500)
                )
            ).all()
            if old_batches:
                await session.execute(
                    delete(DatasetFile).where(DatasetFile.id.in_([b[0] for b in old_batches]))
                )
                keys.extend(b[1] for b in old_batches)
                total += len(old_batches)
        await session.commit()
    for key in keys:  # after the commit: a row never points at a deleted object
        try:
            await container.storage.delete(key)
        except Exception:  # an orphaned object is harmless; it is logged and left
            log.warning("could not delete a purged object", extra={"key": key})
    return total


@periodic("queue_depth")
async def queue_depth(container: Container) -> int:
    async with container.db.sessionmaker() as session:
        counts = dict(
            (
                await session.execute(
                    select(Scan.status, func.count())
                    .where(Scan.status.in_(("queued", "running")))
                    .group_by(Scan.status)
                )
            ).all()
        )
    for status in ("queued", "running"):
        QUEUE_DEPTH.labels(status).set(int(counts.get(status, 0)))
    global _last_queue_log
    now = time.monotonic()
    if now - _last_queue_log >= QUEUE_LOG_EVERY_S:
        # One line a minute: CloudWatch turns `queued` into the backlog alarm's metric.
        _last_queue_log = now
        log.info(
            "scan queue",
            extra={
                "queued": int(counts.get("queued", 0)),
                "running": int(counts.get("running", 0)),
            },
        )
    return 0
