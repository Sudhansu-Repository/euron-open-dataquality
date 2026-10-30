"""Profile a dataset: what each column holds, computed in the source.

Per column: counts (rows, nulls, blanks, distinct), min and max, mean and standard
deviation, quantiles (nearest rank, so every backend returns an actual value of the column),
a 10 bin histogram, the most common values, the most common value shapes, text lengths and
semantic hints (the share of values that look like emails, phones, dates, numbers...).

Cost: one aggregate query for the counts of every column, one for the variances, one for
the histograms, and one group-by per column for top values and shapes. Very large datasets
are profiled over their first ``max_rows`` rows (reported as ``sampled``); checks are always
exact over every row.
"""

from __future__ import annotations

import math
import random
import re
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import Connection
from sqlalchemy.sql.elements import ColumnElement

from dataquality.engine.compiler import exact, filter_clause
from dataquality.engine.dialects import Shape, StrLen, as_text, blank, full_match, supports_regex
from dataquality.engine.patterns import PRESETS, TYPE_PATTERNS
from dataquality.engine.relation import NUMERIC, ORDERED, ColumnInfo, Relation
from dataquality.engine.runner import ScanStopped, jsonable

QUANTILES = (0.05, 0.25, 0.5, 0.75, 0.95)
SEMANTIC_ROWS = 20_000
SEMANTIC = {
    "email": PRESETS["email"].regex,
    "phone": PRESETS["phone_e164"].regex + "|" + PRESETS["phone_in"].regex,
    "url": PRESETS["url"].regex,
    "uuid": PRESETS["uuid"].regex,
    "date": TYPE_PATTERNS["date"],
    "datetime": TYPE_PATTERNS["datetime"],
    "integer": TYPE_PATTERNS["integer"],
    "decimal": TYPE_PATTERNS["decimal"],
    "boolean": TYPE_PATTERNS["boolean"],
}


@dataclass
class ColumnProfile:
    name: str
    logical: str
    native: str
    rows: int = 0
    nulls: int = 0
    blanks: int = 0
    distinct: int | None = None
    min: Any = None
    max: Any = None
    mean: float | None = None
    stddev: float | None = None
    quantiles: dict[str, Any] = field(default_factory=dict)
    histogram: list[dict[str, Any]] = field(default_factory=list)
    top_values: list[dict[str, Any]] = field(default_factory=list)
    shapes: list[dict[str, Any]] = field(default_factory=list)
    min_length: int | None = None
    max_length: int | None = None
    mean_length: float | None = None
    semantic: dict[str, float] = field(default_factory=dict)

    @property
    def present(self) -> int:
        return self.rows - self.nulls

    @property
    def null_rate(self) -> float:
        return self.nulls / self.rows if self.rows else 0.0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DatasetProfile:
    row_count: int
    rows_profiled: int
    sampled: bool
    columns: list[ColumnProfile]
    ms: float = 0.0


