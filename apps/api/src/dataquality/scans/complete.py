"""Write a scan's outcome: results, profile, history, anomalies, rollups, the dataset's
latest state and the alerts, all in one transaction that commits only if the worker still
owns the scan (the same attempt, the same worker)."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from dataquality.alerts.engine import evaluate
from dataquality.checks.models import Check
from dataquality.datasets.models import Dataset
from dataquality.engine.profiler import DatasetProfile
from dataquality.engine.relation import ColumnInfo
from dataquality.engine.runner import Outcome
from dataquality.engine.scoring import ScoredResult, score
from dataquality.engine.spec import CheckType, Dimension
from dataquality.observability.metrics import (
    ANOMALIES,
    CHECK_RESULTS,
    DEPENDENCY_ERRORS,
    ROWS_SCANNED,
    SCANS,
)
from dataquality.projects.models import Project
from dataquality.scans import history
from dataquality.scans.models import CheckResult, DailyScore, Scan, ScanProfile
from dataquality.scans.queue import owned

log = logging.getLogger("dataquality.scans")


@dataclass
class RunOutput:
    row_count: int
    outcomes: list[Outcome]
    columns: list[ColumnInfo]
    profile: DatasetProfile | None = None
    file_id: uuid.UUID | None = None
    extra: dict[str, Any] = field(default_factory=dict)


async def _owned(
    session: AsyncSession, scan_id: uuid.UUID, attempt: int, worker: str
) -> Scan | None:
    return await session.scalar(
        select(Scan).where(owned(scan_id, attempt, worker)).with_for_update()
    )


async def complete(
    session: AsyncSession,
    scan_id: uuid.UUID,
    attempt: int,
    worker: str,
    out: RunOutput,
    checks: Sequence[Check],
) -> Scan | None:
    scan = await _owned(session, scan_id, attempt, worker)
    if scan is None:
        await session.rollback()
        return None  # the lease was lost and the scan belongs to a retry now
    dataset = await session.get(Dataset, scan.dataset_id)
    project = await session.get(Project, scan.project_id)
    assert dataset is not None and project is not None
    now = datetime.now(UTC)
    by_id = {str(c.id): c for c in checks}
    results: list[CheckResult] = []
    scored: list[ScoredResult] = []
    for o in out.outcomes:
        c = by_id[o.key]
        dim = Dimension(c.dimension)
        r = CheckResult(
            scan_id=scan.id,
            check_id=c.id,
            check_name=c.name,
            type=c.type,
            column=c.column,
            params=c.params,
            severity=c.severity,
            dimension=dim.value,
            status=o.status,
            evaluated=o.evaluated,
            failed=o.failed,
            failed_pct=round(o.failed_pct, 4),
            observed=o.observed,
            sample=o.sample if project.sample_size else [],
            message=o.message[:2000],
            error=o.error,
            ms=o.ms,
        )
        if project.sample_size and len(r.sample) > project.sample_size:
            r.sample = r.sample[: project.sample_size]
        results.append(r)
        scored.append(ScoredResult(CheckType(c.type), dim, o.status, o.evaluated, o.failed))
        CHECK_RESULTS.labels(c.type, o.status).inc()
    session.add_all(results)
    s = score(scored)
    scan.status = "succeeded"
    scan.finished_at = now
    scan.duration_ms = int((now - (scan.started_at or now)).total_seconds() * 1000)
    scan.row_count = out.row_count
    scan.score = s.overall
    scan.dimension_scores = s.dimensions
    scan.file_id = out.file_id or scan.file_id
    scan.columns = [{"name": c.name, "type": c.logical, "native": c.native} for c in out.columns]
    scan.checks_total = len(results)
    scan.checks_passed = sum(1 for r in results if r.status == "pass")
    scan.checks_failed = sum(1 for r in results if r.status == "fail" and r.severity == "error")
    scan.checks_warned = sum(1 for r in results if r.status == "fail" and r.severity == "warn")
    scan.checks_errored = sum(1 for r in results if r.status == "error")
    scan.failed_rows = sum(
        r.failed
        for r in results
        if r.status == "fail" and r.type not in ("schema", "freshness", "row_count")
    )
    scan.duplicate_rows = sum(r.failed for r in results if r.type in ("unique", "duplicate_rows"))
    scan.lease_until = None
    if out.profile is not None:
        p = out.profile
        session.add(
            ScanProfile(
                scan_id=scan.id,
                dataset_id=dataset.id,
                row_count=p.row_count,
                rows_profiled=p.rows_profiled,
                sampled=p.sampled,
                ms=p.ms,
                columns=[c.as_dict() for c in p.columns],
            )
        )
    await session.flush()
    at = scan.started_at or now
    points = history.metrics_for(
        scan,
        s.overall,
        s.dimensions,
        [(r.check_id, r.failed_pct) for r in results if r.status != "error"],
        out.profile,
    )
    anomalies = await history.record(
        session, scan, at, points, project.anomaly_sensitivity, {str(c.id): c.name for c in checks}
    )
    changes = await history.drift(session, scan)
    drift = history.drift_anomalies(scan, changes)
    session.add_all(drift)
    for a in [*anomalies, *drift]:
        ANOMALIES.labels(a.kind).inc()
    await _rollup(session, scan, dataset)
    dataset.last_scan_id = scan.id
    dataset.last_scan_at = now
    dataset.last_status = "succeeded"
    dataset.last_score = s.overall
    dataset.last_row_count = out.row_count
    dataset.last_failed_checks = scan.checks_failed + scan.checks_warned
    await session.flush()
    await _alerts(session, dataset, scan, results, [*anomalies, *drift])
    await session.commit()
    SCANS.labels("succeeded", scan.trigger).inc()
    ROWS_SCANNED.labels(dataset.kind).inc(out.row_count)
    return scan


async def _alerts(
    session: AsyncSession,
    dataset: Dataset,
    scan: Scan,
    results: Sequence[CheckResult],
    anomalies: Sequence[Any],
) -> None:
    """Incidents and notifications in a savepoint of the scan's transaction: they commit
    with the results, but a failure in alerting never costs the results themselves."""
    try:
        async with session.begin_nested():
            await evaluate(session, dataset, scan, results, anomalies)
    except SQLAlchemyError:
        log.exception("alert evaluation failed", extra={"scan": str(scan.id)})
        DEPENDENCY_ERRORS.labels("postgres", "alerts").inc()


async def _rollup(session: AsyncSession, scan: Scan, dataset: Dataset) -> None:
    day = (scan.started_at or datetime.now(UTC)).date()
    failed = scan.checks_failed + scan.checks_warned
    stmt = insert(DailyScore).values(
        dataset_id=dataset.id,
        day=day,
        project_id=dataset.project_id,
        scans=1,
        score_sum=scan.score or 0.0,
        last_score=scan.score,
        failed_checks=failed,
        rows_scanned=scan.row_count or 0,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["dataset_id", "day"],
        set_={
            "scans": DailyScore.scans + 1,
            "score_sum": DailyScore.score_sum + (scan.score or 0.0),
            "last_score": scan.score,
            "failed_checks": failed,
            "rows_scanned": scan.row_count or 0,
        },
    )
    if scan.score is not None:
        await session.execute(stmt)


async def fail(
    session: AsyncSession,
    scan_id: uuid.UUID,
    error: str,
    *,
    attempt: int | None = None,
    worker: str | None = None,
    status: str = "failed",
) -> Scan | None:
    """Finish a scan as failed or cancelled (and alert on failure)."""
    if attempt is not None and worker is not None:
        scan = await _owned(session, scan_id, attempt, worker)
    else:
        scan = await session.scalar(select(Scan).where(Scan.id == scan_id).with_for_update())
    if scan is None:
        await session.rollback()
        return None
    now = datetime.now(UTC)
    scan.status = status
    scan.error = error[:2000]
    scan.finished_at = now
    scan.lease_until = None
    if scan.started_at:
        scan.duration_ms = int((now - scan.started_at).total_seconds() * 1000)
    dataset = await session.get(Dataset, scan.dataset_id)
    if dataset is not None and status == "failed":
        dataset.last_status = "failed"
        dataset.last_scan_at = now
        await session.flush()
        await _alerts(session, dataset, scan, [], [])
    await session.commit()
    SCANS.labels(status, scan.trigger).inc()
    return scan
