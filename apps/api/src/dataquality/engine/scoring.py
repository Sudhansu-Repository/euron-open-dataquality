"""The quality score: one number per dataset, built from the share of records that pass.

For every check that ran (errors are left out, they measure nothing):

    pass rate = 1 - failed / evaluated          (row-level checks)
    pass rate = 1 if it passed, else 0          (schema, freshness, row count)

A dimension's score is the mean pass rate of its checks, and the dataset's score is the
mean of the dimensions it has, so ten not-null checks do not drown out one freshness check.
Scores are percentages with one decimal, rounded down, so 100% always means
nothing failed. A project's score is the mean of its datasets'
latest scores. ``docs/architecture/scoring.md`` explains the choice.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from dataquality.engine.spec import DATASET_LEVEL, CheckType, Dimension


@dataclass(frozen=True)
class ScoredResult:
    type: CheckType
    dimension: Dimension
    status: str  # pass, fail, error
    evaluated: int
    failed: int


@dataclass(frozen=True)
class Score:
    overall: float | None
    dimensions: dict[str, float]


def floor1(value: float) -> float:
    """One decimal, rounded down: 100% means nothing failed, never 99.96% shown as 100%."""
    return math.floor(value * 10 + 1e-9) / 10


def pass_rate(r: ScoredResult) -> float | None:
    if r.status == "error":
        return None
    if r.type in DATASET_LEVEL:
        return 1.0 if r.status == "pass" else 0.0
    if r.evaluated <= 0:
        return None  # nothing to judge (an empty table, a filter matching nothing)
    return max(0.0, 1.0 - r.failed / r.evaluated)


def score(results: Iterable[ScoredResult]) -> Score:
    by_dim: dict[str, list[float]] = defaultdict(list)
    for r in results:
        rate = pass_rate(r)
        if rate is not None:
            by_dim[r.dimension.value].append(rate)
    dims = {d: floor1(100.0 * sum(v) / len(v)) for d, v in by_dim.items() if v}
    if not dims:
        return Score(None, {})
    overall = floor1(sum(dims.values()) / len(dims))
    return Score(overall, dict(sorted(dims.items())))