class Profiler:
    def __init__(
        self,
        conn: Connection,
        dialect: str,
        relation: Relation,
        *,
        max_rows: int = 5_000_000,
        top_n: int = 10,
        masked: frozenset[str] = frozenset(),
        dataset_filter: str | None = None,
        should_stop: Callable[[], bool] | None = None,
    ) -> None:
        self.conn = conn
        self.dialect = dialect
        self.relation = relation
        self.max_rows = max_rows
        self.top_n = top_n
        self.masked = {m.lower() for m in masked}
        self.base = filter_clause(dataset_filter, dialect)
        self.should_stop = should_stop

    def _tick(self) -> None:
        if self.should_stop and self.should_stop():
            raise ScanStopped("cancelled")

    def _scalar_row(self, stmt: Any) -> tuple[Any, ...]:
        self._tick()
        row = self.conn.execute(stmt).first()
        return tuple(row) if row is not None else ()

    def run(self) -> DatasetProfile:
        started = time.perf_counter()
        total_stmt = sa.select(sa.func.count()).select_from(self.relation.from_)
        if self.base is not None:
            total_stmt = total_stmt.where(self.base)
        total = int(self._scalar_row(total_stmt)[0] or 0)
        source: sa.FromClause = self.relation.from_
        sampled = total > self.max_rows
        cols = {c.name: self.relation.c(c.name) for c in self.relation.columns}
        if sampled or self.base is not None:
            inner = sa.select(*cols.values()).select_from(self.relation.from_)
            if self.base is not None:
                inner = inner.where(self.base)
            if sampled:
                inner = inner.limit(self.max_rows)
            source = inner.subquery("p")
            cols = {name: source.c[name] for name in cols}
        rows = min(total, self.max_rows)
        profiles = [
            ColumnProfile(c.name, c.logical, c.native, rows=rows) for c in self.relation.columns
        ]
        infos = {c.name: c for c in self.relation.columns}
        self._counts(source, cols, infos, profiles)
        self._variance(source, cols, infos, profiles)
        self._quantiles(source, cols, infos, profiles)
        self._histograms(source, cols, infos, profiles)
        for p in profiles:
            self._top(source, cols[p.name], infos[p.name], p)
        self._semantic(source, cols, infos, profiles)
        for p in profiles:
            if p.name.lower() in self.masked:
                p.top_values = [{"value": "[masked]", "count": v["count"]} for v in p.top_values]
                p.min = p.max = "[masked]" if p.min is not None else None
                p.quantiles = {}
        return DatasetProfile(
            total, rows, sampled, profiles, round((time.perf_counter() - started) * 1000, 1)
        )

    def _counts(
        self,
        source: sa.FromClause,
        cols: dict[str, ColumnElement[Any]],
        infos: dict[str, ColumnInfo],
        profiles: list[ColumnProfile],
    ) -> None:
        exprs: list[ColumnElement[Any]] = []
        slots: list[tuple[ColumnProfile, str]] = []
        for p in profiles:
            info, col = infos[p.name], cols[p.name]
            exprs.append(sa.func.count(col))
            slots.append((p, "present"))
            if info.logical != "other":
                exprs.append(sa.func.count(sa.distinct(exact(info, col))))
                slots.append((p, "distinct"))
            if info.logical in ORDERED:
                exprs += [sa.func.min(col), sa.func.max(col)]
                slots += [(p, "min"), (p, "max")]
            if info.logical in NUMERIC:
                exprs.append(sa.func.avg(sa.cast(col, sa.Float)))
                slots.append((p, "mean"))
            if info.logical == "text":
                length = StrLen(col)
                exprs += [
                    sa.func.count(sa.case((blank(col), 1))),
                    sa.func.min(length),
                    sa.func.max(length),
                    sa.func.avg(sa.cast(length, sa.Float)),
                ]
                slots += [(p, "blanks"), (p, "min_length"), (p, "max_length"), (p, "mean_length")]
        if not exprs:
            return
        values = self._scalar_row(sa.select(*exprs).select_from(source))
        for (p, attr), value in zip(slots, values, strict=True):
            if attr == "present":
                p.nulls = p.rows - int(value or 0)
            elif attr in ("distinct", "blanks", "min_length", "max_length"):
                setattr(p, attr, int(value) if value is not None else None)
            elif attr in ("mean", "mean_length"):
                setattr(p, attr, round(float(value), 6) if value is not None else None)
            else:
                setattr(p, attr, jsonable(value))
        for p in profiles:
            if p.blanks is None:
                p.blanks = 0

    def _variance(
        self,
        source: sa.FromClause,
        cols: dict[str, ColumnElement[Any]],
        infos: dict[str, ColumnInfo],
        profiles: list[ColumnProfile],
    ) -> None:
        numeric = [p for p in profiles if infos[p.name].logical in NUMERIC and p.mean is not None]
        if not numeric:
            return
        exprs = []
        for p in numeric:
            x = sa.cast(cols[p.name], sa.Float)
            exprs.append(sa.func.avg((x - p.mean) * (x - p.mean)))
        for p, var in zip(
            numeric, self._scalar_row(sa.select(*exprs).select_from(source)), strict=True
        ):
            p.stddev = round(math.sqrt(max(float(var or 0.0), 0.0)), 6)

    def _quantiles(
        self,
        source: sa.FromClause,
        cols: dict[str, ColumnElement[Any]],
        infos: dict[str, ColumnInfo],
        profiles: list[ColumnProfile],
    ) -> None:
        """Nearest rank: the value at position ceil(q * n) in sorted order. PostgreSQL and
        DuckDB have it built in (percentile_disc); elsewhere one ORDER BY ... OFFSET each."""
        numeric = [p for p in profiles if infos[p.name].logical in NUMERIC and p.present > 0]
        if not numeric:
            return
        if self.dialect in ("postgresql", "duckdb"):
            exprs = [
                sa.func.percentile_disc(q).within_group(cols[p.name])
                for p in numeric
                for q in QUANTILES
            ]
            values = list(self._scalar_row(sa.select(*exprs).select_from(source)))
            for p in numeric:
                p.quantiles = {f"p{round(q * 100)}": jsonable(values.pop(0)) for q in QUANTILES}
            return
        for p in numeric:
            col = cols[p.name]
            for q in QUANTILES:
                offset = max(math.ceil(q * p.present) - 1, 0)
                stmt = (
                    sa.select(col)
                    .select_from(source)
                    .where(col.is_not(None))
                    .order_by(col)
                    .offset(offset)
                    .limit(1)
                )
                row = self._scalar_row(stmt)
                p.quantiles[f"p{round(q * 100)}"] = jsonable(row[0]) if row else None

    def _histograms(
        self,
        source: sa.FromClause,
        cols: dict[str, ColumnElement[Any]],
        infos: dict[str, ColumnInfo],
        profiles: list[ColumnProfile],
    ) -> None:
        # min and max are already JSON-safe here (decimals as strings).
        numeric = [
            p
            for p in profiles
            if infos[p.name].logical in NUMERIC and p.min is not None and p.max is not None
        ]
        exprs = []
        edges: dict[str, list[float]] = {}
        for p in numeric:
            low, high = float(p.min), float(p.max)
            if high <= low:
                continue
            width = (high - low) / 10
            bounds = [low + i * width for i in range(11)]
            edges[p.name] = bounds
            x = sa.cast(cols[p.name], sa.Float)
            for i in range(10):
                upper = x <= bounds[i + 1] if i == 9 else x < bounds[i + 1]
                exprs.append(sa.func.count(sa.case((sa.and_(x >= bounds[i], upper), 1))))
        if not exprs:
            return
        values = list(self._scalar_row(sa.select(*exprs).select_from(source)))
        for p in numeric:
            if p.name not in edges:
                continue
            b = edges[p.name]
            p.histogram = [
                {
                    "low": round(b[i], 6),
                    "high": round(b[i + 1], 6),
                    "count": int(values.pop(0) or 0),
                }
                for i in range(10)
            ]

    def _top(
        self, source: sa.FromClause, col: ColumnElement[Any], info: ColumnInfo, p: ColumnProfile
    ) -> None:
        if info.logical == "other" or p.present == 0:
            return
        if p.distinct is not None and p.distinct == p.present and p.present > self.top_n:
            return  # every value is unique: a top list says nothing
        key = exact(info, col)
        stmt = (
            # Text is grouped by its exact bytes, so show one spelling of it; anything else
            # is grouped by itself (and min() does not exist for every type, booleans say).
            sa.select(sa.func.min(col) if info.logical == "text" else key, sa.func.count())
            .select_from(source)
            .where(col.is_not(None))
            .group_by(key)
            .order_by(sa.func.count().desc(), key)
            .limit(self.top_n)
        )
        self._tick()
        p.top_values = [
            {"value": jsonable(v), "count": int(n)} for v, n in self.conn.execute(stmt).fetchall()
        ]
        if info.logical != "text":
            return
        shape = Shape(col)
        stmt = (
            sa.select(shape, sa.func.count())
            .select_from(source)
            .where(sa.and_(col.is_not(None), sa.not_(blank(col))))
            .group_by(shape)
            .order_by(sa.func.count().desc(), shape)
            .limit(5)
        )
        self._tick()
        p.shapes = [
            {"shape": str(s)[:80], "count": int(n)} for s, n in self.conn.execute(stmt).fetchall()
        ]

    def _semantic(
        self,
        source: sa.FromClause,
        cols: dict[str, ColumnElement[Any]],
        infos: dict[str, ColumnInfo],
        profiles: list[ColumnProfile],
    ) -> None:
        """For text columns: the share of present values matching each semantic pattern,
        over the first ``SEMANTIC_ROWS`` rows. These are hints for suggestions, and nine
        regexes over every value of every text column is the most expensive part of a
        profile; checks built from them are exact over every row."""
        text_cols = [
            p for p in profiles if infos[p.name].logical == "text" and p.present - p.blanks > 0
        ]
        if not text_cols:
            return
        if supports_regex(self.dialect):
            sample = (
                sa.select(*[cols[p.name] for p in text_cols])
                .select_from(source)
                .limit(SEMANTIC_ROWS)
                .subquery("sem")
            )
            exprs = []
            dens = []
            for p in text_cols:
                scol = sample.c[p.name]
                dens.append(
                    sa.func.count(sa.case((sa.and_(scol.is_not(None), sa.not_(blank(scol))), 1)))
                )
                for pattern in SEMANTIC.values():
                    exprs.append(
                        sa.func.count(
                            sa.case((sa.and_(sa.not_(blank(scol)), full_match(scol, pattern)), 1))
                        )
                    )
            values = list(self._scalar_row(sa.select(*dens, *exprs).select_from(sample)))
            denominators = values[: len(text_cols)]
            values = values[len(text_cols) :]
            for p, denom in zip(text_cols, denominators, strict=True):
                n = int(denom or 0) or 1
                p.semantic = {k: round(int(values.pop(0) or 0) / n, 4) for k in SEMANTIC}
            return
        compiled = {k: re.compile(f"(?:{v})") for k, v in SEMANTIC.items()}
        for p in text_cols:
            col = as_text(cols[p.name], self.dialect)
            stmt = (
                sa.select(col)
                .select_from(source)
                .where(cols[p.name].is_not(None))
                .limit(SEMANTIC_ROWS)
            )
            self._tick()
            values = [str(v[0]) for v in self.conn.execute(stmt).fetchall() if str(v[0]).strip(" ")]
            if len(values) > 2000:
                values = random.Random(0).sample(values, 2000)  # noqa: S311 a sample, not a secret
            n = len(values) or 1
            p.semantic = {
                k: round(sum(1 for v in values if rx.fullmatch(v)) / n, 4)
                for k, rx in compiled.items()
            }
