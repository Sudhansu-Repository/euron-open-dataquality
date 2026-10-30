"""The rest of the API surface: checks as code, setup, uploads, limits, audit, system."""

from __future__ import annotations

from pathlib import Path

import httpx
import polars as pl
import pytest

from tests.integration.conftest import Sources, Stack, by_name

pytestmark = pytest.mark.asyncio

YAML = """
version: 1
dataset: orders
checks:
  - name: id is unique
    type: unique
    column: id
  - name: total never negative
    type: range
    column: total
    params: {min: 0}
    severity: warn
    tolerance: {max_percent: 50}
"""


async def _orders(stack: Stack, tmp_path: Path) -> tuple[dict, dict]:  # type: ignore[type-arg]
    p = await stack.project()
    path = tmp_path / "orders.csv"
    pl.DataFrame(
        {
            "id": [1, 2, 3, 3],
            "total": [1.0, -2.0, 3.0, 4.0],
            "status": ["new", "paid", "paid", "void"],
        }
    ).write_csv(path)
    return p, await stack.upload(p["id"], path, "orders")


async def test_checks_as_code_round_trip_is_idempotent(stack: Stack, tmp_path: Path) -> None:
    p, d = await _orders(stack, tmp_path)
    path = f"/api/v1/projects/{p['id']}/datasets/{d['id']}/checks/yaml"
    first = await stack.ok("PUT", path, {"yaml": YAML})
    assert (first["created"], first["updated"]) == (2, 0)
    again = await stack.ok("PUT", path, {"yaml": YAML})
    assert (again["created"], again["updated"]) == (0, 0)
    exported = (await stack.ok("GET", path)).decode()
    assert "id is unique" in exported and "max_percent: 50" in exported
    pruned = await stack.ok("PUT", path, {"yaml": YAML.split("  - name: total")[0], "prune": True})
    assert pruned["removed"] == ["total never negative"]
    bad = await stack.client.put(path, json={"yaml": "checks:\n  - type: nonsense\n"})
    assert bad.status_code == 400 and "Check 1" in bad.json()["error"]["message"]


async def test_tolerance_and_filters(stack: Stack, tmp_path: Path) -> None:
    p, d = await _orders(stack, tmp_path)
    await stack.add_checks(
        p["id"],
        d["id"],
        [
            {
                "name": "lenient",
                "type": "range",
                "column": "total",
                "params": {"min": 0},
                "tolerance": {"max_percent": 30},
            },
            {
                "name": "paid only",
                "type": "range",
                "column": "total",
                "params": {"min": 0},
                "filter_sql": "status = 'paid'",
            },
            {
                "name": "broken filter",
                "type": "not_null",
                "column": "id",
                "filter_sql": "no_such_column = 1",
            },
        ],
    )
    results = by_name(await stack.scan(p["id"], d["id"]))
    assert results["lenient"]["status"] == "pass" and results["lenient"]["failed"] == 1
    assert (results["paid only"]["evaluated"], results["paid only"]["failed"]) == (2, 1)
    assert results["broken filter"]["status"] == "error" and results["broken filter"]["error"]


async def test_check_validation_errors_say_what_to_fix(stack: Stack, tmp_path: Path) -> None:
    p, d = await _orders(stack, tmp_path)
    base = f"/api/v1/projects/{p['id']}/datasets/{d['id']}/checks"
    for body, words in [
        ({"type": "range", "column": "total"}, "set min, max or both"),
        ({"type": "pattern", "column": "id", "params": {"regex": "\\d+"}}, "[0-9]"),
        ({"type": "not_null"}, "needs a column"),
        ({"type": "pattern", "column": "id", "params": {"preset": "nope"}}, "unknown preset"),
    ]:
        resp = await stack.client.post(base, json=body)
        assert resp.status_code == 400 and words in resp.json()["error"]["message"], resp.text
    created = await stack.ok("POST", base, {"type": "not_null", "column": "id"}, status=201)
    dup = await stack.client.post(base, json={"type": "not_null", "column": "id"})
    assert dup.status_code == 409
    patched = await stack.ok(
        "PATCH", f"{base}/{created['id']}", {"severity": "warn", "enabled": False}
    )
    assert (patched["severity"], patched["enabled"]) == ("warn", False)
    await stack.ok("DELETE", f"{base}/{created['id']}", status=204)


