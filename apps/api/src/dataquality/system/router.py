"""Health, readiness, metrics and deployment info."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable
from typing import Any

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import func, select, text

from dataquality import __version__
from dataquality.auth.dependencies import Admin
from dataquality.core.deps import ContainerDep, SessionDep
from dataquality.core.schemas import ApiModel
from dataquality.datasets.models import Dataset
from dataquality.projects.models import Project
from dataquality.scans.models import Scan
from dataquality.users.models import User

router = APIRouter(tags=["system"])


@router.get("/healthz", summary="Liveness")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health", summary="Liveness (alias of /healthz)")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


async def _probe(name: str, coro: Awaitable[Any]) -> tuple[str, dict[str, Any]]:
    t0 = time.perf_counter()
    try:
        await asyncio.wait_for(coro, timeout=2)
        return name, {"ok": True, "ms": round((time.perf_counter() - t0) * 1000, 1)}
    except Exception as exc:
        return name, {"ok": False, "error": type(exc).__name__}


@router.get("/readyz", summary="Readiness: Postgres reachable (Redis reported too)")
async def readyz(container: ContainerDep, response: Response) -> dict[str, Any]:
    async def pg() -> None:
        async with container.db.engine.connect() as conn:
            await conn.execute(text("select 1"))

    probes = [_probe("postgres", pg())]
    if container.kv.backend == "redis":
        probes.append(_probe("redis", container.kv.ping()))
    checks = dict(await asyncio.gather(*probes))
    # Redis only holds rate limits and caches, which fall back to process memory, so
    # Postgres alone decides readiness and Redis reports as degraded.
    ok = checks["postgres"]["ok"]
    response.status_code = 200 if ok else 503
    degraded = not all(c["ok"] for c in checks.values())
    return {"status": "degraded" if degraded else "ready", "checks": checks}


@router.get("/metrics", summary="Prometheus metrics", include_in_schema=False)
async def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


class QueueInfo(ApiModel):
    queued: int
    running: int
    oldest_queued_s: float | None


class SystemInfo(ApiModel):
    version: str
    environment: str
    storage: str
    key_mode: str
    cache: str
    mail: str
    redis: bool
    queue: QueueInfo
    projects: int
    datasets: int
    users: int
    scans: int


@router.get("/api/v1/system", response_model=SystemInfo, tags=["system"])
async def system(_: Admin, session: SessionDep, container: ContainerDep) -> SystemInfo:
    from datetime import UTC, datetime

    s = container.settings
    try:
        await container.kv.ping()
        redis_ok = container.kv.backend == "redis"
    except Exception:
        redis_ok = False
    counts = dict(
        (
            await session.execute(
                select(Scan.status, func.count())
                .where(Scan.status.in_(("queued", "running")))
                .group_by(Scan.status)
            )
        ).all()
    )
    oldest = await session.scalar(select(func.min(Scan.queued_at)).where(Scan.status == "queued"))

    async def count(model: Any) -> int:
        return int(await session.scalar(select(func.count()).select_from(model)) or 0)

    return SystemInfo(
        version=__version__,
        environment=s.environment,
        storage=s.storage,
        key_mode=s.key_mode,
        cache=s.cache_backend,
        mail=s.mail_backend,
        redis=redis_ok,
        queue=QueueInfo(
            queued=int(counts.get("queued", 0)),
            running=int(counts.get("running", 0)),
            oldest_queued_s=(datetime.now(UTC) - oldest).total_seconds() if oldest else None,
        ),
        projects=await count(Project),
        datasets=await count(Dataset),
        users=await count(User),
        scans=await count(Scan),
    )
