"""The engine against in-process DuckDB and SQLite: the golden counts, errors, stopping,
and the Python path used for sources without regex (SQL Server)."""

from __future__ import annotations

import datetime as dt
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy.engine import Connection

from dataquality.engine.relation import Relation, query_relation, reflect_table
from dataquality.engine.runner import CheckRunner, Outcome, RunOptions, ScanStopped, jsonable
from dataquality.engine.spec import CheckSpec
from dataquality.sources.files import FileTable, open_files
from dataquality.sources.sql import SqlTarget, open_sql
from tests import golden, sources

NOW = dt.datetime.now(dt.UTC)


def specs() -> list[CheckSpec]:
    return [
        CheckSpec(key=c["name"], type=c["type"], column=c.get("column"), params=c.get("params", {}))
        for c in golden.CHECKS
    ]


@pytest.fixture(scope="module")
def files(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    base = tmp_path_factory.mktemp("files")
    out = sources.write_files(base)
    orders = base / "orders"
    orders.mkdir()
    out["orders"] = sources.write_files(orders, "orders")["parquet"]
    return out


@pytest.fixture(scope="module")
def duck(files: dict[str, Path]) -> Iterator[Connection]:
    tables = [
        FileTable("customers", files["parquet"], "parquet", {}),
        FileTable("orders", files["orders"], "parquet", {}),
    ]
    with open_files(tables) as c:
        yield c


@pytest.fixture(scope="module")
def lite(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Connection]:
    path = sources.sqlite_file(tmp_path_factory.mktemp("lite") / "g.sqlite")
    with open_sql(SqlTarget(kind="sqlite", sqlite_path=str(path)), 30) as c:
        yield c


def run(
    c: Connection, dialect: str, checks: list[CheckSpec], **options: object
) -> dict[str, Outcome]:
    relation = reflect_table(c, "customers")
    orders = reflect_table(c, "orders")
    runner = CheckRunner(
        c,
        dialect,
        relation,
        RunOptions(now=NOW, **options),  # type: ignore[arg-type]
        references=lambda name: (
            orders if name == "orders" else (relation if name == "customers" else None)
        ),
    )
    return {o.key: o for o in runner.run(checks)}


@pytest.mark.parametrize("backend", ["duckdb", "sqlite", "mssql-path"])
def test_golden_counts(duck: Connection, lite: Connection, backend: str) -> None:
    # "mssql-path": SQLite SQL, but the plans SQL Server gets (regex evaluated in Python).
    conn, dialect = (
        (duck, "duckdb")
        if backend == "duckdb"
        else (lite, "mssql" if backend == "mssql-path" else "sqlite")
    )
    got = run(conn, dialect, specs())
    for name, (status, evaluated, failed) in golden.EXPECTED.items():
        o = got[name]
        assert (o.status, o.evaluated, o.failed) == (status, evaluated, failed), (
            backend,
            name,
            o.message,
            o.error,
        )


def test_samples_are_bounded_and_masked(duck: Connection) -> None:
    got = run(duck, "duckdb", specs(), sample_size=3, masked=frozenset({"EMAIL"}))
    sample = got["email valid"].sample
    assert len(sample) == 3 and all(r["email"] == "[masked]" for r in sample)
    assert got["id unique"].sample[0]["copies"] == 2
    assert got["zip format"].observed["dominant_shape"] == "999999"
    assert got["price outliers"].observed["high"] > 1000


def test_referential_against_another_table(duck: Connection) -> None:
    relation = reflect_table(duck, "orders")
    customers = reflect_table(duck, "customers")
    check = CheckSpec(
        key="r",
        type="referential",
        column="customer_id",
        params={"dataset": "customers", "column": "customer_id"},
    )
    out = CheckRunner(
        duck, "duckdb", relation, RunOptions(), lambda n: customers if n == "customers" else None
    ).run([check])[0]
    assert (out.status, out.failed) == ("fail", golden.REFERENTIAL_FAILED)
    missing = CheckRunner(duck, "duckdb", relation, RunOptions(), lambda n: None).run([check])[0]
    assert missing.status == "error" and "same source" in (missing.error or "")


def test_errors_land_on_the_check_that_caused_them(duck: Connection) -> None:
    checks = [
        CheckSpec(key="ok", type="not_null", column="email"),
        CheckSpec(key="gone", type="not_null", column="nope"),
        CheckSpec(key="badfilter", type="not_null", column="email", filter="nope = 1"),
        CheckSpec(key="types", type="outliers", column="email"),
        CheckSpec(key="unsafe", type="custom_sql", params={"sql": "DELETE FROM {table}"}),
    ]
    got = run(duck, "duckdb", checks)
    assert got["ok"].failed == 8
    assert got["gone"].status == "error" and "does not exist" in (got["gone"].error or "")
    assert got["badfilter"].status == "error"
    assert got["types"].status == "error" and "numeric" in (got["types"].error or "")
    assert got["unsafe"].status == "error"


def test_dataset_filter_applies_to_every_check(duck: Connection) -> None:
    got = run(
        duck,
        "duckdb",
        [CheckSpec(key="n", type="not_null", column="email")],
        dataset_filter="country = 'GB'",
    )
    assert got["n"].evaluated == 49  # 50 GB rows, one carries a planted bad country


def test_stop_and_deadline(duck: Connection) -> None:
    with pytest.raises(ScanStopped):
        run(duck, "duckdb", specs(), should_stop=lambda: True)
    with pytest.raises(ScanStopped):
        run(duck, "duckdb", specs(), deadline=time.monotonic() - 1)


def test_query_relation_infers_types(lite: Connection) -> None:
    rel: Relation = query_relation(
        lite, "SELECT customer_id, price, email FROM customers WHERE country = 'US'", "sqlite"
    )
    assert [c.logical for c in rel.columns] == ["integer", "decimal", "text"]
    out = CheckRunner(lite, "sqlite", rel, RunOptions()).run(
        [CheckSpec(key="u", type="unique", column="customer_id")]
    )
    assert out[0].status == "fail" and out[0].failed == 2  # ids 101 and 121 are US and duplicated


def test_jsonable() -> None:
    assert jsonable(dt.date(2026, 1, 2)) == "2026-01-02"
    assert jsonable(b"\x00\x01") == "0x0001"
    assert jsonable(float("nan")) == "nan"
    assert jsonable("x" * 500).endswith("...")
