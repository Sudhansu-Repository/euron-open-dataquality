"""AC8: scheduled scans run once however many workers race; a dead worker's scan is retried
and completed exactly once; cancel works; per-connection limits hold."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from dataquality.core.container import Container
from dataquality.scans import queue
from dataquality.scans.models import Scan
from dataquality.scans.tasks import reap_lost, schedule_due
from tests.integration.conftest import Sources, Stack

pytestmark = pytest.mark.asyncio


@pytest.fixture
def run_worker() -> bool:
    return False


async def sql(stack: Stack, statement: str, **params: Any) -> list[Any]:
    engine = create_async_engine(stack.settings.database_url)
    async with engine.begin() as conn:
        result = await conn.execute(text(statement), params)
        rows = list(result.all()) if result.returns_rows else []
    await engine.dispose()
    return rows


async def _dataset(stack: Stack, golden_sources: Sources) -> tuple[dict[str, Any], dict[str, Any]]:
    p = await stack.project()
    conn = await stack.connection(p["id"], golden_sources.postgres)
    d = await stack.table_dataset(p["id"], conn["id"], "customers")
    return p, d


async def test_racing_schedulers_create_one_scan_per_slot(
    stack: Stack, golden_sources: Sources
) -> None:
    p, d = await _dataset(stack, golden_sources)
    updated = await stack.ok(
        "PATCH",
        f"/api/v1/projects/{p['id']}/datasets/{d['id']}",
        {"schedule_cron": "*/5 * * * *", "schedule_tz": "Asia/Kolkata", "schedule_enabled": True},
    )
    assert updated["next_run_at"] is not None
    slot = datetime.now(UTC) - timedelta(minutes=1)
    await sql(stack, "UPDATE datasets SET next_run_at = :t WHERE id = :i", t=slot, i=d["id"])
    containers = [Container.build(stack.settings) for _ in range(4)]
    try:
        await asyncio.gather(*(schedule_due(c) for c in containers))
        await asyncio.gather(*(schedule_due(c) for c in containers))
    finally:
        for c in containers:
            await c.close()
    rows = await sql(
        stack, "SELECT trigger, scheduled_for FROM scans WHERE dataset_id = :i", i=d["id"]
    )
    assert len(rows) == 1 and rows[0][0] == "schedule"
    nxt = (await sql(stack, "SELECT next_run_at FROM datasets WHERE id = :i", i=d["id"]))[0][0]
    assert nxt > datetime.now(UTC) and nxt.minute % 5 == 0


async def test_a_dead_workers_scan_is_retried_and_finishes_once(
    stack: Stack, golden_sources: Sources
) -> None:
    from dataquality.scans import executor

    p, d = await _dataset(stack, golden_sources)
    await stack.add_checks(p["id"], d["id"], [{"type": "not_null", "column": "email"}])
    resp = await stack.client.post(f"/api/v1/projects/{p['id']}/datasets/{d['id']}/scans")
    scan_id = resp.json()["id"]
    container = Container.build(stack.settings)
    try:
        # Worker A claims the scan, then dies without a word: its lease runs out.
        async with container.db.sessionmaker() as s:
            claimed = await queue.claim(s, "worker-a", stack.settings.lease_s)
        assert claimed is not None and str(claimed.id) == scan_id
        await sql(
            stack,
            "UPDATE scans SET lease_until = now() - interval '1 second' WHERE id = :i",
            i=scan_id,
        )
        assert await reap_lost(container) == 1
        # Worker B takes it over and completes it.
        async with container.db.sessionmaker() as s:
            again = await queue.claim(s, "worker-b", stack.settings.lease_s)
        assert again is not None and again.attempt == 2
        assert await executor.execute(container, again, "worker-b") == "succeeded"
        # Worker A wakes up and tries to report: refused, it no longer owns the scan.
        async with container.db.sessionmaker() as s:
            ours, _ = await queue.renew(s, again.id, 1, "worker-a", 30)
        assert ours is False
    finally:
        await container.close()
    results = await sql(stack, "SELECT count(*) FROM check_results WHERE scan_id = :i", i=scan_id)
    assert results[0][0] == 1
    scan = await stack.ok("GET", f"/api/v1/projects/{p['id']}/scans/{scan_id}")
    assert scan["status"] == "succeeded" and scan["attempt"] == 2


async def test_a_scan_out_of_attempts_fails_and_says_why(
    stack: Stack, golden_sources: Sources
) -> None:
    p, d = await _dataset(stack, golden_sources)
    resp = await stack.client.post(f"/api/v1/projects/{p['id']}/datasets/{d['id']}/scans")
    scan_id = resp.json()["id"]
    await sql(
        stack,
        "UPDATE scans SET status = 'running', attempt = :a, worker = 'gone', lease_until = now() - interval '1 second' WHERE id = :i",
        a=stack.settings.max_attempts,
        i=scan_id,
    )
    container = Container.build(stack.settings)
    try:
        await reap_lost(container)
    finally:
        await container.close()
    scan = await stack.ok("GET", f"/api/v1/projects/{p['id']}/scans/{scan_id}")
    assert scan["status"] == "failed" and "stopped responding" in scan["error"]


async def test_cancel_a_queued_scan(stack: Stack, golden_sources: Sources) -> None:
    p, d = await _dataset(stack, golden_sources)
    scan = (await stack.client.post(f"/api/v1/projects/{p['id']}/datasets/{d['id']}/scans")).json()
    out = await stack.ok("POST", f"/api/v1/projects/{p['id']}/scans/{scan['id']}/cancel")
    assert out["status"] == "cancelled"
    resp = await stack.client.post(f"/api/v1/projects/{p['id']}/scans/{scan['id']}/cancel")
    assert resp.status_code == 409


async def test_idempotency_key_returns_the_same_scan(stack: Stack, golden_sources: Sources) -> None:
    p, d = await _dataset(stack, golden_sources)
    path = f"/api/v1/projects/{p['id']}/datasets/{d['id']}/scans"
    a = (await stack.client.post(path, json={"idempotency_key": "ci-run-42"})).json()
    b = (await stack.client.post(path, json={"idempotency_key": "ci-run-42"})).json()
    assert a["id"] == b["id"]


async def test_connection_limit_caps_concurrent_scans(
    stack: Stack, golden_sources: Sources
) -> None:
    p, d = await _dataset(stack, golden_sources)
    await stack.ok(
        "PATCH",
        f"/api/v1/projects/{p['id']}/connections/{d['connection_id']}",
        {"max_concurrent_scans": 1},
    )
    for _ in range(3):
        await stack.client.post(f"/api/v1/projects/{p['id']}/datasets/{d['id']}/scans")
    container = Container.build(stack.settings)
    try:

        async def claim(name: str) -> Scan | None:
            async with container.db.sessionmaker() as s:
                return await queue.claim(s, name, 60)

        got = await asyncio.gather(*(claim(f"w{i}") for i in range(3)))
    finally:
        await container.close()
    assert sum(1 for g in got if g is not None) == 1
