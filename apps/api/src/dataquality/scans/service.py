"""Scans from the API's side: request one, list and read them, cancel, wait for a result,
and read what scans produced over time (profiles, suggestions, history, anomalies)."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from dataquality.audit.service import audit
from dataquality.checks.models import Check
from dataquality.core.container import Container
from dataquality.core.errors import ConflictError, NotFoundError, RateLimitedError
from dataquality.datasets.models import Dataset
from dataquality.engine.profiler import ColumnProfile, DatasetProfile
from dataquality.engine.suggest import suggest
from dataquality.projects.access import Principal
from dataquality.scans import queue
from dataquality.scans.models import FINISHED, Anomaly, CheckResult, MetricPoint, Scan, ScanProfile


async def request_scan(
    container: Container,
    session: AsyncSession,
    p: Principal,
    d: Dataset,
    *,
    trigger: str = "manual",
    idempotency_key: str | None = None,
    file_id: uuid.UUID | None = None,
    profile: bool | None = None,
) -> tuple[Scan, bool]:
    if trigger != "push":
        decision = await container.kv.hit(f"scan:{p.project_id}", container.settings.scan_rpm)
        if not decision.allowed:
            raise RateLimitedError(
                "Too many scans requested in this project. Wait a minute and try again",
                headers={"retry-after": str(decision.retry_after_s)},
            )
    if d.kind in ("file", "push") and d.current_file_id is None and file_id is None:
        what = "Push records to it" if d.kind == "push" else "Upload a file"
        raise ConflictError(f"There is nothing to scan yet. {what} first", code="nothing_to_scan")
    scan, new = await queue.enqueue(
        session,
        d,
        trigger=trigger,
        requested_by=p.user_id,
        requested_by_key=p.key.id if p.key else None,
        file_id=file_id,
        idempotency_key=idempotency_key,
        profile=profile,
    )
    if new:
        audit(session, p.actor, "scan.requested", "scan", scan.id, dataset=d.slug, trigger=trigger)
    await session.commit()
    return scan, new


async def get(session: AsyncSession, project_id: uuid.UUID, scan_id: uuid.UUID) -> Scan:
    scan = await session.scalar(
        select(Scan).where(Scan.id == scan_id, Scan.project_id == project_id)
    )
    if scan is None:
        raise NotFoundError("Scan not found")
    return scan


async def list_scans(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    dataset_id: uuid.UUID | None,
    status: str | None,
    before: datetime | None,
    limit: int,
) -> list[Scan]:
    """Newest first, keyset-paginated on created_at; ``limit + 1`` rows to tell whether
    another page exists."""
    stmt = (
        select(Scan)
        .where(Scan.project_id == project_id)
        .order_by(Scan.created_at.desc(), Scan.id.desc())
        .limit(limit + 1)
    )
    if dataset_id:
        stmt = stmt.where(Scan.dataset_id == dataset_id)
    if status:
        stmt = stmt.where(Scan.status == status)
    if before:
        stmt = stmt.where(Scan.created_at < before)
    return list((await session.scalars(stmt)).all())


async def results(session: AsyncSession, scan: Scan) -> Sequence[CheckResult]:
    order = {"fail": 0, "error": 1, "pass": 2}
    rows = (await session.scalars(select(CheckResult).where(CheckResult.scan_id == scan.id))).all()
    return sorted(
        rows,
        key=lambda r: (
            order.get(r.status, 3),
            0 if r.severity == "error" else 1,
            -r.failed,
            r.check_name,
        ),
    )


async def cancel(session: AsyncSession, p: Principal, scan: Scan) -> Scan:
    if scan.status in FINISHED:
        raise ConflictError("The scan has already finished", code="scan_finished")
    if scan.status == "queued":
        await session.execute(
            update(Scan)
            .where(Scan.id == scan.id, Scan.status == "queued")
            .values(
                status="cancelled",
                finished_at=datetime.now(UTC),
                error="Cancelled before it started",
                cancel_requested=True,
            )
        )
    else:
        scan.cancel_requested = True
    audit(session, p.actor, "scan.cancelled", "scan", scan.id)
    await session.commit()
    await session.refresh(scan)
    return scan


async def wait(
    container: Container, project_id: uuid.UUID, scan_id: uuid.UUID, timeout_s: float
) -> Scan:
    """Poll until the scan finishes or the timeout passes; returns its latest state."""
    deadline = asyncio.get_running_loop().time() + timeout_s
    delay = 0.2
    while True:
        async with container.db.sessionmaker() as session:
            scan = await get(session, project_id, scan_id)
        if scan.status in FINISHED or asyncio.get_running_loop().time() >= deadline:
            return scan
        await asyncio.sleep(delay)
        delay = min(delay * 1.5, 2.0)


async def latest_profile(session: AsyncSession, d: Dataset) -> ScanProfile | None:
    return await session.scalar(
        select(ScanProfile)
        .where(ScanProfile.dataset_id == d.id)
        .order_by(ScanProfile.created_at.desc())
        .limit(1)
    )


def _as_profile(row: ScanProfile) -> DatasetProfile:
    fields = set(ColumnProfile.__dataclass_fields__)
    cols = [ColumnProfile(**{k: v for k, v in c.items() if k in fields}) for c in row.columns]
    return DatasetProfile(row.row_count, row.rows_profiled, row.sampled, cols, row.ms)


async def suggestions(session: AsyncSession, d: Dataset) -> list[dict[str, Any]] | None:
    row = await latest_profile(session, d)
    if row is None:
        return None
    existing = {
        (c.type, c.column)
        for c in (await session.scalars(select(Check).where(Check.dataset_id == d.id))).all()
    }
    return [
        {
            "key": s.key,
            "type": s.type.value,
            "column": s.column,
            "params": s.params,
            "severity": s.severity.value,
            "reason": s.reason,
            "exists": (s.type.value, s.column) in existing,
        }
        for s in suggest(_as_profile(row), row.created_at)
    ]


async def series(
    session: AsyncSession, d: Dataset, metric: str, key: str | None, days: int
) -> list[tuple[str, list[dict[str, Any]]]]:
    since = datetime.now(UTC) - timedelta(days=days)
    stmt = (
        select(MetricPoint.key, MetricPoint.value, MetricPoint.at, MetricPoint.scan_id)
        .where(
            MetricPoint.dataset_id == d.id, MetricPoint.metric == metric, MetricPoint.at >= since
        )
        .order_by(MetricPoint.at)
        .limit(20_000)
    )
    if key is not None:
        stmt = stmt.where(MetricPoint.key == key)
    out: dict[str, list[dict[str, Any]]] = {}
    for k, v, at, sid in (await session.execute(stmt)).all():
        out.setdefault(k, []).append(
            {"at": at.isoformat(), "value": v, "scan_id": str(sid) if sid else None}
        )
    return list(out.items())


async def anomalies(
    session: AsyncSession, project_id: uuid.UUID, dataset_id: uuid.UUID | None, limit: int
) -> Sequence[Anomaly]:
    stmt = (
        select(Anomaly)
        .where(Anomaly.project_id == project_id)
        .order_by(Anomaly.created_at.desc())
        .limit(limit)
    )
    if dataset_id:
        stmt = stmt.where(Anomaly.dataset_id == dataset_id)
    return (await session.scalars(stmt)).all()
