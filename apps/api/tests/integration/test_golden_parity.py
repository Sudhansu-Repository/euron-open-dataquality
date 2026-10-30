"""AC1 and AC2: every built-in check finds exactly the planted defects, and the same data
gives the same results in PostgreSQL, MySQL, SQLite, SQL Server, CSV, Excel, JSON and
Parquet."""

from __future__ import annotations

from typing import Any

import pytest

from tests import golden
from tests.integration.conftest import Sources, Stack, by_name

pytestmark = pytest.mark.asyncio


def assert_golden(scan: dict[str, Any], backend: str) -> None:
    assert scan["status"] == "succeeded", scan.get("error")
    assert scan["row_count"] == golden.TOTAL, backend
    results = by_name(scan)
    problems = []
    for name, (status, evaluated, failed) in golden.EXPECTED.items():
        r = results[name]
        got = (r["status"], r["evaluated"], r["failed"])
        if got != (status, evaluated, failed):
            problems.append(
                f"{name}: expected {(status, evaluated, failed)}, got {got} {r['error'] or r['message']}"
            )
    assert not problems, f"{backend}:\n  " + "\n  ".join(problems)


async def _db_backend(stack: Stack, src: Any) -> dict[str, Any]:
    p = await stack.project(f"{src.kind} parity")
    conn = await stack.connection(p["id"], src)
    customers = await stack.table_dataset(p["id"], conn["id"], "customers")
    await stack.table_dataset(p["id"], conn["id"], "orders")
    await stack.add_checks(p["id"], customers["id"], golden.CHECKS)
    orders = next(
        d
        for d in await stack.ok("GET", f"/api/v1/projects/{p['id']}/datasets")
        if d["name"] == "orders"
    )
    await stack.add_checks(
        p["id"],
        orders["id"],
        [{**golden.REFERENTIAL, "params": {"dataset": "customers", "column": "customer_id"}}],
    )
    scan = await stack.scan(p["id"], customers["id"])
    ref = await stack.scan(p["id"], orders["id"])
    r = by_name(ref)["customer exists"]
    assert (r["status"], r["failed"]) == ("fail", golden.REFERENTIAL_FAILED), r
    return scan


async def test_postgres_finds_every_planted_defect(stack: Stack, golden_sources: Sources) -> None:
    assert_golden(await _db_backend(stack, golden_sources.postgres), "postgresql")


async def test_mysql_matches(stack: Stack, golden_sources: Sources) -> None:
    assert_golden(await _db_backend(stack, golden_sources.mysql), "mysql")


async def test_sql_server_matches(stack: Stack, golden_sources: Sources) -> None:
    if golden_sources.mssql is None:
        pytest.skip("the SQL Server source is not running (make test-integration MSSQL=1)")
    assert_golden(await _db_backend(stack, golden_sources.mssql), "mssql")


async def test_sqlite_matches(stack: Stack, golden_sources: Sources) -> None:
    p = await stack.project("sqlite parity")
    with golden_sources.sqlite.open("rb") as f:
        resp = await stack.client.post(
            f"/api/v1/projects/{p['id']}/connections/sqlite",
            files={"file": ("golden.sqlite", f)},
            data={"name": "golden sqlite"},
        )
    assert resp.status_code == 201, resp.text
    conn = resp.json()
    tables = await stack.ok("GET", f"/api/v1/projects/{p['id']}/connections/{conn['id']}/tables")
    assert {t["name"] for t in tables} == {"customers", "orders"}
    customers = await stack.table_dataset(p["id"], conn["id"], "customers")
    await stack.add_checks(p["id"], customers["id"], golden.CHECKS)
    assert_golden(await stack.scan(p["id"], customers["id"]), "sqlite")


@pytest.mark.parametrize("fmt", ["csv", "xlsx", "json", "parquet"])
async def test_files_match(stack: Stack, golden_sources: Sources, fmt: str) -> None:
    p = await stack.project(f"{fmt} parity")
    customers = await stack.upload(p["id"], golden_sources.files[fmt], "customers")
    orders = await stack.upload(p["id"], golden_sources.order_files[fmt], "orders")
    await stack.add_checks(p["id"], customers["id"], golden.CHECKS)
    await stack.add_checks(
        p["id"],
        orders["id"],
        [{**golden.REFERENTIAL, "params": {"dataset": "customers", "column": "customer_id"}}],
    )
    assert_golden(await stack.scan(p["id"], customers["id"]), fmt)
    r = by_name(await stack.scan(p["id"], orders["id"]))["customer exists"]
    assert (r["status"], r["failed"]) == ("fail", golden.REFERENTIAL_FAILED), (fmt, r)
