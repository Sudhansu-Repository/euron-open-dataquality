"""Open a source database read-only, with a statement timeout. Synchronous: the worker and
the API call these in threads.

Read-only is enforced by the database wherever it can be:

* PostgreSQL: ``default_transaction_read_only=on`` for the session, then every query runs
  in a read-only transaction; a write fails with "cannot execute ... in a read-only
  transaction".
* MySQL and MariaDB: ``SET SESSION TRANSACTION READ ONLY``.
* SQLite: the file is opened with ``mode=ro`` and ``PRAGMA query_only``.
* SQL Server has no session read-only mode. The platform only generates SELECTs and
  refuses custom SQL that is not one SELECT (``engine.sqlguard``), and the transaction is
  rolled back; connect with a ``db_datareader`` login for a database-enforced guarantee.

Every connection is closed after use (no pool): a scan holds one connection to the
customer's database and gives it back.
"""

from __future__ import annotations

import re
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import URL, Connection, Engine
from sqlalchemy.pool import NullPool

from dataquality.engine.patterns import shape

APP_NAME = "euron-dataquality"
DEFAULT_PORTS = {"postgresql": 5432, "mysql": 3306, "mssql": 1433}
_SYSTEM_SCHEMAS = {
    "postgresql": {"pg_catalog", "information_schema", "pg_toast"},
    "mysql": {"mysql", "information_schema", "performance_schema", "sys"},
    "mssql": {
        "sys",
        "INFORMATION_SCHEMA",
        "guest",
        "db_owner",
        "db_accessadmin",
        "db_securityadmin",
        "db_ddladmin",
        "db_backupoperator",
        "db_datareader",
        "db_datawriter",
        "db_denydatareader",
        "db_denydatawriter",
    },
}


@dataclass(frozen=True)
class SqlTarget:
    kind: str  # postgresql, mysql, mssql, sqlite
    host: str = ""
    port: int | None = None
    database: str = ""
    username: str = ""
    password: str | None = None
    ssl_mode: str = "prefer"
    sqlite_path: str | None = None


@dataclass(frozen=True)
class TableRef:
    schema: str | None
    name: str
    kind: str  # table or view


def _engine(t: SqlTarget, timeout_s: int) -> Engine:
    ms = timeout_s * 1000
    if t.kind == "postgresql":
        url = URL.create(
            "postgresql+psycopg",
            t.username or None,
            t.password,
            t.host,
            t.port or 5432,
            t.database or None,
        )
        options = f"-c default_transaction_read_only=on -c statement_timeout={ms}"
        args: dict[str, Any] = {
            "connect_timeout": 10,
            "options": options,
            "application_name": APP_NAME,
            "sslmode": t.ssl_mode or "prefer",
        }
        return sa.create_engine(url, poolclass=NullPool, connect_args=args, hide_parameters=True)
    if t.kind == "mysql":
        url = URL.create(
            "mysql+pymysql",
            t.username or None,
            t.password,
            t.host,
            t.port or 3306,
            t.database or None,
        )
        args = {"connect_timeout": 10, "read_timeout": timeout_s + 15, "charset": "utf8mb4"}
        if t.ssl_mode in ("require", "verify-full"):
            args["ssl"] = {"check_hostname": t.ssl_mode == "verify-full"}
        return sa.create_engine(url, poolclass=NullPool, connect_args=args, hide_parameters=True)
    if t.kind == "mssql":
        url = URL.create(
            "mssql+pymssql",
            t.username or None,
            t.password,
            t.host,
            t.port or 1433,
            t.database or None,
        )
        args = {"login_timeout": 10, "timeout": timeout_s, "appname": APP_NAME}
        return sa.create_engine(url, poolclass=NullPool, connect_args=args, hide_parameters=True)
    if t.kind == "sqlite":
        if not t.sqlite_path:
            raise ValueError("a SQLite source needs its database file")
        path = Path(t.sqlite_path).resolve().as_posix()
        return sa.create_engine(
            f"sqlite:///file:{path}?mode=ro&uri=true", poolclass=NullPool, hide_parameters=True
        )
    raise ValueError(f"unknown source kind {t.kind!r}")


def _prepare(conn: Connection, t: SqlTarget, timeout_s: int) -> None:
    if t.kind == "mysql":
        conn.exec_driver_sql("SET SESSION TRANSACTION READ ONLY")
        try:
            conn.exec_driver_sql(f"SET SESSION MAX_EXECUTION_TIME = {timeout_s * 1000}")
        except sa.exc.DBAPIError:
            conn.rollback()
            conn.exec_driver_sql("SET SESSION TRANSACTION READ ONLY")
            conn.exec_driver_sql(f"SET SESSION max_statement_time = {timeout_s}")  # MariaDB
    elif t.kind == "sqlite":
        raw = conn.connection.dbapi_connection
        assert isinstance(raw, sqlite3.Connection)
        raw.execute("PRAGMA query_only = 1")
        raw.create_function(
            "dq_shape", 1, lambda v: None if v is None else shape(v), deterministic=True
        )
        raw.create_function(
            "REGEXP",
            2,
            lambda pattern, v: None if v is None else re.search(pattern, str(v)) is not None,
            deterministic=True,
        )
        deadline = time.monotonic() + timeout_s
        # Interrupt a statement that runs past the timeout (checked every 100k VM steps).
        raw.set_progress_handler(lambda: int(time.monotonic() > deadline), 100_000)
    elif t.kind == "mssql":
        conn.exec_driver_sql("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
        conn.exec_driver_sql(f"SET LOCK_TIMEOUT {timeout_s * 1000}")


@contextmanager
def open_sql(t: SqlTarget, timeout_s: int) -> Iterator[Connection]:
    """A read-only connection inside a transaction that is always rolled back."""
    engine = _engine(t, timeout_s)
    try:
        with engine.connect() as conn:
            _prepare(conn, t, timeout_s)
            try:
                yield conn
            finally:
                conn.rollback()
    finally:
        engine.dispose()


def server_version(conn: Connection) -> str:
    kind = conn.dialect.name
    sql = {
        "postgresql": "SELECT version()",
        "mysql": "SELECT VERSION()",
        "mssql": "SELECT @@VERSION",
        "sqlite": "SELECT 'SQLite ' || sqlite_version()",
    }[kind]
    value = conn.exec_driver_sql(sql).scalar()
    return str(value or "").splitlines()[0][:200]


def list_tables(conn: Connection, schema: str | None = None, limit: int = 2000) -> list[TableRef]:
    """Tables and views the login can read, outside system schemas."""
    inspector = sa.inspect(conn)
    kind = conn.dialect.name
    if kind == "sqlite":
        schemas: list[str | None] = [None]
    elif schema:
        schemas = [schema]
    else:
        hidden = _SYSTEM_SCHEMAS.get(kind, set())
        schemas = [
            s for s in inspector.get_schema_names() if s not in hidden and not s.startswith("pg_")
        ]
        if kind == "mysql":
            current = conn.exec_driver_sql("SELECT DATABASE()").scalar()
            schemas = [str(current)] if current else schemas
    out: list[TableRef] = []
    for s in schemas:
        for name in inspector.get_table_names(schema=s):
            out.append(TableRef(None if kind == "sqlite" else s, name, "table"))
        for name in inspector.get_view_names(schema=s):
            out.append(TableRef(None if kind == "sqlite" else s, name, "view"))
        if len(out) >= limit:
            break
    return sorted(out, key=lambda r: ((r.schema or ""), r.name))[:limit]