async def test_first_signup_becomes_admin_then_signup_closes(stack: Stack, database: str) -> None:
    from tests.integration.conftest import reset

    await reset(database)
    anon = httpx.AsyncClient(base_url=stack.api_url, headers={"x-dq-csrf": "1"})
    public = (await anon.get("/api/v1/org/public")).json()
    assert public["needs_setup"] is True and public["allow_signup"] is False
    resp = await anon.post(
        "/api/v1/auth/signup",
        json={"email": "owner@example.test", "name": "Owner", "password": "Owner-Pass-123"},
    )
    assert resp.status_code == 201 and resp.json()["user"]["role"] == "admin"
    resp = await anon.post(
        "/api/v1/auth/signup",
        json={"email": "late@example.test", "name": "Late", "password": "Late-Pass-1234"},
    )
    assert resp.status_code == 403 and resp.json()["error"]["code"] == "signup_closed"
    await anon.aclose()


async def test_uploads_refuse_what_they_cannot_read(stack: Stack, tmp_path: Path) -> None:
    p = await stack.project()
    for name, data, code in [
        ("notes.docx", b"PK\x03\x04junk", "unsupported_file"),
        ("data.parquet", b"not parquet", "unsupported_file"),
        ("empty.csv", b"", "file_empty"),
        ("broken.json", b'[{"a": 1}, {', "unreadable_file"),
    ]:
        resp = await stack.client.post(
            f"/api/v1/projects/{p['id']}/datasets/upload", files={"file": (name, data)}
        )
        assert resp.status_code == 400 and resp.json()["error"]["code"] == code, (name, resp.text)
    datasets = await stack.ok("GET", f"/api/v1/projects/{p['id']}/datasets")
    assert datasets == []  # nothing half-created
    resp = await stack.client.post(
        f"/api/v1/projects/{p['id']}/connections/sqlite",
        files={"file": ("x.sqlite", b"not sqlite")},
        data={"name": "x"},
    )
    assert resp.status_code == 400 and resp.json()["error"]["code"] == "not_sqlite"


async def test_large_bodies_need_a_real_session(stack: Stack) -> None:
    p = await stack.project()
    big = b"a,b\n" + b"1,2\n" * 1_000_000
    anon = httpx.AsyncClient(base_url=stack.api_url)
    try:
        resp = await anon.post(
            f"/api/v1/projects/{p['id']}/datasets/upload", files={"file": ("big.csv", big)}
        )
        assert resp.status_code == 413
    except httpx.TransportError:
        pass  # refused while still sending
    await anon.aclose()
    resp = await stack.client.post(
        f"/api/v1/projects/{p['id']}/datasets/upload", files={"file": ("big.csv", big)}
    )
    assert resp.status_code == 201, resp.text


async def test_query_datasets_masking_and_connection_lifecycle(
    stack: Stack, golden_sources: Sources
) -> None:
    p = await stack.project()
    conn = await stack.connection(p["id"], golden_sources.postgres)
    body = {
        "name": "indian customers",
        "kind": "query",
        "connection_id": conn["id"],
        "query_sql": "SELECT customer_id, email, country FROM customers WHERE country = 'IN'",
        "masked_columns": ["email"],
    }
    d = await stack.ok("POST", f"/api/v1/projects/{p['id']}/datasets", body, status=201)
    await stack.add_checks(
        p["id"], d["id"], [{"type": "pattern", "column": "email", "params": {"preset": "email"}}]
    )
    scan = await stack.scan(p["id"], d["id"])
    r = scan["results"][0]
    assert scan["row_count"] == 49 and r["failed"] >= 1
    assert all(row["email"] == "[masked]" for row in r["sample"] if row["email"] is not None)
    preview = await stack.ok("GET", f"/api/v1/projects/{p['id']}/datasets/{d['id']}/preview")
    assert all(row["email"] in (None, "[masked]") for row in preview["rows"])
    resp = await stack.client.delete(f"/api/v1/projects/{p['id']}/connections/{conn['id']}")
    assert resp.status_code == 409 and resp.json()["error"]["code"] == "connection_in_use"
    await stack.ok("DELETE", f"/api/v1/projects/{p['id']}/datasets/{d['id']}", status=204)
    await stack.ok("DELETE", f"/api/v1/projects/{p['id']}/connections/{conn['id']}", status=204)


