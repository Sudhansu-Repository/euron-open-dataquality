"""Turn a check into SQL: which rows it evaluates, and which of those fail.

Most checks become a pair of boolean expressions (``evaluated``, ``failed``) that the runner
folds into one aggregate query per dataset, so a table is scanned once however many checks
it has. Checks that need grouping, a second table or two statistical passes get a ``Plan``
kind the runner executes separately. Nothing here talks to a database.

Semantics shared by every source (``docs/architecture/checks.md``):

* NULL is never "invalid": validity checks evaluate present values only, and missing values
  are the completeness checks' business. For text, blank strings count as missing too, for
  ``type``, ``pattern``, ``accepted_values`` and ``format_consistency``.
* Text is compared exactly (case and trailing spaces matter) on every backend.
* Regexes match the whole value.
"""

from __future__ import annotations

import datetime as dt
import operator
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import sqlalchemy as sa
from sqlalchemy.sql.elements import ColumnElement

from dataquality.engine.dialects import (
    Exact,
    FullMatch,
    StrLen,
    as_text,
    blank,
    full_match,
    supports_regex,
)
from dataquality.engine.relation import NUMERIC, ColumnInfo, Relation
from dataquality.engine.spec import (
    AcceptedValuesParams,
    CheckSpec,
    CheckType,
    CompareParams,
    DuplicateRowsParams,
    LengthParams,
    NotNullParams,
    PatternParams,
    RangeParams,
    TypeParams,
    UniqueParams,
)
from dataquality.engine.sqlguard import check_predicate, check_read_only


class PlanKind(StrEnum):
    AGGREGATE = "aggregate"  # counted in the shared aggregate query
    PYTHON = "python"  # a regex on a source without regex: evaluated over streamed rows
    COUNT = "count"  # its own COUNT query (subqueries cannot sit inside SUM on SQL Server)
    GROUPS = "groups"  # unique and duplicate rows
    SHAPES = "shapes"  # format consistency
    OUTLIERS = "outliers"
    CUSTOM = "custom"
    DATASET = "dataset"  # schema, row count, freshness: judged once per dataset


class CheckCompileError(ValueError):
    """The check cannot run against this dataset (missing column, wrong type)."""


@dataclass
class Plan:
    spec: CheckSpec
    kind: PlanKind
    # Rows the check looks at (None: every row in the dataset filter).
    evaluated: ColumnElement[bool] | None = None
    failed: ColumnElement[bool] | None = None
    # PYTHON: the column to stream and the test a present value must pass.
    column: ColumnElement[Any] | None = None
    accept: Callable[[object], bool] | None = None
    # GROUPS: the key columns; SHAPES and OUTLIERS: the value expression.
    keys: list[tuple[str, ColumnElement[Any]]] = field(default_factory=list)
    value: ColumnElement[Any] | None = None
    # CUSTOM: the guarded SQL.
    sql: str | None = None


_OPS: dict[str, Callable[[Any, Any], Any]] = {
    "<": operator.lt,
    "<=": operator.le,
    "=": operator.eq,
    "!=": operator.ne,
    ">=": operator.ge,
    ">": operator.gt,
}


def _col(relation: Relation, name: str | None) -> tuple[ColumnInfo, ColumnElement[Any]]:
    if not name:
        raise CheckCompileError("this check needs a column")
    try:
        info = relation.column(name)
    except KeyError as exc:
        raise CheckCompileError(f"column {name!r} does not exist in {relation.display}") from exc
    return info, relation.c(info.name)


def exact(info: ColumnInfo, col: ColumnElement[Any]) -> ColumnElement[Any]:
    return Exact(col) if info.logical == "text" else col


def present(
    info: ColumnInfo, col: ColumnElement[Any], *, blank_is_missing: bool
) -> ColumnElement[bool]:
    cond: ColumnElement[bool] = col.is_not(None)
    if blank_is_missing and info.logical == "text":
        cond = sa.and_(cond, sa.not_(blank(col)))
    return cond


def _bound(info: ColumnInfo, value: object) -> object:
    """Bounds arrive as JSON; turn ISO strings into dates for date columns."""
    if isinstance(value, str) and info.logical in ("date", "datetime"):
        try:
            parsed = dt.datetime.fromisoformat(value)
        except ValueError as exc:
            raise CheckCompileError(f"{value!r} is not an ISO date") from exc
        return parsed.date() if info.logical == "date" and len(value) <= 10 else parsed
    if isinstance(value, str) and info.logical in NUMERIC:
        try:
            return float(value) if "." in value else int(value)
        except ValueError as exc:
            raise CheckCompileError(f"{value!r} is not a number") from exc
    return value


# A native column type already guarantees these logical types.
_SATISFIES: dict[str, set[str]] = {
    "integer": {"integer"},
    "decimal": {"integer", "decimal"},
    "boolean": {"boolean"},
    "date": {"date"},
    "datetime": {"datetime"},
    "uuid": {"uuid"},
}


