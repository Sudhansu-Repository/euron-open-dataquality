"""The configuration surface end to end: alert channels and rules, incidents by hand,
projects, members, sessions and the server CLI."""

from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path

import httpx
import polars as pl
import pytest

from tests.integration.conftest import ADMIN, Stack, login

pytestmark = pytest.mark.asyncio


async def test_channels_and_rules_lifecycle(stack: Stack) -> None:
    p = await stack.project()
    base = f"/api/v1/projects/{p['id']}"
    email = await stack.ok(
        "POST",
        f"{base}/alert-channels",
        {"name": "team", "kind": "email", "recipients": ["a@example.test"]},
        status=201,
    )
    slack = await stack.ok(
        "POST",
        f"{base}/alert-channels",
        {"name": "slack", "kind": "slack", "url": "https://hooks.slack.example/T1/B1/x"},
        status=201,
    )
    assert slack["target_hint"] == "hooks.slack.example" and slack["signing_secret"] is None
    dup = await stack.client.post(
        f"{base}/alert-channels",
        json={"name": "team", "kind": "email", "recipients": ["b@example.test"]},
    )
    assert dup.status_code == 409
    bad = await stack.client.post(f"{base}/alert-channels", json={"name": "x", "kind": "email"})
    assert bad.status_code == 422
    updated = await stack.ok(
        "PATCH",
        f"{base}/alert-channels/{email['id']}",
        {"recipients": ["c@example.test", "d@example.test"], "enabled": False},
    )
    assert (
        updated["recipients"] == ["c@example.test", "d@example.test"]
        and updated["enabled"] is False
    )
    await stack.ok(
        "PATCH",
        f"{base}/alert-channels/{slack['id']}",
        {"url": "https://hooks.slack.example/T2/B2/y", "name": "slack 2"},
    )
    rule = await stack.ok(
        "POST",
        f"{base}/alert-rules",
        {
            "name": "fails",
            "kind": "check_failed",
            "channel_ids": [email["id"]],
            "min_severity": "warn",
        },
        status=201,
    )
    other = await stack.project("Other")
    foreign = await stack.ok(
        "POST",
        f"/api/v1/projects/{other['id']}/alert-channels",
        {"name": "x", "kind": "email", "recipients": ["x@example.test"]},
        status=201,
    )
    resp = await stack.client.post(
        f"{base}/alert-rules",
        json={"name": "bad", "kind": "anomaly", "channel_ids": [foreign["id"]]},
    )
    assert resp.status_code == 404
    changed = await stack.ok(
        "PATCH",
        f"{base}/alert-rules/{rule['id']}",
        {"enabled": False, "channel_ids": [email["id"], slack["id"]]},
    )
    assert changed["enabled"] is False and len(changed["channel_ids"]) == 2
    resp = await stack.client.patch(f"{base}/alert-rules/{rule['id']}", json={"threshold": None})
    assert resp.status_code == 200
    rules = await stack.ok("GET", f"{base}/alert-rules")
    assert [r["name"] for r in rules] == ["fails"]
    await stack.ok("DELETE", f"{base}/alert-rules/{rule['id']}", status=204)
    await stack.ok("DELETE", f"{base}/alert-channels/{email['id']}", status=204)
    assert [c["name"] for c in await stack.ok("GET", f"{base}/alert-channels")] == ["slack 2"]


async def test_manual_resolve_and_explain_when_ai_is_off(stack: Stack, tmp_path: Path) -> None:
    p = await stack.project()
    base = f"/api/v1/projects/{p['id']}"
    path = tmp_path / "t.csv"
    pl.DataFrame({"id": [1, None]}).write_csv(path)
    d = await stack.upload(p["id"], path, "t")
    await stack.add_checks(p["id"], d["id"], [{"type": "not_null", "column": "id"}])
    await stack.ok(
        "POST", f"{base}/alert-rules", {"name": "all", "kind": "check_failed"}, status=201
    )
    await stack.scan(p["id"], d["id"])
    [incident] = await stack.ok("GET", f"{base}/incidents")
    resp = await stack.client.post(f"{base}/incidents/{incident['id']}/explain")
    assert resp.status_code == 409
    done = await stack.ok("POST", f"{base}/incidents/{incident['id']}/resolve")
    assert done["status"] == "resolved" and done["resolution"] == "manual"
    again = await stack.ok("POST", f"{base}/incidents/{incident['id']}/resolve")
    assert again["status"] == "resolved"
    resp = await stack.client.post(f"{base}/incidents/{incident['id']}/acknowledge")
    assert resp.status_code == 409
    assert await stack.ok("GET", f"{base}/incidents?status=active") == []
    assert len(await stack.ok("GET", f"{base}/incidents?status=resolved")) == 1


