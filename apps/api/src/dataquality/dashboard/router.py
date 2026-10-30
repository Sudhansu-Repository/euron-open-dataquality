"""The project dashboard: one request, a handful of indexed queries over denormalised state
(each dataset's latest scan) and the daily rollup, never over raw results history.

Cached for ``CACHE_TTL_S`` per project in the KV store (Redis, or process memory), keyed by
the project's version counter, which the worker bumps after every scan: with Redis (shared
by the API and the worker) a new result shows at once; without it each process has its
own counter and a result shows within the TTL.
"""

from __future__ import annotations

import contextlib
import uuid
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

import orjson
from fastapi import APIRouter
from redis.exceptions import RedisError
from sqlalchemy import func, select

from dataquality.alerts.models import Incident
from dataquality.core.deps import ContainerDep, SessionDep
from dataquality.core.schemas import ApiModel
from dataquality.datasets.models import Dataset
from dataquality.projects.access import Viewer
from dataquality.scans.models import CheckResult, DailyScore, Scan

router = APIRouter(prefix="/api/v1/projects/{project_id}", tags=["dashboard"])
CACHE_TTL_S = 30
DIMENSIONS = ("completeness", "validity", "consistency", "uniqueness", "freshness", "volume")


class Issue(ApiModel):
    dataset_id: uuid.UUID
    dataset_name: str
    scan_id: uuid.UUID
    check_name: str
    type: str
    column: str | None
    severity: str
    failed: int
    message: str


class TrendPoint(ApiModel):
    day: str
    score: float | None
    failed_checks: int
    scans: int


class DatasetScore(ApiModel):
    id: uuid.UUID
    name: str
    kind: str
    score: float | None
    status: str | None
    row_count: int | None
    failed_checks: int | None
    last_scan_at: datetime | None


class Dashboard(ApiModel):
    score: float | None
    score_change: float | None
    datasets: int
    datasets_scanned: int
    records_scanned: int
    failed_checks: int
    duplicate_records: int
    open_incidents: int
    scans_24h: int
    dimensions: dict[str, float | None]
    trend: list[TrendPoint]
    issues: list[Issue]
    worst: list[DatasetScore]
    generated_at: datetime


def version_key(project_id: uuid.UUID) -> str:
    return f"dash:v:{project_id}"


@router.get(
    "/dashboard",
    response_model=Dashboard,
    summary="Score, counts, dimensions, trend and recent issues",
)
async def dashboard(p: Viewer, session: SessionDep, container: ContainerDep) -> Dashboard:
    try:
        version = (await container.kv.get(version_key(p.project_id))) or b"0"
        cached = await container.kv.get(f"dash:{p.project_id}:{version.decode()}")
    except (RedisError, OSError):  # a cache outage only costs a recompute
        version, cached = b"0", None
    if cached:
        return Dashboard.model_validate(orjson.loads(cached))
    out = await compute(session, p.project_id)
    with contextlib.suppress(RedisError, OSError):
        await container.kv.set(
            f"dash:{p.project_id}:{version.decode()}",
            orjson.dumps(out.model_dump(mode="json")),
            CACHE_TTL_S,
        )
    return out


async def compute(session: Any, project_id: uuid.UUID) -> Dashboard:
    now = datetime.now(UTC)
    datasets = (
        await session.scalars(select(Dataset).where(Dataset.project_id == project_id))
    ).all()
    scanned = [d for d in datasets if d.last_score is not None]
    score = round(sum(d.last_score for d in scanned) / len(scanned), 1) if scanned else None
    last_ids = [d.last_scan_id for d in datasets if d.last_scan_id]
    latest = (
        (await session.scalars(select(Scan).where(Scan.id.in_(last_ids)))).all() if last_ids else []
    )
    dims: dict[str, list[float]] = defaultdict(list)
    for s in latest:
        for k, v in (s.dimension_scores or {}).items():
            dims[k].append(float(v))
    dimensions = {
        k: (round(sum(dims[k]) / len(dims[k]), 1) if dims[k] else None) for k in DIMENSIONS
    }
    since = (now - timedelta(days=30)).date()
    trend_rows = (
        await session.execute(
            select(
                DailyScore.day,
                func.sum(DailyScore.score_sum),
                func.sum(DailyScore.scans),
                func.sum(DailyScore.failed_checks),
            )
            .where(DailyScore.project_id == project_id, DailyScore.day >= since)
            .group_by(DailyScore.day)
            .order_by(DailyScore.day)
        )
    ).all()
    trend = [
        TrendPoint(
            day=day.isoformat(),
            score=round(float(total) / int(n), 1) if n else None,
            failed_checks=int(failed or 0),
            scans=int(n or 0),
        )
        for day, total, n, failed in trend_rows
    ]
    change = None
    week_ago = [
        t
        for t in trend
        if t.day <= (now - timedelta(days=7)).date().isoformat() and t.score is not None
    ]
    if score is not None and week_ago:
        change = round(score - (week_ago[-1].score or 0), 1)
    elif score is not None and len(trend) >= 2 and trend[0].score is not None:
        change = round(score - trend[0].score, 1)
    names = {d.id: d.name for d in datasets}
    issues: list[Issue] = []
    if last_ids:
        rows = (
            await session.scalars(
                select(CheckResult)
                .where(CheckResult.scan_id.in_(last_ids), CheckResult.status == "fail")
                .order_by(CheckResult.severity, CheckResult.failed.desc())
                .limit(10)
            )
        ).all()
        by_scan = {s.id: s.dataset_id for s in latest}
        issues = [
            Issue(
                dataset_id=by_scan[r.scan_id],
                dataset_name=names.get(by_scan[r.scan_id], ""),
                scan_id=r.scan_id,
                check_name=r.check_name,
                type=r.type,
                column=r.column,
                severity=r.severity,
                failed=r.failed,
                message=r.message,
            )
            for r in rows
        ]
    open_incidents = int(
        await session.scalar(
            select(func.count())
            .select_from(Incident)
            .where(Incident.project_id == project_id, Incident.status != "resolved")
        )
        or 0
    )
    scans_24h = int(
        await session.scalar(
            select(func.count())
            .select_from(Scan)
            .where(Scan.project_id == project_id, Scan.created_at >= now - timedelta(hours=24))
        )
        or 0
    )
    worst = sorted(
        datasets,
        key=lambda d: (d.last_score is None, d.last_score if d.last_score is not None else 0),
    )[:6]
    return Dashboard(
        score=score,
        score_change=change,
        datasets=len(datasets),
        datasets_scanned=len(scanned),
        records_scanned=sum(d.last_row_count or 0 for d in datasets),
        failed_checks=sum(d.last_failed_checks or 0 for d in datasets),
        duplicate_records=sum(s.duplicate_rows for s in latest),
        open_incidents=open_incidents,
        scans_24h=scans_24h,
        dimensions=dimensions,
        trend=trend,
        issues=issues,
        worst=[
            DatasetScore(
                id=d.id,
                name=d.name,
                kind=d.kind,
                score=d.last_score,
                status=d.last_status,
                row_count=d.last_row_count,
                failed_checks=d.last_failed_checks,
                last_scan_at=d.last_scan_at,
            )
            for d in worst
        ],
        generated_at=now,
    )