async def test_a_missing_table_fails_the_scan_with_a_reason(
    stack: Stack, golden_sources: Sources
) -> None:
    p = await stack.project()
    conn = await stack.connection(p["id"], golden_sources.postgres)
    d = await stack.table_dataset(p["id"], conn["id"], "no_such_table")
    scan = await stack.scan(p["id"], d["id"])
    assert scan["status"] == "failed" and "no_such_table" in scan["error"]
    listed = await stack.ok("GET", f"/api/v1/projects/{p['id']}/scans?status=failed")
    assert [s["id"] for s in listed["items"]] == [scan["id"]]


async def test_audit_and_system(stack: Stack, tmp_path: Path) -> None:
    await _orders(stack, tmp_path)
    audit = await stack.ok("GET", "/api/v1/audit?action=dataset.")
    assert any(e["action"] == "dataset.created" for e in audit["items"])
    system = await stack.ok("GET", "/api/v1/system")
    assert system["datasets"] == 1 and system["queue"]["queued"] >= 0
    ready = await stack.ok("GET", "/readyz")
    assert ready["checks"]["postgres"]["ok"] is True
    user = await stack.user()
    assert (await user.get("/api/v1/system")).status_code == 403


async def test_checks_refuse_what_they_cannot_use(stack: Stack, tmp_path: Path) -> None:
    p, d = await _orders(stack, tmp_path)
    base = f"/api/v1/projects/{p['id']}/datasets/{d['id']}/checks"
    resp = await stack.client.post(base, json={"type": "unique"})
    assert resp.status_code == 400 and "needs a column" in resp.json()["error"]["message"]
    resp = await stack.client.post(
        base, json={"type": "row_count", "params": {"min": 1}, "filter_sql": "total > 0"}
    )
    assert resp.status_code == 400 and resp.json()["error"]["code"] == "filter_not_supported"


async def test_retention_purges_old_results_and_batches(stack: Stack) -> None:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from dataquality.core.container import Container
    from dataquality.scans.tasks import purge

    p = await stack.project()
    d = await stack.ok(
        "POST",
        f"/api/v1/projects/{p['id']}/datasets",
        {"name": "events", "kind": "push"},
        status=201,
    )
    path = f"/api/v1/projects/{p['id']}/datasets/{d['id']}/records"
    for i in range(3):
        await stack.ok("POST", path, {"records": [{"n": i}]})
    engine = create_async_engine(stack.settings.database_url)
    async with engine.begin() as c:
        await c.execute(
            text("UPDATE scans SET created_at = now() - interval '200 days' WHERE dataset_id = :d"),
            {"d": d["id"]},
        )
        await c.execute(
            text(
                "UPDATE dataset_files SET created_at = now() - interval '200 days' WHERE dataset_id = :d"
            ),
            {"d": d["id"]},
        )
    container = Container.build(stack.settings)
    try:
        assert (
            await purge(container) == 4
        )  # 2 old scans (the latest stays), 2 old batches (the current stays)
    finally:
        await container.close()
    async with engine.connect() as c:
        scans = (
            await c.execute(
                text("SELECT count(*) FROM scans WHERE dataset_id = :d"), {"d": d["id"]}
            )
        ).scalar()
        files = (
            await c.execute(
                text("SELECT count(*) FROM dataset_files WHERE dataset_id = :d"), {"d": d["id"]}
            )
        ).scalar()
        dangling = (
            await c.execute(
                text(
                    "SELECT count(*) FROM metric_points m WHERE m.scan_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM scans s WHERE s.id = m.scan_id)"
                )
            )
        ).scalar()
    await engine.dispose()
    assert (scans, files, dangling) == (1, 1, 0)
    assert (await stack.ok("GET", f"/api/v1/projects/{p['id']}/datasets/{d['id']}/files"))[0][
        "version"
    ] == 3
