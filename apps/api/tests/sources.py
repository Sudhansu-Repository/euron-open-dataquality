"""Load the golden dataset into every kind of source the platform reads.

Databases get a ``customers`` and an ``orders`` table plus a read-only login (the platform
always connects as that login); files are written from the same rows with Polars.
"""

from __future__ import annotations

import datetime as dt
import os
import re
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import polars as pl

from tests import golden

ROOT = Path(__file__).resolve().parents[3]
READER_PASSWORD = "Reader-Pass-123"


def compose_env() -> dict[str, str]:
    path = ROOT / "deploy" / "compose" / ".env"
    out: dict[str, str] = {}
    if path.exists():
        for line in path.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                out[k.strip()] = v.strip()
    return out


def admin_password() -> str:
    return os.environ.get("TEST_SOURCE_ADMIN_PASSWORD") or compose_env().get(
        "DQ_SOURCE_ADMIN_PASSWORD", ""
    )


@dataclass(frozen=True)
class DbSource:
    kind: str
    host: str
    port: int
    database: str
    username: str
    password: str


PG_PORT = int(os.environ.get("DQ_SOURCE_PG_PORT", "4943"))
MYSQL_PORT = int(os.environ.get("DQ_SOURCE_MYSQL_PORT", "4906"))
MSSQL_PORT = int(os.environ.get("DQ_SOURCE_MSSQL_PORT", "4933"))
TEST_DB = "dq_source_test"


def _value(v: Any) -> Any:
    return v


def _ddl(kind: str) -> tuple[str, str]:
    text = {"postgresql": "TEXT", "mysql": "VARCHAR(255)", "mssql": "NVARCHAR(255)"}[kind]
    ts = {"postgresql": "TIMESTAMP", "mysql": "DATETIME", "mssql": "DATETIME2"}[kind]
    customers = (
        f"CREATE TABLE customers (customer_id INTEGER, email {text}, phone {text}, country {text}, "
        f"price DECIMAL(10,2), signup_date DATE, last_login {ts}, zip_code {text}, age_text {text}, code {text})"
    )
    orders = "CREATE TABLE orders (order_id INTEGER, customer_id INTEGER, amount DECIMAL(10,2))"
    return customers, orders


def _rows(table: str) -> tuple[list[str], list[tuple[Any, ...]]]:
    data = golden.rows() if table == "customers" else golden.orders()
    cols = list(data[0].keys())
    return cols, [tuple(_value(r[c]) for c in cols) for r in data]


def load_postgres() -> DbSource:
    import psycopg

    admin = admin_password()
    with psycopg.connect(
        host="127.0.0.1",
        port=PG_PORT,
        user="warehouse_admin",
        password=admin,
        dbname="warehouse",
        autocommit=True,
    ) as c:
        c.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
        c.execute(f"CREATE DATABASE {TEST_DB}")
        c.execute("DROP ROLE IF EXISTS dq_test_reader")
        c.execute(f"CREATE ROLE dq_test_reader LOGIN PASSWORD '{READER_PASSWORD}'")
    with psycopg.connect(
        host="127.0.0.1",
        port=PG_PORT,
        user="warehouse_admin",
        password=admin,
        dbname=TEST_DB,
        autocommit=True,
    ) as c:
        for ddl, table in zip(_ddl("postgresql"), ("customers", "orders"), strict=True):
            c.execute(ddl)
            cols, rows = _rows(table)
            with c.cursor() as cur:
                cur.executemany(
                    f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})",
                    rows,
                )
        c.execute("GRANT USAGE ON SCHEMA public TO dq_test_reader")
        c.execute("GRANT SELECT ON ALL TABLES IN SCHEMA public TO dq_test_reader")
    return DbSource("postgresql", "127.0.0.1", PG_PORT, TEST_DB, "dq_test_reader", READER_PASSWORD)


def load_mysql() -> DbSource:
    import pymysql

    admin = admin_password()
    c = pymysql.connect(
        host="127.0.0.1", port=MYSQL_PORT, user="root", password=admin, autocommit=True
    )
    try:
        with c.cursor() as cur:
            cur.execute(f"DROP DATABASE IF EXISTS {TEST_DB}")
            cur.execute(
                f"CREATE DATABASE {TEST_DB} CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci"
            )
            cur.execute("DROP USER IF EXISTS 'dq_test_reader'@'%'")
            cur.execute(f"CREATE USER 'dq_test_reader'@'%' IDENTIFIED BY '{READER_PASSWORD}'")
            cur.execute(f"GRANT SELECT ON {TEST_DB}.* TO 'dq_test_reader'@'%'")
            cur.execute(f"USE {TEST_DB}")
            for ddl, table in zip(_ddl("mysql"), ("customers", "orders"), strict=True):
                cur.execute(ddl)
                cols, rows = _rows(table)
                cur.executemany(
                    f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})",
                    rows,
                )
    finally:
        c.close()
    return DbSource("mysql", "127.0.0.1", MYSQL_PORT, TEST_DB, "dq_test_reader", READER_PASSWORD)