def compile_check(spec: CheckSpec, relation: Relation, dialect: str) -> Plan:
    """The plan for one check; raises ``CheckCompileError`` when it cannot apply."""
    params = spec.parsed
    t = spec.type
    if t in (CheckType.SCHEMA, CheckType.ROW_COUNT):
        return Plan(spec, PlanKind.DATASET)
    if t == CheckType.FRESHNESS:
        info, col = _col(relation, spec.column)
        if info.logical not in ("date", "datetime", "text"):
            raise CheckCompileError(
                f"freshness needs a date or timestamp column, not {info.logical}"
            )
        return Plan(spec, PlanKind.DATASET, value=col)
    if t == CheckType.CUSTOM_SQL:
        sql = str(params.sql).replace("{table}", relation.sql_name)
        check_read_only(sql, dialect)
        return Plan(spec, PlanKind.CUSTOM, sql=sql.strip().rstrip(";"))
    if t == CheckType.DUPLICATE_ROWS:
        assert isinstance(params, DuplicateRowsParams)
        names = params.columns or [c.name for c in relation.columns if c.logical != "other"]
        keys = [(n, exact(*_col(relation, n))) for n in names]
        return Plan(spec, PlanKind.GROUPS, keys=keys)
    if t == CheckType.UNIQUE:
        assert isinstance(params, UniqueParams)
        names = [str(spec.column), *params.columns]
        pairs = [_col(relation, n) for n in names]
        keys = [(info.name, exact(info, col)) for info, col in pairs]
        return Plan(
            spec, PlanKind.GROUPS, keys=keys, evaluated=sa.and_(*[c.is_not(None) for _, c in pairs])
        )

    info, col = _col(relation, spec.column)
    if t == CheckType.NOT_NULL:
        assert isinstance(params, NotNullParams)
        failed = sa.not_(present(info, col, blank_is_missing=params.empty_is_null))
        return Plan(spec, PlanKind.AGGREGATE, failed=failed)
    if t == CheckType.RANGE:
        assert isinstance(params, RangeParams)
        if info.logical not in ("integer", "decimal", "date", "datetime", "text"):
            raise CheckCompileError(f"range does not apply to a {info.logical} column")
        parts = []
        if params.min is not None:
            low = _bound(info, params.min)
            parts.append(col < low if params.inclusive else col <= low)
        if params.max is not None:
            high = _bound(info, params.max)
            parts.append(col > high if params.inclusive else col >= high)
        return Plan(spec, PlanKind.AGGREGATE, evaluated=col.is_not(None), failed=sa.or_(*parts))
    if t == CheckType.LENGTH:
        assert isinstance(params, LengthParams)
        length = StrLen(col if info.logical == "text" else as_text(col, dialect))
        parts = []
        if params.min is not None:
            parts.append(length < params.min)
        if params.max is not None:
            parts.append(length > params.max)
        return Plan(spec, PlanKind.AGGREGATE, evaluated=col.is_not(None), failed=sa.or_(*parts))
    if t == CheckType.ACCEPTED_VALUES:
        assert isinstance(params, AcceptedValuesParams)
        evaluated = present(info, col, blank_is_missing=True)
        if info.logical == "text":
            values = [str(v) for v in params.values]
            if params.case_sensitive:
                inside = Exact(col).in_([Exact(sa.literal(v)) for v in values])
            else:
                inside = sa.func.lower(col).in_(sorted({v.lower() for v in values}))
        else:
            inside = col.in_([_bound(info, v) for v in params.values])
        return Plan(spec, PlanKind.AGGREGATE, evaluated=evaluated, failed=sa.not_(inside))
    if t == CheckType.COMPARE:
        assert isinstance(params, CompareParams)
        _, other = _col(relation, params.other)
        cond = _OPS[params.op](col, other)
        evaluated = sa.and_(col.is_not(None), other.is_not(None))
        return Plan(spec, PlanKind.AGGREGATE, evaluated=evaluated, failed=sa.not_(cond))
    if t in (CheckType.PATTERN, CheckType.TYPE):
        if t == CheckType.TYPE:
            assert isinstance(params, TypeParams)
            if info.logical in _SATISFIES[params.type]:
                # The column's own type guarantees it: nothing can fail.
                return Plan(spec, PlanKind.AGGREGATE, evaluated=col.is_not(None), failed=sa.false())
            pattern = params.pattern
        else:
            assert isinstance(params, PatternParams)
            pattern = params.pattern
        evaluated = present(info, col, blank_is_missing=True)
        text = col if info.logical == "text" else as_text(col, dialect)
        if not supports_regex(dialect):
            rx = re.compile(f"(?:{pattern})")
            return Plan(
                spec,
                PlanKind.PYTHON,
                evaluated=evaluated,
                column=text,
                accept=lambda v: rx.fullmatch(str(v)) is not None,
            )
        return Plan(
            spec, PlanKind.AGGREGATE, evaluated=evaluated, failed=sa.not_(full_match(text, pattern))
        )
    if t == CheckType.FORMAT_CONSISTENCY:
        evaluated = present(info, col, blank_is_missing=True)
        text = col if info.logical == "text" else as_text(col, dialect)
        return Plan(spec, PlanKind.SHAPES, evaluated=evaluated, value=text)
    if t == CheckType.OUTLIERS:
        if info.logical not in NUMERIC:
            raise CheckCompileError(f"outliers needs a numeric column, not {info.logical}")
        return Plan(
            spec, PlanKind.OUTLIERS, evaluated=col.is_not(None), value=sa.cast(col, sa.Float)
        )
    if t == CheckType.REFERENTIAL:
        return Plan(spec, PlanKind.COUNT, evaluated=col.is_not(None), value=col)
    raise CheckCompileError(f"unsupported check type {t}")


def filter_clause(sql: str | None, dialect: str) -> ColumnElement[bool] | None:
    """A user filter (``status = 'active'``), guarded to be a plain condition."""
    if not sql or not sql.strip():
        return None
    return sa.literal_column(f"({check_predicate(sql.strip(), dialect)})", sa.Boolean)


__all__ = [
    "CheckCompileError",
    "FullMatch",
    "Plan",
    "PlanKind",
    "compile_check",
    "exact",
    "filter_clause",
]