async def test_ai_explains_an_incident_when_on(stack: Stack, tmp_path: Path) -> None:
    async with httpx.AsyncClient() as c:
        await c.post(f"{stack.mock_ai_url}/admin/reset", json={})
    await stack.ok(
        "PATCH",
        "/api/v1/org/settings",
        {"ai_enabled": True, "ai_base_url": f"{stack.mock_ai_url}/v1", "ai_model": "mock"},
    )
    p = await stack.project()
    base = f"/api/v1/projects/{p['id']}"
    path = tmp_path / "t.csv"
    pl.DataFrame({"id": [1, None]}).write_csv(path)
    d = await stack.upload(p["id"], path, "t")
    await stack.add_checks(p["id"], d["id"], [{"type": "not_null", "column": "id"}])
    await stack.ok(
        "POST", f"{base}/alert-rules", {"name": "all", "kind": "check_failed"}, status=201
    )
    await stack.scan(p["id"], d["id"])
    [incident] = await stack.ok("GET", f"{base}/incidents")
    out = await stack.ok("POST", f"{base}/incidents/{incident['id']}/explain")
    assert "mock explanation" in out["explanation"] and out["model"] == "mock"
    async with httpx.AsyncClient() as c:
        await c.post(f"{stack.mock_ai_url}/admin/reset", json={"fail": True})
    resp = await stack.client.post(f"{base}/incidents/{incident['id']}/explain")
    assert resp.status_code == 502 and resp.json()["error"]["code"] == "ai_unavailable"
    async with httpx.AsyncClient() as c:
        await c.post(f"{stack.mock_ai_url}/admin/reset", json={})
    resp = await stack.client.patch(
        "/api/v1/org/settings", json={"ai_base_url": "http://169.254.169.254/v1"}
    )
    assert resp.status_code == 422


async def test_projects_members_and_sessions(stack: Stack) -> None:
    p = await stack.project("Finance")
    base = f"/api/v1/projects/{p['id']}"
    updated = await stack.ok(
        "PATCH",
        base,
        {
            "name": "Finance data",
            "sample_size": 5,
            "retention_days": 30,
            "anomaly_sensitivity": 4.0,
        },
    )
    assert (updated["name"], updated["sample_size"], updated["retention_days"]) == (
        "Finance data",
        5,
        30,
    )
    dup = await stack.client.post("/api/v1/projects", json={"name": "x", "slug": updated["slug"]})
    assert dup.status_code == 409
    missing = await stack.client.post(f"{base}/members", json={"email": "nobody@example.test"})
    assert missing.status_code == 404
    member = await stack.user()
    email = member.headers["x-test-email"]
    added = await stack.ok("POST", f"{base}/members", {"email": email, "role": "owner"}, status=201)
    again = await stack.client.post(f"{base}/members", json={"email": email})
    assert again.status_code == 409
    await stack.ok("DELETE", f"{base}/members/{added['user_id']}", status=204)
    # Sessions: sign out ends the session server-side; a password change ends the others.
    second = await login(stack.api_url)
    assert (await second.post("/api/v1/auth/logout")).status_code == 200
    assert (await second.get("/api/v1/auth/me")).status_code == 401
    session = (await second.get("/api/v1/auth/session")).json()
    assert session["user"] is None
    other = await login(stack.api_url)
    changed = await stack.ok(
        "POST",
        "/api/v1/auth/password",
        {"current_password": ADMIN["password"], "new_password": "Changed-Pass-456"},
    )
    # Every session ends, this one too; the response carries a fresh token.
    stack.client.headers["authorization"] = f"Bearer {changed['session_token']}"
    assert (await other.get("/api/v1/auth/me")).status_code == 401
    wrong = await stack.client.post(
        "/api/v1/auth/login", json={"email": ADMIN["email"], "password": "nope"}
    )
    assert wrong.status_code == 401
    await stack.ok("DELETE", base, status=204)
    assert (await stack.client.get(base)).status_code in (401, 404)
    for c in (member, second, other):
        await c.aclose()


async def test_server_cli(stack: Stack) -> None:
    env = {
        "DATABASE_URL": stack.settings.database_url,
        "PATH": "/usr/bin:/bin",
        "DATAQUALITY_ADMIN_PASSWORD": "Cli-Admin-Pass-1",
    }

    def run(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "dataquality.cli", *args],
            capture_output=True,
            text=True,
            env=env,
            timeout=120,
            check=False,
        )

    out = await asyncio.to_thread(run, "openapi")
    assert out.returncode == 0 and out.stdout.startswith("openapi:")
    out = await asyncio.to_thread(
        run, "create-admin", "--email", "ops@example.test", "--name", "Ops"
    )
    assert out.returncode == 0 and "created ops@example.test" in out.stdout
    out = await asyncio.to_thread(run, "create-admin", "--email", "ops@example.test")
    assert out.returncode == 0 and "updated" in out.stdout
    out = await asyncio.to_thread(run, "migrate")
    assert out.returncode == 0 and "migrations applied" in out.stdout
    ops = await login(stack.api_url, {"email": "ops@example.test", "password": "Cli-Admin-Pass-1"})
    assert (await ops.get("/api/v1/auth/me")).json()["role"] == "admin"
    await ops.aclose()
