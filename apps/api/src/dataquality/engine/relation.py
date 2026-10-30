"""A dataset as the engine sees it: something to SELECT from, with typed columns.

A relation is a table or view (reflected from the source), a read-only query (wrapped as a
subquery, its column types inferred from a sample of rows), or a file that the worker loaded
into DuckDB (a table there). The engine never needs to know which.
"""

from __future__ import annotations

import datetime as dt
import decimal
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

import sqlalchemy as sa
from sqlalchemy import types as sat
from sqlalchemy.engine import Connection
from sqlalchemy.sql.expression import FromClause

from dataquality.engine.sqlguard import check_read_only

Logical = Literal["integer", "decimal", "boolean", "date", "datetime", "text", "uuid", "other"]
NUMERIC: frozenset[str] = frozenset({"integer", "decimal"})
TEMPORAL: frozenset[str] = frozenset({"date", "datetime"})
ORDERED: frozenset[str] = NUMERIC | TEMPORAL | {"text"}


@dataclass(frozen=True)
class ColumnInfo:
    name: str
    logical: Logical
    native: str
    nullable: bool = True


@dataclass
class Relation:
    """``from_`` is the FROM clause; ``display`` names it for people."""

    display: str
    from_: FromClause
    columns: list[ColumnInfo] = field(default_factory=list)
    # Plain SQL name to substitute for {table} in custom checks.
    sql_name: str = ""

    def column(self, name: str) -> ColumnInfo:
        for col in self.columns:
            if col.name == name:
                return col
        lowered = [c for c in self.columns if c.name.lower() == name.lower()]
        if len(lowered) == 1:
            return lowered[0]
        raise KeyError(name)

    def has(self, name: str) -> bool:
        try:
            self.column(name)
        except KeyError:
            return False
        return True

    def c(self, name: str) -> sa.ColumnElement[Any]:
        return self.from_.c[self.column(name).name]


def logical_of(t: sat.TypeEngine[Any]) -> Logical:
    """Map a reflected SQLAlchemy type to the engine's logical type."""
    name = type(t).__name__.upper()
    if "UUID" in name or "UNIQUEIDENTIFIER" in name:
        return "uuid"
    if isinstance(t, sat.Boolean) or name in ("BIT", "BOOL"):
        return "boolean"
    if isinstance(t, sat.Integer):
        return "integer"
    if isinstance(t, sat.Numeric | sat.Float):
        if isinstance(t, sat.Numeric) and not isinstance(t, sat.Float) and t.scale == 0:
            return "integer"
        return "decimal"
    if isinstance(t, sat.DateTime) or "TIMESTAMP" in name or "DATETIME" in name:
        return "datetime"
    if isinstance(t, sat.Date):
        return "date"
    if isinstance(t, sat.String | sat.Enum) or name in ("TEXT", "NTEXT", "CITEXT"):
        return "text"
    return "other"


def logical_of_value(v: object) -> Logical | None:
    if v is None:
        return None
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, int):
        return "integer"
    if isinstance(v, float | decimal.Decimal):
        return "decimal"
    if isinstance(v, dt.datetime):
        return "datetime"
    if isinstance(v, dt.date):
        return "date"
    if isinstance(v, uuid.UUID):
        return "uuid"
    if isinstance(v, str):
        return "text"
    return "other"


def duckdb_logical(native: str) -> Logical:
    t = native.upper()
    if t.startswith(
        (
            "TINYINT",
            "SMALLINT",
            "INTEGER",
            "BIGINT",
            "HUGEINT",
            "UTINYINT",
            "USMALLINT",
            "UINTEGER",
            "UBIGINT",
        )
    ):
        return "integer"
    if t.startswith(("DECIMAL", "DOUBLE", "FLOAT", "REAL", "NUMERIC")):
        return "integer" if t.startswith("DECIMAL") and t.endswith(",0)") else "decimal"
    if t.startswith("BOOLEAN"):
        return "boolean"
    if t.startswith("TIMESTAMP"):
        return "datetime"
    if t == "DATE":
        return "date"
    if t == "UUID":
        return "uuid"
    if t.startswith("VARCHAR") or t in ("TEXT", "STRING"):
        return "text"
    return "other"


def _duckdb_columns(conn: Connection, name: str, schema: str | None) -> list[ColumnInfo]:
    # duckdb-engine's reflection queries catalog tables DuckDB does not have; its own
    # information_schema is exact and cheap.
    rows = conn.execute(
        sa.text(
            "SELECT column_name, data_type, is_nullable FROM information_schema.columns "
            "WHERE table_name = :t AND table_schema = :s ORDER BY ordinal_position"
        ),
        {"t": name, "s": schema or "main"},
    ).all()
    return [
        ColumnInfo(
            name=str(r[0]),
            logical=duckdb_logical(str(r[1])),
            native=str(r[1]),
            nullable=r[2] == "YES",
        )
        for r in rows
    ]


def reflect_table(conn: Connection, name: str, schema: str | None = None) -> Relation:
    if conn.dialect.name == "duckdb":
        cols = _duckdb_columns(conn, name, schema)
    else:
        cols = [
            ColumnInfo(
                name=str(c["name"]),
                logical=logical_of(c["type"]),
                native=str(c["type"]),
                nullable=bool(c.get("nullable", True)),
            )
            for c in sa.inspect(conn).get_columns(name, schema=schema)
        ]
    if not cols:
        raise LookupError(f"table {name!r} was not found or has no columns")
    table = sa.table(name, *[sa.column(c.name) for c in cols], schema=schema)
    preparer = conn.dialect.identifier_preparer
    sql_name = preparer.quote(name)
    if schema is not None:
        sql_name = f"{preparer.quote_schema(schema)}.{sql_name}"
    return Relation(
        display=f"{schema}.{name}" if schema else name,
        from_=table,
        columns=cols,
        sql_name=sql_name,
    )


def query_relation(conn: Connection, sql: str, dialect: str, sample_rows: int = 500) -> Relation:
    """A read-only query as a relation; column types come from a sample of its rows."""
    check_read_only(sql, dialect)
    body = sql.strip().rstrip(";")
    probe = sa.select(sa.text("*")).select_from(sa.text(f"({body}) AS q")).limit(sample_rows)
    result = conn.execute(probe)
    names = list(result.keys())
    rows = result.fetchall()
    cols = []
    for i, name in enumerate(names):
        kinds = {logical_of_value(r[i]) for r in rows} - {None}
        logical: Logical
        if len(kinds) == 1:
            logical = kinds.pop() or "other"
        elif kinds == {"integer", "decimal"}:
            logical = "decimal"
        else:
            logical = "text" if not kinds else "other"
        cols.append(ColumnInfo(name=name, logical=logical, native=logical))
    table = sa.text(body).columns(*[sa.column(n) for n in names]).subquery("q")
    return Relation(display="query", from_=table, columns=cols, sql_name=f"({body}) AS q")


def column_names(relation: Relation) -> Sequence[str]:
    return [c.name for c in relation.columns]
