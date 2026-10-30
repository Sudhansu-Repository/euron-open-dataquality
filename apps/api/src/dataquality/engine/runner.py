"""Run checks against an open source connection and return exact counts and samples.

Order of work for one dataset:

1. One aggregate query: the row count, plus ``COUNT(CASE ...)`` pairs (evaluated, failed)
   for every row-level check, plus ``MAX`` for freshness. One scan of the table.
2. One query per grouped, shape, outlier, reference or custom check.
3. Python-evaluated checks (regex on SQL Server): one streamed pass over the rows.
4. A bounded sample of failing rows for every failing check.

The connection is synchronous (the worker runs this in a thread); ``should_stop`` and the
deadline are checked between queries, and each query is bounded by the session's
statement timeout set when the connection was opened.
"""

from __future__ import annotations

import datetime as dt
import decimal
import math
import time
import uuid
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

import sqlalchemy as sa
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from sqlalchemy.sql.elements import ColumnElement

from dataquality.engine.compiler import (
    CheckCompileError,
    Plan,
    PlanKind,
    compile_check,
    exact,
    filter_clause,
)
from dataquality.engine.dialects import Exact, Shape
from dataquality.engine.relation import Relation
from dataquality.engine.spec import (
    CheckSpec,
    CheckType,
    FormatConsistencyParams,
    FreshnessParams,
    OutliersParams,
    ReferentialParams,
    RowCountParams,
    SchemaParams,
)
from dataquality.engine.sqlguard import UnsafeSqlError

Status = Literal["pass", "fail", "error"]
MASK = "[masked]"
MAX_TEXT = 200


class ScanStopped(Exception):  # noqa: N818 a signal, not a failure
    """The scan was cancelled or ran past its deadline."""


@dataclass
class Outcome:
    key: str
    type: CheckType
    status: Status
    evaluated: int = 0
    failed: int = 0
    observed: dict[str, Any] = field(default_factory=dict)
    sample: list[dict[str, Any]] = field(default_factory=list)
    message: str = ""
    error: str | None = None
    ms: float = 0.0

    @property
    def failed_pct(self) -> float:
        return 100.0 * self.failed / self.evaluated if self.evaluated else 0.0


@dataclass
class RunOptions:
    sample_size: int = 20
    masked: frozenset[str] = frozenset()
    now: dt.datetime = field(default_factory=lambda: dt.datetime.now(dt.UTC))
    deadline: float | None = None  # time.monotonic() value
    should_stop: Callable[[], bool] | None = None
    stream_batch: int = 10_000
    dataset_filter: str | None = None


def jsonable(value: object) -> object:
    """A sample value safe to store as JSON and show in a table."""
    if value is None or isinstance(value, bool | int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, decimal.Decimal):
        return str(value)
    if isinstance(value, dt.datetime | dt.date | dt.time):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, bytes | bytearray | memoryview):
        raw = bytes(value)
        return "0x" + raw[:32].hex() + ("..." if len(raw) > 32 else "")
    text = str(value)
    return text if len(text) <= MAX_TEXT else text[:MAX_TEXT] + "..."


def error_text(exc: BaseException) -> str:
    """The database's own message, first line, without bound parameters."""
    text = str(exc.orig) if isinstance(exc, DBAPIError) and exc.orig is not None else str(exc)
    return (text.strip().splitlines() or [type(exc).__name__])[0][:500]


def _count(cond: ColumnElement[bool] | None) -> ColumnElement[int]:
    if cond is None:
        return sa.func.count()
    return sa.func.count(sa.case((cond, 1)))


def _and(*parts: ColumnElement[bool] | None) -> ColumnElement[bool] | None:
    present = [p for p in parts if p is not None]
    if not present:
        return None
    return present[0] if len(present) == 1 else sa.and_(*present)


