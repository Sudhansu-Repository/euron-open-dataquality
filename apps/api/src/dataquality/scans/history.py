"""History: the metrics each scan records, anomaly detection against them, schema drift.

Metrics per scan (``metric_points``): ``row_count``, ``score``, ``dimension`` (key: the
dimension), ``check_failed_pct`` (key: check id), and from the profile ``null_rate``,
``distinct`` and ``mean`` (key: column). Anomalies are looked for in ``row_count``,
``null_rate`` and ``score``: the ones whose sudden change means a broken load.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from dataquality.engine.anomaly import detect
from dataquality.engine.profiler import DatasetProfile
from dataquality.scans.models import Anomaly, MetricPoint, Scan

HISTORY = 30
WATCHED = {
    "row_count": "Row count",
    "null_rate": "Missing values",
    "score": "Quality score",
    "check_failed_pct": "Failing rows",
}
# Percentages: a change under one percentage point is noise, whatever its relative size.
PERCENT = {"null_rate", "score", "check_failed_pct"}


@dataclass(frozen=True)
class Drift:
    column: str
    change: str  # added, removed, retyped
    before: str | None
    after: str | None

    def text(self) -> str:
        if self.change == "added":
            return f"Column {self.column} was added ({self.after})"
        if self.change == "removed":
            return f"Column {self.column} was removed"
        return f"Column {self.column} changed type from {self.before} to {self.after}"


def metrics_for(
    scan: Scan,
    score: float | None,
    dims: dict[str, float],
    results: list[tuple[uuid.UUID | None, float]],
    profile: DatasetProfile | None,
) -> list[tuple[str, str, float]]:
    out: list[tuple[str, str, float]] = [("row_count", "", float(scan.row_count or 0))]
    if score is not None:
        out.append(("score", "", score))
    out += [("dimension", d, v) for d, v in dims.items()]
    out += [("check_failed_pct", str(cid), pct) for cid, pct in results if cid is not None]
    if profile is not None:
        for c in profile.columns:
            out.append(("null_rate", c.name, round(100.0 * c.null_rate, 4)))
            if c.distinct is not None:
                out.append(("distinct", c.name, float(c.distinct)))
            if c.mean is not None:
                out.append(("mean", c.name, float(c.mean)))
    return out


async def record(
    session: AsyncSession,
    scan: Scan,
    at: datetime,
    points: list[tuple[str, str, float]],
    sensitivity: float,
    labels: dict[str, str] | None = None,
) -> list[Anomaly]:
    """Store this scan's points and return the anomalies among the watched ones."""
    watched = [(m, k, v) for m, k, v in points if m in WATCHED]
    history: dict[tuple[str, str], list[float]] = defaultdict(list)
    if watched:
        # The last HISTORY points of every watched series, however many series there are.
        ranked = (
            select(
                MetricPoint.metric,
                MetricPoint.key,
                MetricPoint.value,
                func.row_number()
                .over(
                    partition_by=(MetricPoint.metric, MetricPoint.key),
                    order_by=MetricPoint.at.desc(),
                )
                .label("n"),
            )
            .where(
                MetricPoint.dataset_id == scan.dataset_id,
                MetricPoint.metric.in_(sorted({m for m, _, _ in watched})),
                MetricPoint.at < at,
            )
            .subquery()
        )
        rows = (
            await session.execute(
                select(ranked.c.metric, ranked.c.key, ranked.c.value)
                .where(ranked.c.n <= HISTORY)
                .order_by(ranked.c.metric, ranked.c.key, ranked.c.n)
            )
        ).all()
        for m, k, v in rows:
            history[(m, k)].append(float(v))
    session.add_all(
        MetricPoint(dataset_id=scan.dataset_id, scan_id=scan.id, metric=m, key=k, value=v, at=at)
        for m, k, v in points
    )
    found: list[Anomaly] = []
    for m, k, v in watched:
        name = (labels or {}).get(k, k)
        label = WATCHED[m] + (
            f" for {name}" if m == "check_failed_pct" else f" in {name}" if k else ""
        )
        unit = "%" if m in PERCENT else ""
        floor = 0.5 if m in ("null_rate", "check_failed_pct") else 0.1
        d = detect(
            v,
            list(reversed(history[(m, k)])),
            label=label,
            sensitivity=sensitivity,
            unit=unit,
            min_relative_change=floor,
        )
        if m in PERCENT and d.anomalous and abs(d.value - d.median) < 1.0:
            continue
        if d.anomalous:
            found.append(
                Anomaly(
                    project_id=scan.project_id,
                    dataset_id=scan.dataset_id,
                    scan_id=scan.id,
                    kind="metric",
                    metric=m,
                    key=k,
                    value=d.value,
                    expected=d.median,
                    z=d.z,
                    direction=d.direction,
                    explanation=d.explanation,
                    details={"history": d.history},
                )
            )
    session.add_all(found)
    return found


async def drift(session: AsyncSession, scan: Scan) -> list[Drift]:
    """Columns added, removed or retyped since the previous successful scan."""
    previous = await session.scalar(
        select(Scan.columns)
        .where(Scan.dataset_id == scan.dataset_id, Scan.status == "succeeded", Scan.id != scan.id)
        .order_by(Scan.finished_at.desc())
        .limit(1)
    )
    if not previous:
        return []
    before: dict[str, Any] = {c["name"]: c["type"] for c in previous}
    after: dict[str, Any] = {c["name"]: c["type"] for c in scan.columns or []}
    out = [Drift(n, "removed", t, None) for n, t in before.items() if n not in after]
    out += [Drift(n, "added", None, t) for n, t in after.items() if n not in before]
    out += [
        Drift(n, "retyped", before[n], t)
        for n, t in after.items()
        if n in before and before[n] != t
    ]
    return out


def drift_anomalies(scan: Scan, changes: list[Drift]) -> list[Anomaly]:
    return [
        Anomaly(
            project_id=scan.project_id,
            dataset_id=scan.dataset_id,
            scan_id=scan.id,
            kind="schema",
            metric="schema",
            key=c.column,
            direction="none",
            explanation=c.text(),
            details={"change": c.change, "before": c.before, "after": c.after},
        )
        for c in changes
    ]
