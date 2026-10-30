"""Suggested checks, derived from a profile with plain rules (no AI).

Each rule reads what the data already is and proposes the check that keeps it that way: a
column with no missing values gets "not null", one where every value is distinct and the
name looks like a key gets "unique", a column where 95% of values are emails gets the email
pattern, and so on. Every suggestion says why, so a person can accept it with confidence.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from dataquality.engine.profiler import ColumnProfile, DatasetProfile
from dataquality.engine.spec import CheckType, Severity

_KEY_NAME = re.compile(r"(^id$|_id$|^id_|uuid|^key$|_key$|code$|^sku$|number$|_no$)", re.I)
_FRESH_NAME = re.compile(
    r"(updated|created|loaded|inserted|modified|event|ingest|timestamp|_at$|_time$|date$)", re.I
)
_NON_NEGATIVE_NAME = re.compile(
    r"(price|amount|qty|quantity|count|total|cost|age|salary|balance|stock|units)", re.I
)
SEMANTIC_PRESET = {"email": "email", "uuid": "uuid", "url": "url"}
TYPE_FROM_SEMANTIC = ("date", "datetime", "integer", "decimal", "boolean")


@dataclass
class Suggestion:
    type: CheckType
    column: str | None
    params: dict[str, Any] = field(default_factory=dict)
    severity: Severity = Severity.ERROR
    reason: str = ""

    @property
    def key(self) -> str:
        return f"{self.type.value}:{self.column or '*'}"


def suggest(profile: DatasetProfile, now: datetime | None = None) -> list[Suggestion]:
    now = now or datetime.now(UTC)
    out: list[Suggestion] = []
    if profile.row_count == 0:
        return [
            Suggestion(
                CheckType.ROW_COUNT,
                None,
                {"min": 1},
                reason="The dataset is empty; expect at least one row",
            )
        ]
    out.append(
        Suggestion(
            CheckType.SCHEMA,
            None,
            {
                "columns": [{"name": c.name, "type": _schema_type(c)} for c in profile.columns],
                "allow_extra": True,
            },
            reason=f"Lock the {len(profile.columns)} columns and their types, so a dropped "
            f"or retyped column is caught",
        )
    )
    out.append(
        Suggestion(
            CheckType.ROW_COUNT,
            None,
            {"min": max(1, math.floor(profile.row_count * 0.5))},
            severity=Severity.WARN,
            reason=f"{profile.row_count:,} rows now; fewer than half of that usually means "
            f"a broken load",
        )
    )
    out.append(
        Suggestion(
            CheckType.DUPLICATE_ROWS,
            None,
            reason="Exact copies of a whole row are almost always a double load",
        )
    )
    for c in profile.columns:
        out.extend(_column(c, now))
    return out


def _schema_type(c: ColumnProfile) -> str:
    return (
        c.logical
        if c.logical in ("integer", "decimal", "boolean", "date", "datetime", "text", "uuid")
        else "any"
    )


def _column(c: ColumnProfile, now: datetime) -> list[Suggestion]:
    out: list[Suggestion] = []
    present = c.present - (c.blanks or 0)
    missing = c.rows - present
    is_key = bool(_KEY_NAME.search(c.name))
    if c.rows and missing == 0:
        out.append(Suggestion(CheckType.NOT_NULL, c.name, reason="No missing values so far"))
    elif c.rows and missing / c.rows <= 0.01:
        out.append(
            Suggestion(
                CheckType.NOT_NULL,
                c.name,
                severity=Severity.WARN,
                reason=f"{missing:,} missing ({missing / c.rows:.2%}); worth knowing when it grows",
            )
        )
    if (
        c.logical in ("integer", "text", "uuid")
        and c.distinct is not None
        and present >= 10
        and (c.distinct == c.present or (is_key and c.distinct >= 0.98 * c.present))
        and (is_key or c.logical == "uuid")
    ):
        dupes = c.present - c.distinct
        reason = (
            "Looks like a key and every value is distinct"
            if not dupes
            else f"Looks like a key; {dupes:,} values repeat"
        )
        out.append(Suggestion(CheckType.UNIQUE, c.name, reason=reason))
    if c.logical == "text" and present >= 5 and c.semantic:
        sem = c.semantic
        preset = next((p for k, p in SEMANTIC_PRESET.items() if sem.get(k, 0) >= 0.9), None)
        if preset is None and sem.get("phone", 0) >= 0.9:
            top_shape = c.shapes[0]["shape"] if c.shapes else ""
            preset = (
                "phone_e164" if top_shape.startswith("+") and " " not in top_shape else "phone_in"
            )
        if preset:
            share = max(sem.get(k, 0) for k in ("email", "uuid", "url", "phone"))
            out.append(
                Suggestion(
                    CheckType.PATTERN,
                    c.name,
                    {"preset": preset},
                    reason=f"{share:.0%} of values are valid {preset.replace('_', ' ')}",
                )
            )
        else:
            kind = next((k for k in TYPE_FROM_SEMANTIC if sem.get(k, 0) >= 0.95), None)
            if kind and not (kind == "boolean" and (c.distinct or 0) > 2):
                out.append(
                    Suggestion(
                        CheckType.TYPE,
                        c.name,
                        {"type": kind},
                        reason=f"{sem[kind]:.0%} of values are {kind}s stored as text",
                    )
                )
            elif c.shapes and present >= 20 and (c.distinct or 0) > 10:
                top = c.shapes[0]
                share = top["count"] / present
                if share >= 0.95:
                    out.append(
                        Suggestion(
                            CheckType.FORMAT_CONSISTENCY,
                            c.name,
                            {"min_share": 0.95},
                            Severity.WARN,
                            f"{share:.0%} of values have the shape {top['shape']!r}",
                        )
                    )
    if (
        c.logical == "text"
        and c.distinct is not None
        and 1 < c.distinct <= 12
        and present >= 20
        and len(c.top_values) == c.distinct
        and not is_key
    ):
        values = sorted(str(v["value"]) for v in c.top_values if v["value"] not in (None, ""))
        out.append(
            Suggestion(
                CheckType.ACCEPTED_VALUES,
                c.name,
                {"values": values},
                reason=f"Only {c.distinct} distinct values: "
                f"{', '.join(values[:5])}{'...' if len(values) > 5 else ''}",
            )
        )
    if c.logical in ("integer", "decimal") and c.min is not None:
        low = float(c.min)
        if low >= 0 and (_NON_NEGATIVE_NAME.search(c.name) or not is_key):
            out.append(
                Suggestion(CheckType.RANGE, c.name, {"min": 0}, reason="Never negative so far")
            )
        if not is_key and (c.distinct or 0) > 20 and (c.stddev or 0) > 0:
            out.append(
                Suggestion(
                    CheckType.OUTLIERS,
                    c.name,
                    {"z": 4.0},
                    Severity.WARN,
                    "Flags values more than 4 standard deviations from the mean",
                )
            )
    if (
        c.logical in ("date", "datetime")
        and _FRESH_NAME.search(c.name)
        and c.max not in (None, "[masked]")
    ):
        try:
            newest = datetime.fromisoformat(str(c.max))
        except ValueError:
            newest = None
        if newest is not None:
            if newest.tzinfo is None:
                newest = newest.replace(tzinfo=UTC)
            age = max((now - newest).total_seconds() / 3600, 0)
            if age <= 24 * 7:
                limit = 26 if age <= 26 else math.ceil(age * 2)
                out.append(
                    Suggestion(
                        CheckType.FRESHNESS,
                        c.name,
                        {"max_age_hours": limit},
                        Severity.WARN,
                        f"Newest value is {age:.0f} hours old; alert if no new data for "
                        f"{limit} hours",
                    )
                )
    if (
        c.logical == "text"
        and c.min_length is not None
        and c.min_length == c.max_length
        and present >= 10
        and c.min_length > 0
        and not any(s.type in (CheckType.PATTERN, CheckType.TYPE) for s in out)
    ):
        out.append(
            Suggestion(
                CheckType.LENGTH,
                c.name,
                {"min": c.min_length, "max": c.max_length},
                Severity.WARN,
                f"Every value is exactly {c.min_length} characters",
            )
        )
    return out