class CheckRunner:
    def __init__(
        self,
        conn: Connection,
        dialect: str,
        relation: Relation,
        options: RunOptions | None = None,
        references: Callable[[str], Relation | None] | None = None,
    ) -> None:
        self.conn = conn
        self.dialect = dialect
        self.relation = relation
        self.options = options or RunOptions()
        self.references = references or (lambda _ref: None)
        self.base = filter_clause(self.options.dataset_filter, dialect)
        self.row_count = 0

    # Helpers ---------------------------------------------------------------------------

    def _tick(self) -> None:
        o = self.options
        if o.should_stop and o.should_stop():
            raise ScanStopped("cancelled")
        if o.deadline is not None and time.monotonic() > o.deadline:
            raise ScanStopped("the scan ran past its time limit")

    def _where(self, *parts: ColumnElement[bool] | None) -> ColumnElement[bool] | None:
        return _and(self.base, *parts)

    def _select_rows(self, cond: ColumnElement[bool] | None) -> list[dict[str, Any]]:
        stmt = sa.select(*[self.relation.c(c.name) for c in self.relation.columns]).select_from(
            self.relation.from_
        )
        if cond is not None:
            stmt = stmt.where(cond)
        stmt = stmt.limit(self.options.sample_size)
        result = self.conn.execute(stmt)
        return [self._row(dict(zip(result.keys(), r, strict=True))) for r in result.fetchall()]

    def _row(self, row: dict[str, Any]) -> dict[str, Any]:
        masked = {m.lower() for m in self.options.masked}
        return {
            k: (MASK if k.lower() in masked and v is not None else jsonable(v))
            for k, v in row.items()
        }

    def _scalar_row(self, stmt: sa.Select[Any]) -> Sequence[Any]:
        self._tick()
        row = self.conn.execute(stmt).first()
        return tuple(row) if row is not None else ()

    # The run ---------------------------------------------------------------------------

    def run(self, checks: Iterable[CheckSpec]) -> list[Outcome]:
        plans: list[Plan] = []
        outcomes: dict[str, Outcome] = {}
        order: list[str] = []
        for spec in checks:
            order.append(spec.key)
            try:
                plans.append(compile_check(spec, self.relation, self.dialect))
            except (CheckCompileError, UnsafeSqlError, ValueError) as exc:
                outcomes[spec.key] = Outcome(
                    spec.key, spec.type, "error", error=str(exc), message=str(exc)
                )
        try:
            check_filters = {p.spec.key: filter_clause(p.spec.filter, self.dialect) for p in plans}
        except UnsafeSqlError as exc:
            # One bad filter: report it on its own check and drop that plan.
            check_filters = {}
            kept = []
            for p in plans:
                try:
                    check_filters[p.spec.key] = filter_clause(p.spec.filter, self.dialect)
                    kept.append(p)
                except UnsafeSqlError as one:
                    outcomes[p.spec.key] = Outcome(
                        p.spec.key, p.spec.type, "error", error=str(one), message=str(one)
                    )
            plans = kept
            del exc
        self._filters = check_filters
        self._aggregate(plans, outcomes)
        for plan in plans:
            if plan.spec.key in outcomes:
                continue
            started = time.perf_counter()
            try:
                self._tick()
                outcome = self._run_one(plan)
            except ScanStopped:
                raise
            except (SQLAlchemyError, ValueError, ArithmeticError) as exc:
                outcome = Outcome(
                    plan.spec.key,
                    plan.spec.type,
                    "error",
                    error=error_text(exc),
                    message="The check could not run: " + error_text(exc),
                )
            outcome.ms = round((time.perf_counter() - started) * 1000, 1)
            outcomes[plan.spec.key] = outcome
        self._python_pass([p for p in plans if p.kind == PlanKind.PYTHON], outcomes)
        return [outcomes[k] for k in order if k in outcomes]

    def _filter(self, plan: Plan) -> ColumnElement[bool] | None:
        return self._filters.get(plan.spec.key)

    def _aggregate(self, plans: list[Plan], outcomes: dict[str, Outcome]) -> None:
        """Row count and every aggregate count in one statement. If it fails (one check's
        filter references a missing column, say), each check is counted on its own so the
        error lands on the check that caused it."""
        self._agg: dict[str, tuple[int, int]] = {}
        self._max: dict[str, Any] = {}
        exprs: list[ColumnElement[Any]] = [_count(None).label("rows")]
        wanted: list[tuple[str, str, Plan]] = []
        for p in plans:
            if p.kind in (
                PlanKind.AGGREGATE,
                PlanKind.GROUPS,
                PlanKind.SHAPES,
                PlanKind.OUTLIERS,
                PlanKind.COUNT,
                PlanKind.PYTHON,
            ):
                ev = _and(self._filter(p), p.evaluated)
                exprs.append(_count(ev).label(f"e{len(wanted)}"))
                wanted.append(("e", p.spec.key, p))
                if p.kind == PlanKind.AGGREGATE:
                    exprs.append(_count(_and(ev, p.failed)).label(f"f{len(wanted)}"))
                    wanted.append(("f", p.spec.key, p))
            if p.spec.type == CheckType.FRESHNESS and p.value is not None:
                exprs.append(sa.func.max(p.value).label(f"m{len(wanted)}"))
                wanted.append(("m", p.spec.key, p))
        stmt = sa.select(*exprs).select_from(self.relation.from_)
        if self.base is not None:
            stmt = stmt.where(self.base)
        try:
            row = self._scalar_row(stmt)
            self.row_count = int(row[0] or 0)
            values = list(row[1:])
        except ScanStopped:
            raise
        except SQLAlchemyError as exc:
            # The row count itself failing (bad dataset filter) fails every check.
            try:
                total = sa.select(_count(None)).select_from(self.relation.from_)
                if self.base is not None:
                    total = total.where(self.base)
                self.row_count = int(self._scalar_row(total)[0] or 0)
            except SQLAlchemyError as base_exc:
                raise DatasetUnreadableError(error_text(base_exc)) from base_exc
            del exc
            values = []
            for kind, key, p in wanted:
                expr = exprs[len(values) + 1]
                one = sa.select(expr).select_from(self.relation.from_)
                if self.base is not None:
                    one = one.where(self.base)
                try:
                    values.append(self._scalar_row(one)[0])
                except SQLAlchemyError as one_exc:
                    values.append(None)
                    outcomes.setdefault(
                        key,
                        Outcome(
                            key,
                            p.spec.type,
                            "error",
                            error=error_text(one_exc),
                            message="The check could not run: " + error_text(one_exc),
                        ),
                    )
                del kind
        evaluated: dict[str, int] = {}
        failed: dict[str, int] = {}
        for (kind, key, _), value in zip(wanted, values, strict=True):
            if kind == "e":
                evaluated[key] = int(value or 0)
            elif kind == "f":
                failed[key] = int(value or 0)
            else:
                self._max[key] = value
        for name, count in evaluated.items():
            self._agg[name] = (count, failed.get(name, 0))

    def _judge(self, spec: CheckSpec, evaluated: int, failed: int, **extra: Any) -> Outcome:
        ok = spec.tolerance.allows(failed, evaluated)
        return Outcome(spec.key, spec.type, "pass" if ok else "fail", evaluated, failed, **extra)

    def _run_one(self, plan: Plan) -> Outcome:
        spec = plan.spec
        kind = plan.kind
        if kind == PlanKind.DATASET:
            return self._dataset_level(plan)
        if kind == PlanKind.AGGREGATE:
            evaluated, failed = self._agg.get(spec.key, (0, 0))
            out = self._judge(spec, evaluated, failed)
            if failed:
                out.sample = self._select_rows(
                    self._where(self._filter(plan), plan.evaluated, plan.failed)
                )
            out.message = _describe_rows(failed, evaluated, spec)
            return out
        if kind == PlanKind.GROUPS:
            return self._groups(plan)
        if kind == PlanKind.SHAPES:
            return self._shapes(plan)
        if kind == PlanKind.OUTLIERS:
            return self._outliers(plan)
        if kind == PlanKind.COUNT:
            return self._referential(plan)
        if kind == PlanKind.CUSTOM:
            return self._custom(plan)
        if kind == PlanKind.PYTHON:
            evaluated, _ = self._agg.get(spec.key, (0, 0))
            return Outcome(spec.key, spec.type, "pass", evaluated, 0)  # filled by _python_pass
        raise CheckCompileError(f"no executor for {kind}")

    # Dataset-level checks --------------------------------------------------------------

    def _dataset_level(self, plan: Plan) -> Outcome:
        spec = plan.spec
        params = spec.parsed
        if spec.type == CheckType.ROW_COUNT:
            assert isinstance(params, RowCountParams)
            n = self.row_count
            bad = (params.min is not None and n < params.min) or (
                params.max is not None and n > params.max
            )
            expected = _range_text(params.min, params.max)
            return Outcome(
                spec.key,
                spec.type,
                "fail" if bad else "pass",
                1,
                int(bad),
                observed={"row_count": n, "min": params.min, "max": params.max},
                message=f"{n:,} rows (expected {expected})",
            )
        if spec.type == CheckType.FRESHNESS:
            assert isinstance(params, FreshnessParams)
            newest = _as_datetime(self._max.get(spec.key))
            if newest is None:
                return Outcome(
                    spec.key,
                    spec.type,
                    "fail",
                    1,
                    1,
                    observed={"newest": None},
                    message="No timestamps at all, so the data cannot be fresh",
                )
            age_h = (self.options.now - newest).total_seconds() / 3600
            stale = age_h > params.max_age_hours
            return Outcome(
                spec.key,
                spec.type,
                "fail" if stale else "pass",
                1,
                int(stale),
                observed={
                    "newest": newest.isoformat(),
                    "age_hours": round(age_h, 2),
                    "max_age_hours": params.max_age_hours,
                },
                message=f"Newest value is {_age_text(age_h)} old (limit "
                f"{_age_text(params.max_age_hours)})",
            )
        assert isinstance(params, SchemaParams)
        problems = schema_problems(self.relation, params)
        evaluated = len(params.columns) + (0 if params.allow_extra else len(self.relation.columns))
        out = self._judge(spec, max(evaluated, 1), len(problems))
        out.sample = problems[: max(self.options.sample_size, 50)]
        out.observed = {
            "columns": [{"name": c.name, "type": c.logical} for c in self.relation.columns]
        }
        out.message = (
            "Schema matches"
            if not problems
            else f"{len(problems)} schema problem{'s' if len(problems) != 1 else ''}"
        )
        return out

    # Grouped checks --------------------------------------------------------------------

    def _groups(self, plan: Plan) -> Outcome:
        spec = plan.spec
        cond = self._where(self._filter(plan), plan.evaluated)
        keys = [expr for _, expr in plan.keys]
        n = sa.func.count().label("n")
        grouped = sa.select(*[k.label(f"k{i}") for i, k in enumerate(keys)], n).select_from(
            self.relation.from_
        )
        if cond is not None:
            grouped = grouped.where(cond)
        grouped = grouped.group_by(*keys).having(sa.func.count() > 1)
        sub = grouped.subquery("dups")
        extra, groups = self._scalar_row(
            sa.select(sa.func.coalesce(sa.func.sum(sub.c.n - 1), 0), sa.func.count()).select_from(
                sub
            )
        )
        evaluated = self._agg.get(spec.key, (0, 0))[0]
        failed = int(extra or 0)
        out = self._judge(spec, evaluated, failed, observed={"duplicate_groups": int(groups or 0)})
        if failed:
            display = [
                # Exact text is grouped by bytes: show one spelling; other types as they are.
                (sa.func.min(self.relation.c(name)) if isinstance(expr, Exact) else expr).label(
                    name
                )
                for name, expr in plan.keys
            ]
            top = sa.select(*display, sa.func.count().label("copies")).select_from(
                self.relation.from_
            )
            if cond is not None:
                top = top.where(cond)
            top = (
                top.group_by(*keys)
                .having(sa.func.count() > 1)
                .order_by(sa.func.count().desc(), *keys)
                .limit(self.options.sample_size)
            )
            self._tick()
            result = self.conn.execute(top)
            out.sample = [
                self._row(dict(zip(result.keys(), r, strict=True))) for r in result.fetchall()
            ]
        what = "row" if spec.type == CheckType.DUPLICATE_ROWS else "value"
        n_groups = int(groups or 0)
        out.message = (
            f"{failed:,} duplicate {what}{'s' if failed != 1 else ''} in {n_groups:,} "
            f"group{'s' if n_groups != 1 else ''}"
            if failed
            else f"No duplicate {what}s"
        )
        return out

    def _shapes(self, plan: Plan) -> Outcome:
        spec = plan.spec
        params = spec.parsed
        assert isinstance(params, FormatConsistencyParams) and plan.value is not None
        cond = self._where(self._filter(plan), plan.evaluated)
        shape = Shape(plan.value)
        top = sa.select(shape.label("shape"), sa.func.count().label("n")).select_from(
            self.relation.from_
        )
        if cond is not None:
            top = top.where(cond)
        top = top.group_by(shape).order_by(sa.func.count().desc(), shape).limit(5)
        self._tick()
        shapes = [(str(s), int(c)) for s, c in self.conn.execute(top).fetchall()]
        evaluated = self._agg.get(spec.key, (0, 0))[0]
        dominant, dominant_n = shapes[0] if shapes else ("", 0)
        failed = evaluated - dominant_n
        share = dominant_n / evaluated if evaluated else 1.0
        # The share is the threshold; a tolerance, when set, can only make it stricter.
        ok = share >= params.min_share and (
            (spec.tolerance.max_count is None and spec.tolerance.max_percent is None)
            or spec.tolerance.allows(failed, evaluated)
        )
        out = Outcome(
            spec.key,
            spec.type,
            "pass" if ok else "fail",
            evaluated,
            failed,
            observed={
                "dominant_shape": dominant,
                "share": round(share, 4),
                "shapes": [{"shape": s, "count": c} for s, c in shapes],
            },
        )
        if failed:
            out.sample = self._select_rows(self._where(cond, shape != dominant))
        out.message = f"{share:.1%} of values look like {dominant!r}" if shapes else "No values"
        return out

    def _outliers(self, plan: Plan) -> Outcome:
        spec = plan.spec
        params = spec.parsed
        assert isinstance(params, OutliersParams) and plan.value is not None
        x = plan.value
        cond = self._where(self._filter(plan), plan.evaluated)

        def scalar(expr: ColumnElement[Any], extra: ColumnElement[bool] | None = None) -> Any:
            stmt = sa.select(expr).select_from(self.relation.from_)
            where = _and(cond, extra)
            if where is not None:
                stmt = stmt.where(where)
            return self._scalar_row(stmt)[0]

        mean = scalar(sa.func.avg(x))
        evaluated = self._agg.get(spec.key, (0, 0))[0]
        if mean is None or evaluated < 2:
            return Outcome(
                spec.key,
                spec.type,
                "pass",
                evaluated,
                0,
                message="Not enough values for statistics",
            )
        mean = float(mean)
        # Two passes: the variance around the mean is numerically stable, unlike
        # avg(x*x) - avg(x)^2, which loses everything on large values.
        var = float(scalar(sa.func.avg((x - mean) * (x - mean))) or 0.0)
        sd = math.sqrt(var)
        limit = params.z * sd
        observed = {
            "mean": round(mean, 6),
            "stddev": round(sd, 6),
            "z": params.z,
            "low": round(mean - limit, 6),
            "high": round(mean + limit, 6),
        }
        if sd == 0:
            return Outcome(
                spec.key,
                spec.type,
                "pass",
                evaluated,
                0,
                observed=observed,
                message="Every value is the same",
            )
        outside = sa.or_(x < mean - limit, x > mean + limit)
        failed = int(scalar(sa.func.count(), outside) or 0)
        out = self._judge(spec, evaluated, failed, observed=observed)
        if failed:
            out.sample = self._select_rows(self._where(cond, outside))
        out.message = (
            f"{failed:,} values outside {mean - limit:,.4g} to "
            f"{mean + limit:,.4g} (mean {mean:,.4g}, {params.z:g} standard deviations)"
        )
        return out

    def _referential(self, plan: Plan) -> Outcome:
        spec = plan.spec
        params = spec.parsed
        assert isinstance(params, ReferentialParams) and plan.value is not None
        ref = self.references(params.dataset)
        if ref is None:
            raise CheckCompileError(
                f"reference dataset {params.dataset!r} is not in the same source, so it "
                f"cannot be joined"
            )
        if not ref.has(params.column):
            raise CheckCompileError(f"column {params.column!r} does not exist in {ref.display}")
        r = ref.from_.alias("ref")
        rinfo = ref.column(params.column)
        here = self.relation.column(str(spec.column))
        missing = ~sa.exists(
            sa.select(sa.literal(1))
            .select_from(r)
            .where(exact(rinfo, r.c[rinfo.name]) == exact(here, plan.value))
        )
        cond = self._where(self._filter(plan), plan.evaluated)
        stmt = sa.select(sa.func.count()).select_from(self.relation.from_).where(missing)
        if cond is not None:
            stmt = stmt.where(cond)
        failed = int(self._scalar_row(stmt)[0] or 0)
        evaluated = self._agg.get(spec.key, (0, 0))[0]
        out = self._judge(spec, evaluated, failed, observed={"reference": ref.display})
        if failed:
            out.sample = self._select_rows(_and(cond, missing))
        out.message = (
            f"{failed:,} values have no match in {ref.display}.{rinfo.name}"
            if failed
            else f"Every value exists in {ref.display}"
        )
        return out

    def _custom(self, plan: Plan) -> Outcome:
        spec = plan.spec
        assert plan.sql is not None
        sub = sa.text(plan.sql).columns().subquery("custom")
        failed = int(self._scalar_row(sa.select(sa.func.count()).select_from(sub))[0] or 0)
        out = self._judge(spec, self.row_count, failed)
        if failed:
            self._tick()
            result = self.conn.execute(
                sa.select(sa.text("*")).select_from(sub).limit(self.options.sample_size)
            )
            out.sample = [
                self._row(dict(zip(result.keys(), r, strict=True))) for r in result.fetchall()
            ]
        out.message = (
            f"{failed:,} rows returned by the query" if failed else "The query returned no rows"
        )
        return out

    # Python-evaluated checks -----------------------------------------------------------

    def _python_pass(self, plans: list[Plan], outcomes: dict[str, Outcome]) -> None:
        """One streamed pass for every regex check on a source without regex support. The
        evaluated condition stays in SQL; only the match itself runs here."""
        plans = [
            p for p in plans if outcomes.get(p.spec.key) and outcomes[p.spec.key].status != "error"
        ]
        if not plans:
            return
        cols = [self.relation.c(c.name) for c in self.relation.columns]
        extra = []
        for i, p in enumerate(plans):
            ev = _and(self._filter(p), p.evaluated)
            extra.append(
                sa.case((ev, 1), else_=0).label(f"_e{i}")
                if ev is not None
                else sa.literal(1).label(f"_e{i}")
            )
            assert p.column is not None
            extra.append(p.column.label(f"_v{i}"))
        stmt = sa.select(*cols, *extra).select_from(self.relation.from_)
        if self.base is not None:
            stmt = stmt.where(self.base)
        names = [c.name for c in self.relation.columns]
        failed = [0] * len(plans)
        samples: list[list[dict[str, Any]]] = [[] for _ in plans]
        size = self.options.sample_size
        result = self.conn.execution_options(
            stream_results=True, yield_per=self.options.stream_batch
        ).execute(stmt)
        width = len(names)
        seen = 0
        for row in result:
            seen += 1
            if seen % self.options.stream_batch == 0:
                self._tick()
            for i, p in enumerate(plans):
                if not row[width + 2 * i]:
                    continue
                value = row[width + 2 * i + 1]
                assert p.accept is not None
                if not p.accept(value):
                    failed[i] += 1
                    if len(samples[i]) < size:
                        samples[i].append(self._row(dict(zip(names, row[:width], strict=True))))
        for i, p in enumerate(plans):
            evaluated = self._agg.get(p.spec.key, (0, 0))[0]
            out = self._judge(p.spec, evaluated, failed[i])
            out.sample = samples[i]
            out.message = _describe_rows(failed[i], evaluated, p.spec)
            out.ms = outcomes[p.spec.key].ms
            outcomes[p.spec.key] = out