def mssql_available() -> bool:
    import socket

    with socket.socket() as s:
        s.settimeout(1)
        return s.connect_ex(("127.0.0.1", MSSQL_PORT)) == 0


def load_mssql() -> DbSource:
    import pymssql

    sa_password = (
        os.environ.get("DQ_MSSQL_SA_PASSWORD")
        or compose_env().get("DQ_MSSQL_SA_PASSWORD")
        or "Dq-Sql-Server-1"
    )
    c = pymssql.connect(
        server="127.0.0.1", port=str(MSSQL_PORT), user="sa", password=sa_password, autocommit=True
    )
    try:
        cur = c.cursor()
        cur.execute(
            f"IF DB_ID('{TEST_DB}') IS NOT NULL BEGIN ALTER DATABASE {TEST_DB} SET SINGLE_USER WITH ROLLBACK IMMEDIATE; DROP DATABASE {TEST_DB}; END"
        )
        cur.execute(f"CREATE DATABASE {TEST_DB}")
        cur.execute("IF SUSER_ID('dq_test_reader') IS NOT NULL DROP LOGIN dq_test_reader")
        cur.execute(
            f"CREATE LOGIN dq_test_reader WITH PASSWORD = '{READER_PASSWORD}', CHECK_POLICY = OFF"
        )
        cur.execute(f"USE {TEST_DB}")
        cur.execute("CREATE USER dq_test_reader FOR LOGIN dq_test_reader")
        cur.execute("ALTER ROLE db_datareader ADD MEMBER dq_test_reader")
        for ddl, table in zip(_ddl("mssql"), ("customers", "orders"), strict=True):
            cur.execute(ddl)
            cols, rows = _rows(table)
            cur.executemany(
                f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})",
                rows,
            )
    finally:
        c.close()
    return DbSource("mssql", "127.0.0.1", MSSQL_PORT, TEST_DB, "dq_test_reader", READER_PASSWORD)


def sqlite_file(path: Path) -> Path:
    path.unlink(missing_ok=True)
    c = sqlite3.connect(path)
    try:
        for table in ("customers", "orders"):
            ddl = _ddl("postgresql")[0 if table == "customers" else 1]
            c.execute(re.sub(r"\bTIMESTAMP\b", "DATETIME", ddl))
            cols, rows = _rows(table)

            def conv(v: Any) -> Any:
                if isinstance(v, dt.datetime):
                    return v.isoformat(sep=" ")
                if isinstance(v, dt.date):
                    return v.isoformat()
                return v

            c.executemany(
                f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(['?'] * len(cols))})",
                [tuple(conv(v) for v in r) for r in rows],
            )
        c.commit()
    finally:
        c.close()
    return path


def frame(table: str = "customers") -> pl.DataFrame:
    data = golden.rows() if table == "customers" else golden.orders()
    schema: dict[str, Any] = (
        {
            "customer_id": pl.Int64,
            "email": pl.String,
            "phone": pl.String,
            "country": pl.String,
            "price": pl.Float64,
            "signup_date": pl.Date,
            "last_login": pl.Datetime("us"),
            "zip_code": pl.String,
            "age_text": pl.String,
            "code": pl.String,
        }
        if table == "customers"
        else {"order_id": pl.Int64, "customer_id": pl.Int64, "amount": pl.Float64}
    )
    return pl.DataFrame(data, schema=schema, orient="row")


def write_files(directory: Path, table: str = "customers") -> dict[str, Path]:
    """The same rows as CSV, Excel, JSON (an array), NDJSON and Parquet."""
    df = frame(table)
    out = {
        "csv": directory / f"{table}.csv",
        "xlsx": directory / f"{table}.xlsx",
        "json": directory / f"{table}.json",
        "parquet": directory / f"{table}.parquet",
    }
    df.write_csv(out["csv"])
    df.write_excel(out["xlsx"], worksheet="customers")
    import json

    def conv(v: Any) -> Any:
        return v.isoformat() if isinstance(v, dt.date | dt.datetime) else v

    out["json"].write_text(
        json.dumps(
            [
                {k: conv(v) for k, v in r.items()}
                for r in (golden.rows() if table == "customers" else golden.orders())
            ]
        )
    )
    df.write_parquet(out["parquet"])
    return out


def all_formats() -> Iterable[str]:
    return ("csv", "xlsx", "json", "parquet")
