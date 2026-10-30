"""SQL building blocks whose spelling differs per database, compiled per dialect.

The check compiler only uses the elements below, so every check means the same thing on
PostgreSQL, MySQL, SQLite, SQL Server and DuckDB:

* ``FullMatch``: the whole value matches a portable regex. SQL Server has no regex, so the
  engine evaluates those checks in Python over a streamed column (``supports_regex``).
* ``StrLen``: length in characters.
* ``Shape``: letters to ``A``/``a`` and digits to ``9`` (see ``patterns.shape``).
* ``Exact``: a text value compared byte for byte. MySQL and SQL Server compare text with
  the column's collation, usually case-insensitive and trailing-space-insensitive, which
  would make ``"A"`` and ``"a"`` the same customer id.
* ``blank``: an empty or whitespace-only string.
"""

from __future__ import annotations

import string
from typing import Any

from sqlalchemy import String, cast, func, literal
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.functions import FunctionElement
from sqlalchemy.types import Boolean, Integer

from dataquality.engine.patterns import anchored

DIALECTS = ("postgresql", "mysql", "sqlite", "mssql", "duckdb")
_LOWER, _UPPER, _DIGITS = string.ascii_lowercase, string.ascii_uppercase, string.digits


def supports_regex(dialect: str) -> bool:
    return dialect != "mssql"


class FullMatch(FunctionElement[bool]):
    type = Boolean()
    inherit_cache = True
    name = "full_match"


def full_match(value: ColumnElement[Any], pattern: str) -> FullMatch:
    return FullMatch(value, literal(anchored(pattern)))


@compiles(FullMatch)
def _full_match_default(element: FullMatch, compiler: Any, **kw: Any) -> str:
    value, pattern = list(element.clauses)
    return f"({compiler.process(value, **kw)} ~ {compiler.process(pattern, **kw)})"


@compiles(FullMatch, "mysql")
def _full_match_mysql(element: FullMatch, compiler: Any, **kw: Any) -> str:
    value, pattern = list(element.clauses)
    # 'c': case-sensitive whatever the column's collation.
    return f"REGEXP_LIKE({compiler.process(value, **kw)}, {compiler.process(pattern, **kw)}, 'c')"


@compiles(FullMatch, "sqlite")
def _full_match_sqlite(element: FullMatch, compiler: Any, **kw: Any) -> str:
    value, pattern = list(element.clauses)
    # The engine registers REGEXP (Python re.search) on every SQLite connection.
    return f"({compiler.process(value, **kw)} REGEXP {compiler.process(pattern, **kw)})"


@compiles(FullMatch, "duckdb")
def _full_match_duckdb(element: FullMatch, compiler: Any, **kw: Any) -> str:
    value, pattern = list(element.clauses)
    return f"regexp_full_match({compiler.process(value, **kw)}, {compiler.process(pattern, **kw)})"


@compiles(FullMatch, "mssql")
def _full_match_mssql(element: FullMatch, compiler: Any, **kw: Any) -> str:
    raise NotImplementedError("SQL Server has no regex; the engine evaluates it in Python")


class StrLen(FunctionElement[int]):
    type = Integer()
    inherit_cache = True
    name = "str_len"


@compiles(StrLen)
def _len_default(element: StrLen, compiler: Any, **kw: Any) -> str:
    return f"length({compiler.process(element.clauses, **kw)})"


@compiles(StrLen, "postgresql")
@compiles(StrLen, "mysql")
def _len_char(element: StrLen, compiler: Any, **kw: Any) -> str:
    return f"char_length({compiler.process(element.clauses, **kw)})"


@compiles(StrLen, "mssql")
def _len_mssql(element: StrLen, compiler: Any, **kw: Any) -> str:
    # LEN ignores trailing spaces; appending one character and subtracting it does not.
    return f"(LEN({compiler.process(element.clauses, **kw)} + N'x') - 1)"


class Shape(FunctionElement[str]):
    type = String()
    inherit_cache = True
    name = "value_shape"


_FROM = _LOWER + _UPPER + _DIGITS
_TO = "a" * 26 + "A" * 26 + "9" * 10


@compiles(Shape)
def _shape_translate(element: Shape, compiler: Any, **kw: Any) -> str:
    return f"translate({compiler.process(element.clauses, **kw)}, '{_FROM}', '{_TO}')"


@compiles(Shape, "mssql")
def _shape_mssql(element: Shape, compiler: Any, **kw: Any) -> str:
    value = compiler.process(element.clauses, **kw)
    # A binary collation, or a case-insensitive one would map 'A' through 'a' first.
    return f"TRANSLATE({value} COLLATE Latin1_General_BIN2, '{_FROM}', '{_TO}')"


@compiles(Shape, "mysql")
def _shape_mysql(element: Shape, compiler: Any, **kw: Any) -> str:
    value = compiler.process(element.clauses, **kw)
    lower = f"REGEXP_REPLACE({value}, '[a-z]', 'a', 1, 0, 'c')"
    upper = f"REGEXP_REPLACE({lower}, '[A-Z]', 'A', 1, 0, 'c')"
    return f"REGEXP_REPLACE({upper}, '[0-9]', '9', 1, 0, 'c')"


@compiles(Shape, "sqlite")
def _shape_sqlite(element: Shape, compiler: Any, **kw: Any) -> str:
    # Registered on every SQLite connection (patterns.shape).
    return f"dq_shape({compiler.process(element.clauses, **kw)})"


class Exact(FunctionElement[str]):
    type = String()
    inherit_cache = True
    name = "exact_text"


@compiles(Exact)
def _exact_default(element: Exact, compiler: Any, **kw: Any) -> str:
    return str(compiler.process(element.clauses, **kw))


@compiles(Exact, "mysql")
def _exact_mysql(element: Exact, compiler: Any, **kw: Any) -> str:
    return f"CAST({compiler.process(element.clauses, **kw)} AS BINARY)"


@compiles(Exact, "mssql")
def _exact_mssql(element: Exact, compiler: Any, **kw: Any) -> str:
    # A binary collation: case-sensitive. SQL Server still ignores trailing spaces in '='
    # (ANSI padding, documented).
    return f"({compiler.process(element.clauses, **kw)} COLLATE Latin1_General_BIN2)"


def blank(value: ColumnElement[Any]) -> ColumnElement[bool]:
    """An empty or whitespace-only string. A plain comparison, not a function: SQL Server
    has no boolean values, so only a predicate can be negated or put in a CASE there."""
    return func.ltrim(func.rtrim(value)) == ""


def as_text(value: ColumnElement[Any], dialect: str) -> ColumnElement[Any]:
    """A value as text, for regex and shape checks on columns stored as numbers."""
    if dialect == "mssql":
        return cast(value, String(4000))
    return cast(value, String())