class DatasetUnreadableError(Exception):
    """The dataset itself cannot be read (the table is gone, the filter is broken)."""


def schema_problems(relation: Relation, params: SchemaParams) -> list[dict[str, Any]]:
    actual = {c.name.lower(): c for c in relation.columns}
    problems: list[dict[str, Any]] = []
    expected_names = set()
    for exp in params.columns:
        expected_names.add(exp.name.lower())
        col = actual.get(exp.name.lower())
        if col is None:
            if exp.required:
                problems.append(
                    {"column": exp.name, "problem": "missing", "expected": exp.type, "actual": None}
                )
            continue
        if exp.type != "any" and not type_compatible(exp.type, col.logical):
            problems.append(
                {"column": col.name, "problem": "type", "expected": exp.type, "actual": col.logical}
            )
    if not params.allow_extra:
        for name, col in actual.items():
            if name not in expected_names:
                problems.append(
                    {
                        "column": col.name,
                        "problem": "unexpected",
                        "expected": None,
                        "actual": col.logical,
                    }
                )
    return problems


def type_compatible(expected: str, actual: str) -> bool:
    """Whether a column of type ``actual`` satisfies ``expected``. Booleans are integers
    in MySQL and SQLite, UUIDs are text outside PostgreSQL and SQL Server, and integers
    are decimals."""
    if expected == actual:
        return True
    return (expected, actual) in {
        ("decimal", "integer"),
        ("boolean", "integer"),
        ("uuid", "text"),
    }


def _as_datetime(value: object) -> dt.datetime | None:
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        return value if value.tzinfo else value.replace(tzinfo=dt.UTC)
    if isinstance(value, dt.date):
        return dt.datetime(value.year, value.month, value.day, tzinfo=dt.UTC)
    try:
        parsed = dt.datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.UTC)


def _age_text(hours: float) -> str:
    if hours < 1:
        return f"{max(hours * 60, 0):.0f} minutes"
    if hours < 48:
        return f"{hours:.1f} hours"
    return f"{hours / 24:.1f} days"


def _range_text(low: int | None, high: int | None) -> str:
    if low is not None and high is not None:
        return f"{low:,} to {high:,}"
    return f"at least {low:,}" if low is not None else f"at most {high:,}"


def _describe_rows(failed: int, evaluated: int, spec: CheckSpec) -> str:
    if not failed:
        return f"All {evaluated:,} rows pass"
    share = 100.0 * failed / evaluated if evaluated else 0.0
    return f"{failed:,} of {evaluated:,} rows fail ({share:.2f}%)"
