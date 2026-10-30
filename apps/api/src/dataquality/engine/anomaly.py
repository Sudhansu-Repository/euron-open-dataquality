"""Anomaly detection on a metric's history, explainable in one sentence.

Robust z-score (Iglewicz and Hoaglin): the distance of the new value from the median of
the history, in units of the median absolute deviation scaled to match a standard
deviation (MAD x 1.4826). Medians ignore the outliers the history already contains, so
one bad day does not hide the next. A value is anomalous when that distance is above the
sensitivity (3.5 by default).

Two guards keep it quiet on normal data: at least ``min_history`` points are needed, and
a change smaller than ``min_relative_change`` of the median never counts (a row count of
10,001 against a perfectly flat 10,000 has an infinite z-score and means nothing). With a
flat history (MAD 0) only that relative change decides.
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from dataclasses import dataclass

MAD_SCALE = 1.4826


@dataclass(frozen=True)
class Detection:
    anomalous: bool
    value: float
    median: float
    z: float | None
    direction: str  # up, down, none
    history: int
    explanation: str


def detect(
    value: float,
    history: Sequence[float],
    *,
    label: str,
    sensitivity: float = 3.5,
    min_history: int = 6,
    min_relative_change: float = 0.1,
    unit: str = "",
) -> Detection:
    n = len(history)
    if n < min_history:
        return Detection(
            False,
            value,
            value,
            None,
            "none",
            n,
            f"Not enough history yet ({n} of {min_history} scans)",
        )
    median = statistics.median(history)
    mad = statistics.median([abs(x - median) for x in history]) * MAD_SCALE
    delta = value - median
    direction = "up" if delta > 0 else "down" if delta < 0 else "none"
    relative = abs(delta) / abs(median) if median else (float("inf") if delta else 0.0)
    if mad > 0:
        z: float | None = delta / mad
        anomalous = abs(delta / mad) > sensitivity and relative >= min_relative_change
    else:
        z = None
        anomalous = relative >= min_relative_change and delta != 0
    if not anomalous:
        return Detection(
            False, value, median, z, direction, n, f"{label} is within its normal range"
        )
    change = (
        f"{relative:.0%} {'above' if delta > 0 else 'below'}"
        if median
        else ("above" if delta > 0 else "below")
    )
    spread = (
        f"; that is {abs(z):.1f} robust deviations"
        if z is not None
        else "; it never changed before"
    )
    text = (
        f"{label} is {_fmt(value)}{unit}, {change} the typical {_fmt(median)}{unit} "
        f"(median of the last {n} scans){spread}"
    )
    return Detection(True, value, median, z, direction, n, text)


def _fmt(v: float) -> str:
    if float(v).is_integer():
        return f"{int(v):,}"
    return f"{v:,.4g}" if abs(v) < 1000 else f"{v:,.0f}"
