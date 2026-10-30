"""AC12: a failing check opens one incident and notifies each channel once until it is
resolved; it resolves itself when the check passes again. Webhooks are signed."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

import httpx
import polars as pl
import pytest

from dataquality.alerts.delivery import SIGNATURE_HEADER, verify
from dataquality.core.mail import OUTBOX
from tests.integration.conftest import Stack

pytestmark = pytest.mark.asyncio
SECRET = "webhook-signing-secret-for-tests"


async def hooks(stack: Stack) -> list[dict[str, Any]]:
    async with httpx.AsyncClient() as c:
        return list((await c.get(f"{stack.mock_ai_url}/webhook")).json())


async def until(predicate: Any, timeout: float = 20) -> None:
    deadline = time.monotonic() + timeout
    while not await predicate():
        assert time.monotonic() < deadline, "condition not met in time"
        await asyncio.sleep(0.2)


async def upload_version(stack: Stack, p: dict[str, Any], d: dict[str, Any], path: Path) -> None:
    with path.open("rb") as f:
        resp = await stack.client.post(
            f"/api/v1/projects/{p['id']}/datasets/{d['id']}/files", files={"file": (path.name, f)}
        )
    assert resp.status_code == 201, resp.text


async def test_incident_lifecycle_notifies_once_per_channel(stack: Stack, tmp_path: Path) -> None:
    async with httpx.AsyncClient() as c:
        await c.post(f"{stack.mock_ai_url}/admin/reset", json={})
    OUTBOX.clear()
    p = await stack.project()
    bad = tmp_path / "customers.csv"
    pl.DataFrame({"id": [1, 2, 3], "email": ["a@x.com", None, None]}).write_csv(bad)
    d = await stack.upload(p["id"], bad, "customers")
    await stack.add_checks(p["id"], d["id"], [{"type": "not_null", "column": "email"}])
    hook = await stack.ok(
        "POST",
        f"/api/v1/projects/{p['id']}/alert-channels",
        {
            "name": "ops webhook",
            "kind": "webhook",
            "url": f"{stack.mock_ai_url}/webhook",
            "secret": SECRET,
        },
        status=201,
    )
    assert hook["target_hint"] == "127.0.0.1" and "url" not in hook
    mail = await stack.ok(
        "POST",
        f"/api/v1/projects/{p['id']}/alert-channels",
        {"name": "data team", "kind": "email", "recipients": ["data@example.test"]},
        status=201,
    )
    await stack.ok(
        "POST",
        f"/api/v1/projects/{p['id']}/alert-rules",
        {"name": "errors", "kind": "check_failed", "channel_ids": [hook["id"], mail["id"]]},
        status=201,
    )
    await stack.scan(p["id"], d["id"])
    await stack.scan(p["id"], d["id"])  # still failing: same incident, no new message
    incidents = await stack.ok("GET", f"/api/v1/projects/{p['id']}/incidents?status=active")
    assert len(incidents) == 1 and incidents[0]["occurrences"] == 2
    incident_id = incidents[0]["id"]

    async def delivered() -> bool:
        detail = await stack.ok("GET", f"/api/v1/projects/{p['id']}/incidents/{incident_id}")
        return (
            all(n["status"] == "sent" for n in detail["notifications"])
            and len(detail["notifications"]) == 2
        )

    await until(delivered)
    received = await hooks(stack)
    assert len(received) == 1
    body = received[0]["body"].encode()
    assert verify(SECRET, body, received[0]["headers"][SIGNATURE_HEADER])
    assert not verify(
        "another-secret-xxxxxxxxxxxxx", body, received[0]["headers"][SIGNATURE_HEADER]
    )
    assert '"incident.opened"' in received[0]["body"]
    assert [m.to for m in OUTBOX] == ["data@example.test"] and "email" in OUTBOX[0].subject

    # The data is fixed: the next scan resolves the incident and says so once.
    good = tmp_path / "customers_fixed.csv"
    pl.DataFrame({"id": [1, 2, 3], "email": ["a@x.com", "b@x.com", "c@x.com"]}).write_csv(good)
    await upload_version(stack, p, d, good)
    await stack.scan(p["id"], d["id"])
    detail = await stack.ok("GET", f"/api/v1/projects/{p['id']}/incidents/{incident_id}")
    assert detail["status"] == "resolved" and detail["resolution"] == "cleared"

    async def resolved_sent() -> bool:
        return len(await hooks(stack)) == 2

    await until(resolved_sent)
    assert '"incident.resolved"' in (await hooks(stack))[1]["body"]


async def test_score_and_scan_failure_rules(stack: Stack, tmp_path: Path) -> None:
    p = await stack.project()
    path = tmp_path / "t.csv"
    pl.DataFrame({"id": [1, None, None, None]}).write_csv(path)
    d = await stack.upload(p["id"], path, "t")
    await stack.add_checks(
        p["id"], d["id"], [{"type": "not_null", "column": "id", "severity": "warn"}]
    )
    await stack.ok(
        "POST",
        f"/api/v1/projects/{p['id']}/alert-rules",
        {"name": "score", "kind": "score_below", "threshold": 90},
        status=201,
    )
    resp = await stack.client.post(
        f"/api/v1/projects/{p['id']}/alert-rules", json={"name": "bad", "kind": "score_below"}
    )
    assert resp.status_code == 422
    scan = await stack.scan(p["id"], d["id"])
    assert scan["score"] == 25.0
    active = await stack.ok("GET", f"/api/v1/projects/{p['id']}/incidents?status=active")
    assert len(active) == 1 and "25.0%" in active[0]["title"]
    ack = await stack.ok(
        "POST", f"/api/v1/projects/{p['id']}/incidents/{active[0]['id']}/acknowledge"
    )
    assert ack["status"] == "acknowledged"


async def test_channel_test_send_and_private_url_refusal(stack: Stack) -> None:
    p = await stack.project()
    ch = await stack.ok(
        "POST",
        f"/api/v1/projects/{p['id']}/alert-channels",
        {"name": "hook", "kind": "webhook", "url": f"{stack.mock_ai_url}/webhook"},
        status=201,
    )
    assert ch["signing_secret"]  # generated and shown once
    assert (await stack.ok("POST", f"/api/v1/projects/{p['id']}/alert-channels/{ch['id']}/test"))[
        "ok"
    ] is True


async def test_private_webhooks_are_refused_unless_allowed(stack: Stack) -> None:
    stack.settings.outbound_allow_private = False
    try:
        p = await stack.project()
        ch = await stack.ok(
            "POST",
            f"/api/v1/projects/{p['id']}/alert-channels",
            {"name": "internal", "kind": "slack", "url": "http://127.0.0.1:9/hook"},
            status=201,
        )
        resp = await stack.client.post(f"/api/v1/projects/{p['id']}/alert-channels/{ch['id']}/test")
        assert resp.status_code == 400 and "private" in resp.json()["error"]["message"]
    finally:
        stack.settings.outbound_allow_private = True


async def test_opening_many_incidents_on_one_connection(stack: Stack, tmp_path: Path) -> None:
    """PostgreSQL switches a prepared statement to a generic plan after five runs; the
    incident insert must still find its partial unique index then (it once did not)."""
    import uuid

    from dataquality.alerts.engine import evaluate
    from dataquality.core.container import Container
    from dataquality.datasets.models import Dataset
    from dataquality.scans.models import CheckResult, Scan

    p = await stack.project()
    path = tmp_path / "t.csv"
    pl.DataFrame({"id": [1, None]}).write_csv(path)
    d = await stack.upload(p["id"], path, "t")
    await stack.ok(
        "POST",
        f"/api/v1/projects/{p['id']}/alert-rules",
        {"name": "all", "kind": "check_failed"},
        status=201,
    )
    container = Container.build(stack.settings)
    try:
        async with container.db.sessionmaker() as session:
            dataset = await session.get(Dataset, uuid.UUID(d["id"]))
            assert dataset is not None
            for i in range(12):
                scan = Scan(
                    id=uuid.uuid4(),
                    project_id=dataset.project_id,
                    dataset_id=dataset.id,
                    status="succeeded",
                )
                result = CheckResult(
                    scan_id=scan.id,
                    check_name=f"check {i}",
                    type="not_null",
                    severity="error",
                    dimension="completeness",
                    status="fail",
                    message="1 of 2 rows fail",
                )
                opened, _ = await evaluate(session, dataset, scan, [result], [])
                assert opened == 1, i
                await session.commit()
    finally:
        await container.close()
