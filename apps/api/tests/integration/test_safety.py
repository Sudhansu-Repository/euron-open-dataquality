"""AC3 and AC4: the platform never writes to a source, and source credentials are sealed."""

from __future__ import annotations

import logging

import pytest
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from dataquality.sources.sql import SqlTarget, open_sql
from tests.integration.conftest import Sources, Stack

pytestmark = pytest.mark.asyncio

WRITES = [
    "DELETE FROM {table}",
    "UPDATE {table} SET email = NULL",
    "SELECT 1; DROP TABLE customers",
    "INSERT INTO customers (customer_id) VALUES (1)",
    "SELECT * INTO copy_table FROM {table}",
    "SELECT pg_sleep(30)",
    "SELECT * FROM {table} FOR UPDATE",
    "SELECT * FROM read_csv('/etc/passwd')",
    "WITH x AS (DELETE FROM customers RETURNING *) SELECT * FROM x",
]


async def test_write_sql_in_a_custom_check_is_refused(
    stack: Stack, golden_sources: Sources
) -> None:
    p = await stack.project()
    conn = await stack.connection(p["id"], golden_sources.postgres)
    d = await stack.table_dataset(p["id"], conn["id"], "customers")
    for sql in WRITES:
        resp = await stack.client.post(
            f"/api/v1/projects/{p['id']}/datasets/{d['id']}/checks",
            json={"name": "evil", "type": "custom_sql", "params": {"sql": sql}},
        )
        assert resp.status_code == 400, (sql, resp.text)
        assert resp.json()["error"]["code"] == "unsafe_sql", sql
    resp = await stack.client.post(
        f"/api/v1/projects/{p['id']}/datasets",
        json={
            "name": "evil query",
            "kind": "query",
            "connection_id": conn["id"],
            "query_sql": "DELETE FROM customers",
        },
    )
    assert resp.status_code == 400 and resp.json()["error"]["code"] == "unsafe_sql"
    resp = await stack.client.patch(
        f"/api/v1/projects/{p['id']}/datasets/{d['id']}",
        json={"filter_sql": "1=1; DROP TABLE customers"},
    )
    assert resp.status_code == 400


@pytest.mark.parametrize("kind", ["postgresql", "mysql", "sqlite", "duckdb"])
async def test_scan_sessions_refuse_writes(
    golden_sources: Sources, kind: str, tmp_path: object
) -> None:
    """Even SQL that got past the guard could not write: the database refuses it."""
    import asyncio

    from dataquality.sources.files import FileTable, open_files

    def attempt() -> None:
        if kind == "duckdb":
            table = FileTable("customers", golden_sources.files["csv"], "csv", {})
            with open_files([table]) as c:
                c.exec_driver_sql("COPY customers TO '/tmp/dq-leak.csv'")
            return
        if kind == "sqlite":
            target = SqlTarget(kind="sqlite", sqlite_path=str(golden_sources.sqlite))
        else:
            src = golden_sources.postgres if kind == "postgresql" else golden_sources.mysql
            # Even with the admin login (which may write), the scan session is read-only.
            from tests.sources import admin_password

            user = "warehouse_admin" if kind == "postgresql" else "root"
            target = SqlTarget(
                kind=kind,
                host=src.host,
                port=src.port,
                database=src.database,
                username=user,
                password=admin_password(),
                ssl_mode="disable",
            )
        with open_sql(target, 10) as c:
            c.exec_driver_sql("DELETE FROM customers")

    with pytest.raises(sa.exc.DBAPIError):
        await asyncio.to_thread(attempt)


async def test_passwords_are_sealed_and_never_returned(
    stack: Stack, golden_sources: Sources, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    p = await stack.project()
    src = golden_sources.postgres
    conn = await stack.connection(p["id"], src)
    assert conn["has_password"] is True and "password" not in conn
    for path in (
        f"/api/v1/projects/{p['id']}/connections",
        f"/api/v1/projects/{p['id']}/connections/{conn['id']}",
    ):
        resp = await stack.client.get(path)
        assert src.password not in resp.text
    test = await stack.ok("POST", f"/api/v1/projects/{p['id']}/connections/{conn['id']}/test")
    assert test["ok"] is True, test
    engine = create_async_engine(stack.settings.database_url)
    async with engine.connect() as c:
        row = (
            await c.execute(
                text("SELECT config::text, secret_sealed FROM connections WHERE id = :i"),
                {"i": conn["id"]},
            )
        ).one()
    await engine.dispose()
    assert src.password not in row[0]
    assert src.password.encode() not in bytes(row[1])
    assert src.password not in caplog.text


async def test_wrong_password_gets_an_actionable_message(
    stack: Stack, golden_sources: Sources
) -> None:
    p = await stack.project()
    src = golden_sources.postgres
    body = {
        "name": "x",
        "kind": "postgresql",
        "host": src.host,
        "port": src.port,
        "database": src.database,
        "username": src.username,
        "password": "wrong-password",
        "ssl_mode": "disable",
    }
    result = await stack.ok("POST", f"/api/v1/projects/{p['id']}/connections/test", body)
    assert result["ok"] is False and "username or password" in result["message"]
    body["port"] = 1
    result = await stack.ok("POST", f"/api/v1/projects/{p['id']}/connections/test", body)
    assert result["ok"] is False and "port" in result["message"].lower()


async def test_metadata_hosts_are_refused(stack: Stack) -> None:
    p = await stack.project()
    for host in ("169.254.169.254", "0xa9fea9fe", "[fd00:ec2::254]"):
        resp = await stack.client.post(
            f"/api/v1/projects/{p['id']}/connections",
            json={
                "name": "m",
                "kind": "postgresql",
                "host": host,
                "database": "d",
                "username": "u",
            },
        )
        assert resp.status_code == 422, (host, resp.text)
