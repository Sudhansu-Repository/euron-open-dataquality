"""The optional AI assistant: plain language to a check, and incident explanations.

Off by default. With it off no request is ever made (the endpoints answer 409 before any
network code runs). With it on, the model sees column names, types and profile statistics;
sample values only when the project allows it. A drafted check is never saved by the
assistant: it goes through the same validation as a hand-written one and a person accepts
it. Any OpenAI-compatible endpoint works (a hosted provider, Ollama, vLLM).
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dataquality.alerts.models import Incident
from dataquality.alerts.schemas import ExplainOut
from dataquality.checks.schemas import CheckIn, DraftOut
from dataquality.checks.service import validate
from dataquality.core.container import Container
from dataquality.core.errors import AppError, ConflictError
from dataquality.datasets.models import Dataset
from dataquality.engine.patterns import PRESETS
from dataquality.engine.spec import CheckType
from dataquality.org import service as org
from dataquality.projects.access import Principal
from dataquality.scans.models import CheckResult, Scan, ScanProfile

log = logging.getLogger("dataquality.ai")
DRAFT_MARKER = "DRAFT_CHECK"
EXPLAIN_MARKER = "EXPLAIN_INCIDENT"


class AiUnavailableError(AppError):
    status_code = 502
    code = "ai_unavailable"


async def _settings(container: Container, session: AsyncSession) -> tuple[str, str, str | None]:
    row = await org.get(session)
    if not row.ai_enabled or not row.ai_base_url or not row.ai_model:
        raise ConflictError(
            "The AI assistant is off. An admin can turn it on in Settings with any OpenAI-compatible endpoint",
            code="ai_disabled",
        )
    return row.ai_base_url, row.ai_model, await org.ai_api_key(container, row)


async def _chat(
    container: Container, session: AsyncSession, system: str, user: str
) -> tuple[str, str]:
    base, model, key = await _settings(container, session)
    org.check_endpoint(container, base)
    headers = {"authorization": f"Bearer {key}"} if key else {}
    body = {
        "model": model,
        "temperature": 0,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    }
    try:
        resp = await container.http.post(
            base.rstrip("/") + "/chat/completions",
            json=body,
            headers=headers,
            timeout=container.settings.ai_timeout_s,
        )
    except httpx.HTTPError as exc:
        raise AiUnavailableError(
            f"The AI endpoint could not be reached ({type(exc).__name__})"
        ) from exc
    if resp.status_code >= 400:
        raise AiUnavailableError(f"The AI endpoint answered HTTP {resp.status_code}")
    try:
        return str(resp.json()["choices"][0]["message"]["content"]), model
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise AiUnavailableError(
            "The AI endpoint's answer was not an OpenAI chat completion"
        ) from exc


async def _columns(session: AsyncSession, d: Dataset, with_samples: bool) -> list[dict[str, Any]]:
    profile = await session.scalar(
        select(ScanProfile)
        .where(ScanProfile.dataset_id == d.id)
        .order_by(ScanProfile.created_at.desc())
        .limit(1)
    )
    if profile is None:
        scan = await session.get(Scan, d.last_scan_id) if d.last_scan_id else None
        return [{"name": c["name"], "type": c["type"]} for c in (scan.columns if scan else [])]
    masked = {m.lower() for m in d.masked_columns or []}
    out = []
    for c in profile.columns:
        item: dict[str, Any] = {
            "name": c["name"],
            "type": c["logical"],
            "null_rate": round(c["nulls"] / c["rows"], 4) if c["rows"] else 0,
            "distinct": c.get("distinct"),
            "semantic": {k: v for k, v in (c.get("semantic") or {}).items() if v >= 0.5},
        }
        if with_samples and c["name"].lower() not in masked:
            item["top_values"] = [v["value"] for v in (c.get("top_values") or [])[:5]]
            item["min"], item["max"] = c.get("min"), c.get("max")
        out.append(item)
    return out


SYSTEM_DRAFT = f"""{DRAFT_MARKER}
You turn a data quality rule written in plain language into exactly one check for a data quality tool.
Answer with one JSON object and nothing else:
{{"name": str, "type": str, "column": str or null, "params": object, "severity": "error" or "warn", "explanation": str}}
Check types and params:
not_null {{"empty_is_null": bool}}; unique {{"columns": [other key columns]}}; duplicate_rows {{}};
type {{"type": "integer|decimal|boolean|date|datetime|uuid"}}; range {{"min": number or ISO date, "max": ...}};
pattern {{"preset": one of {sorted(PRESETS)}}} or {{"regex": "..."}} (use [0-9], never \\d);
accepted_values {{"values": [...]}}; length {{"min": int, "max": int}}; freshness {{"max_age_hours": number}};
row_count {{"min": int, "max": int}}; compare {{"op": "<|<=|=|!=|>=|>", "other": column}};
format_consistency {{"min_share": 0.95}}; outliers {{"z": 3}}; custom_sql {{"sql": "SELECT ... FROM {{table}} WHERE <failing rows>"}}.
Use only the columns given."""


def _json_object(text: str) -> dict[str, Any]:
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        raise AiUnavailableError("The AI answer had no JSON object")
    try:
        value = json.loads(match.group(0))
    except ValueError as exc:
        raise AiUnavailableError("The AI answer was not valid JSON") from exc
    if not isinstance(value, dict):
        raise AiUnavailableError("The AI answer was not a JSON object")
    return value


async def draft_check(
    container: Container, session: AsyncSession, p: Principal, d: Dataset, prompt: str
) -> DraftOut:
    columns = await _columns(session, d, p.project.ai_allow_samples)
    user = json.dumps({"rule": prompt, "dataset": d.name, "columns": columns}, default=str)
    text, _model = await _chat(container, session, SYSTEM_DRAFT, user)
    raw = _json_object(text)
    try:
        check = CheckIn(
            name=str(raw.get("name") or "")[:160] or None,
            type=CheckType(str(raw.get("type"))),
            column=raw.get("column"),
            params=raw.get("params") or {},
            severity=raw.get("severity", "error"),
        )
    except (ValueError, ValidationError) as exc:
        raise AppError(
            f"The AI proposed a check this tool does not have: {raw.get('type')!r}",
            code="ai_invalid_check",
        ) from exc
    if check.column and check.column not in {c["name"] for c in columns}:
        raise AppError(
            f"The AI named a column that does not exist: {check.column!r}", code="ai_invalid_check"
        )
    validate(check)
    return DraftOut(check=check, explanation=str(raw.get("explanation") or "")[:1000])


SYSTEM_EXPLAIN = f"""{EXPLAIN_MARKER}
You explain a data quality incident to a developer in at most five short sentences: what is wrong,
the most likely cause, and what to check first. Plain language, no markdown headings."""


async def explain_incident(
    container: Container, session: AsyncSession, p: Principal, i: Incident
) -> ExplainOut:
    d = await session.get(Dataset, i.dataset_id)
    results = []
    if i.last_scan_id:
        for r in (
            await session.scalars(
                select(CheckResult).where(
                    CheckResult.scan_id == i.last_scan_id, CheckResult.status != "pass"
                )
            )
        ).all():
            item: dict[str, Any] = {
                "check": r.check_name,
                "type": r.type,
                "column": r.column,
                "failed": r.failed,
                "of": r.evaluated,
                "message": r.message,
            }
            if p.project.ai_allow_samples:
                item["sample"] = r.sample[:3]
            results.append(item)
    user = json.dumps(
        {
            "incident": {
                "title": i.title,
                "detail": i.detail,
                "occurrences": i.occurrences,
                "since": i.opened_at.isoformat(),
            },
            "dataset": d.name if d else None,
            "columns": await _columns(session, d, p.project.ai_allow_samples) if d else [],
            "failing_checks": results[:20],
        },
        default=str,
    )
    text, model = await _chat(container, session, SYSTEM_EXPLAIN, user)
    return ExplainOut(explanation=text.strip()[:3000], model=model)
