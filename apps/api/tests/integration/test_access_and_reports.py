"""AC13, AC15 and AC16: reports match the API, project roles hold on every route, and the
AI assistant is optional and careful with data."""

from __future__ import annotations

import csv
import io
from pathlib import Path

import httpx
import polars as pl
import pytest

from tests.integration.conftest import Stack

pytestmark = pytest.mark.asyncio


async def _scanned(stack: Stack, tmp_path: Path) -> tuple[dict, dict, dict]:  # type: ignore[type-arg]
    p = await stack.project("Reports")
    path = tmp_path / "sales.csv"
    pl.DataFrame(
        {
            "id": [1, 2, 2, 4],
            "amount": [5.0, -2.0, 3.0, None],
            "email": ["a@x.io", "=cmd|' /C calc'!A0", "b@x.io", "c@x.io"],
        }
    ).write_csv(path)
    d = await stack.upload(p["id"], path, "sales")
    await stack.add_checks(
        p["id"],
        d["id"],
        [
            {"type": "unique", "column": "id"},
            {"type": "range", "column": "amount", "params": {"min": 0}},
            {"type": "pattern", "column": "email", "params": {"preset": "email"}},
        ],
    )
    scan = await stack.scan(p["id"], d["id"])
    return p, d, scan


async def test_reports_match_the_api(stack: Stack, tmp_path: Path) -> None:
    p, d, scan = await _scanned(stack, tmp_path)
    raw = await stack.ok("GET", f"/api/v1/projects/{p['id']}/scans/{scan['id']}/report.csv")
    rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
    assert len(rows) == len(scan["results"])
    by = {r["check"]: r for r in rows}
    for r in scan["results"]:
        assert int(by[r["check_name"]]["failed"]) == r["failed"]
        assert by[r["check_name"]]["status"] == r["status"]
    cells = [c for r in rows for c in r.values()]
    assert not any(c.startswith(("=", "+", "-", "@")) for c in cells if c), "formula injection"
    pdf = await stack.ok("GET", f"/api/v1/projects/{p['id']}/scans/{scan['id']}/report.pdf")
    assert pdf.startswith(b"%PDF") and len(pdf) > 2000
    history = await stack.ok("GET", f"/api/v1/projects/{p['id']}/datasets/{d['id']}/history.csv")
    assert history.decode("utf-8-sig").count("\n") == 2
    summary = await stack.ok("GET", f"/api/v1/projects/{p['id']}/report.pdf")
    assert summary.startswith(b"%PDF")
    dash = await stack.ok("GET", f"/api/v1/projects/{p['id']}/dashboard")
    assert dash["score"] == scan["score"] and dash["datasets"] == 1
    assert dash["failed_checks"] == scan["checks_failed"] + scan["checks_warned"]
    assert dash["duplicate_records"] == 1 and dash["records_scanned"] == 4
    assert {i["check_name"] for i in dash["issues"]} == {
        r["check_name"] for r in scan["results"] if r["status"] == "fail"
    }


async def test_project_roles_hold(stack: Stack, tmp_path: Path) -> None:
    p, d, scan = await _scanned(stack, tmp_path)
    viewer = await stack.user()
    outsider = await stack.user()
    await stack.ok(
        "POST",
        f"/api/v1/projects/{p['id']}/members",
        {"email": viewer.headers["x-test-email"], "role": "viewer"},
        status=201,
    )
    base = f"/api/v1/projects/{p['id']}"
    assert (await viewer.get(f"{base}/datasets")).status_code == 200
    assert (await viewer.get(f"{base}/scans/{scan['id']}")).status_code == 200
    for method, path, body in [
        ("POST", f"{base}/datasets/{d['id']}/checks", {"type": "not_null", "column": "id"}),
        ("POST", f"{base}/datasets/{d['id']}/scans", None),
        ("DELETE", f"{base}/datasets/{d['id']}", None),
        ("POST", f"{base}/api-keys", {"name": "x"}),
        ("POST", f"{base}/alert-rules", {"name": "x", "kind": "anomaly"}),
        ("PATCH", base, {"name": "renamed"}),
    ]:
        resp = await viewer.request(method, path, json=body)
        assert resp.status_code == 403, (method, path, resp.status_code)
    for path in (base, f"{base}/datasets", f"{base}/scans/{scan['id']}", f"{base}/dashboard"):
        assert (await outsider.get(path)).status_code == 404, path
    assert (await outsider.get("/api/v1/projects")).json() == []
    mine = (await viewer.get("/api/v1/projects")).json()
    assert [x["role"] for x in mine] == ["viewer"]
    # Promote to editor: now checks can be added.
    me = (await viewer.get("/api/v1/auth/me")).json()
    await stack.ok("PATCH", f"{base}/members/{me['id']}", {"role": "editor"})
    resp = await viewer.post(
        f"{base}/datasets/{d['id']}/checks", json={"type": "not_null", "column": "id"}
    )
    assert resp.status_code == 201
    # The last owner cannot be removed.
    admin_me = await stack.ok("GET", "/api/v1/auth/me")
    resp = await stack.client.delete(f"{base}/members/{admin_me['id']}")
    assert resp.status_code == 409


async def test_ai_is_off_by_default_and_careful_when_on(stack: Stack, tmp_path: Path) -> None:
    async with httpx.AsyncClient() as c:
        await c.post(f"{stack.mock_ai_url}/admin/reset", json={})
    p, d, _ = await _scanned(stack, tmp_path)
    draft = f"/api/v1/projects/{p['id']}/datasets/{d['id']}/checks/draft"
    resp = await stack.client.post(draft, json={"prompt": "emails must be valid"})
    assert resp.status_code == 409 and resp.json()["error"]["code"] == "ai_disabled"
    async with httpx.AsyncClient() as c:
        assert (await c.get(f"{stack.mock_ai_url}/stats")).json()["requests"] == 0
    await stack.ok(
        "PATCH",
        "/api/v1/org/settings",
        {
            "ai_enabled": True,
            "ai_base_url": f"{stack.mock_ai_url}/v1",
            "ai_model": "mock",
            "ai_api_key": "sk-test-key",
        },
    )
    before = len(await stack.ok("GET", f"/api/v1/projects/{p['id']}/datasets/{d['id']}/checks"))
    out = await stack.ok("POST", draft, {"prompt": "emails must be valid"})
    assert out["check"]["type"] == "pattern" and out["check"]["params"] == {"preset": "email"}
    assert (
        len(await stack.ok("GET", f"/api/v1/projects/{p['id']}/datasets/{d['id']}/checks"))
        == before
    )
    async with httpx.AsyncClient() as c:
        last = (await c.get(f"{stack.mock_ai_url}/stats")).json()["last"]
    assert "a@x.io" not in str(last), "sample values were sent without permission"
    await stack.ok("PATCH", f"/api/v1/projects/{p['id']}", {"ai_allow_samples": True})
    await stack.ok("POST", draft, {"prompt": "emails must be valid"})
    async with httpx.AsyncClient() as c:
        last = (await c.get(f"{stack.mock_ai_url}/stats")).json()["last"]
    assert "a@x.io" in str(last)
    settings = await stack.ok("GET", "/api/v1/org/settings")
    assert settings["ai_has_key"] is True and "sk-test-key" not in str(settings)
