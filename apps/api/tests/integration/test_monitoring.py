"""AC10, AC11 and AC14: anomalies on the history, schema drift between scans, push datasets
and project API keys."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import polars as pl
import pytest

from tests.integration.conftest import Stack, by_name

pytestmark = pytest.mark.asyncio


def records(n: int, missing: int = 0) -> list[dict[str, Any]]:
    return [
        {
            "signup_id": i,
            "email": None if i < missing else f"p{i}@example.com",
            "plan": "pro" if i % 3 else "free",
        }
        for i in range(n)
    ]


async def key(stack: Stack, project_id: str, scopes: list[str]) -> httpx.AsyncClient:
    created = await stack.ok(
        "POST",
        f"/api/v1/projects/{project_id}/api-keys",
        {"name": "ci", "scopes": scopes},
        status=201,
    )
    assert created["key"].startswith("dq_")
    return httpx.AsyncClient(
        base_url=stack.api_url, timeout=120, headers={"authorization": f"Bearer {created['key']}"}
    )


async def test_push_records_validates_them_and_volume_drop_is_an_anomaly(stack: Stack) -> None:
    p = await stack.project()
    d = await stack.ok(
        "POST",
        f"/api/v1/projects/{p['id']}/datasets",
        {"name": "signups", "kind": "push"},
        status=201,
    )
    await stack.add_checks(p["id"], d["id"], [{"type": "not_null", "column": "email"}])
    pusher = await key(stack, p["id"], ["push", "read"])
    path = f"/api/v1/projects/{p['id']}/datasets/{d['id']}/records"
    for i in range(8):
        resp = await pusher.post(path, json={"records": records(100 + i)})
        assert resp.status_code == 200, resp.text
        assert resp.json()["passed"] is True
    resp = await pusher.post(path, json={"records": records(10, missing=4)})
    body = resp.json()
    assert body["passed"] is False and body["records"] == 10
    assert by_name(body["scan"])["email not null"]["failed"] == 4
    anomalies = await stack.ok("GET", f"/api/v1/projects/{p['id']}/anomalies?dataset_id={d['id']}")
    volume = [a for a in anomalies if a["metric"] == "row_count"]
    assert volume, anomalies
    assert volume[0]["direction"] == "down" and "Row count is 10" in volume[0]["explanation"]
    # Normal variation (100 to 107 rows) raised nothing before the drop.
    assert len(volume) == 1
    history = await stack.ok(
        "GET", f"/api/v1/projects/{p['id']}/datasets/{d['id']}/metrics?metric=row_count"
    )
    assert [pt["value"] for pt in history[0]["points"]][-1] == 10.0
    await pusher.aclose()


async def test_api_keys_are_scoped_to_one_project(stack: Stack) -> None:
    a = await stack.project("A")
    b = await stack.project("B")
    d = await stack.ok(
        "POST",
        f"/api/v1/projects/{a['id']}/datasets",
        {"name": "events", "kind": "push"},
        status=201,
    )
    reader = await key(stack, a["id"], ["read"])
    scanner = await key(stack, b["id"], ["read", "scan", "push"])
    assert (await reader.get(f"/api/v1/projects/{a['id']}/datasets")).status_code == 200
    resp = await reader.post(
        f"/api/v1/projects/{a['id']}/datasets/{d['id']}/records", json={"records": records(3)}
    )
    assert resp.status_code == 403 and resp.json()["error"]["code"] == "insufficient_scope"
    assert (await scanner.get(f"/api/v1/projects/{a['id']}/datasets")).status_code == 404
    keys = await stack.ok("GET", f"/api/v1/projects/{a['id']}/api-keys")
    await stack.ok("DELETE", f"/api/v1/projects/{a['id']}/api-keys/{keys[0]['id']}")
    assert (await reader.get(f"/api/v1/projects/{a['id']}/datasets")).status_code == 401
    bad = httpx.AsyncClient(base_url=stack.api_url, headers={"x-api-key": "dq_000000000000_forged"})
    assert (await bad.get(f"/api/v1/projects/{a['id']}/datasets")).status_code == 401
    for c in (reader, scanner, bad):
        await c.aclose()


async def test_a_key_with_scan_scope_triggers_and_waits(stack: Stack, tmp_path: Path) -> None:
    p = await stack.project()
    path = tmp_path / "orders.csv"
    pl.DataFrame({"order_id": [1, 2, 2], "total": [10.0, -1.0, 5.0]}).write_csv(path)
    d = await stack.upload(p["id"], path, "orders")
    await stack.add_checks(
        p["id"],
        d["id"],
        [
            {"type": "unique", "column": "order_id"},
            {"type": "range", "column": "total", "params": {"min": 0}},
        ],
    )
    ci = await key(stack, p["id"], ["read", "scan"])
    resp = await ci.post(
        f"/api/v1/projects/{p['id']}/datasets/{d['id']}/scans", params={"wait": 60}
    )
    assert resp.status_code == 200, resp.text
    scan = resp.json()
    assert scan["trigger"] == "api" and scan["checks_failed"] == 2
    await ci.aclose()


async def test_schema_drift_between_uploads(stack: Stack, tmp_path: Path) -> None:
    p = await stack.project()
    v1 = tmp_path / "people.csv"
    pl.DataFrame({"id": [1, 2], "name": ["a", "b"], "age": [30, 40]}).write_csv(v1)
    d = await stack.upload(p["id"], v1, "people")
    first = await stack.scan(p["id"], d["id"])
    assert first["status"] == "succeeded"
    v2 = tmp_path / "people2.csv"
    pl.DataFrame({"id": [1, 2], "age": ["thirty", "forty"], "city": ["x", "y"]}).write_csv(v2)
    with v2.open("rb") as f:
        resp = await stack.client.post(
            f"/api/v1/projects/{p['id']}/datasets/{d['id']}/files",
            files={"file": ("people.csv", f)},
        )
    assert resp.status_code == 201
    await stack.scan(p["id"], d["id"])
    drift = [
        a
        for a in await stack.ok("GET", f"/api/v1/projects/{p['id']}/anomalies")
        if a["kind"] == "schema"
    ]
    changes = {(a["key"], a["explanation"]) for a in drift}
    assert ("name", "Column name was removed") in changes
    assert ("city", "Column city was added (text)") in changes
    assert ("age", "Column age changed type from integer to text") in changes


async def test_rest_dataset_reads_the_feed(stack: Stack) -> None:
    p = await stack.project()
    body = {
        "name": "partner leads",
        "kind": "rest",
        "rest": {"url": f"{stack.mock_ai_url}/feed/leads?bad=3", "records_path": "data.items"},
        "rest_headers": {"authorization": "Bearer partner-token"},
    }
    d = await stack.ok("POST", f"/api/v1/projects/{p['id']}/datasets", body, status=201)
    assert d["has_secret"] is True and "partner-token" not in str(d)
    await stack.add_checks(
        p["id"],
        d["id"],
        [{"type": "not_null", "column": "email"}, {"type": "unique", "column": "lead_id"}],
    )
    scan = await stack.scan(p["id"], d["id"])
    assert scan["row_count"] == 40, scan
    assert by_name(scan)["email not null"]["failed"] == 3
    assert {c["name"] for c in scan["columns"]} >= {"lead_id", "email", "score", "meta"}
