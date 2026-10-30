"""A stand-in for an OpenAI-compatible LLM, for the demo and the tests (no key, no network).

``POST /v1/chat/completions`` answers deterministically: for a check draft it reads the
rule and the columns from the request and proposes a matching check; for an incident it
writes a short explanation. ``GET /stats`` counts requests: the AI-off acceptance test
reads it to prove that no request was ever made. ``POST /webhook`` is a webhook sink that
keeps what it receives, for the alert tests and the demo. ``GET /feed/leads`` is a small
partner feed for REST datasets.
"""

from __future__ import annotations

import json
import time
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI(title="DataQuality mock AI", docs_url=None, redoc_url=None, openapi_url=None)
STATE: dict[str, Any] = {"requests": 0, "last": None, "fail": False, "hooks": []}


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/stats")
async def stats() -> dict[str, Any]:
    return {"requests": STATE["requests"], "last": STATE["last"]}


@app.post("/admin/reset")
async def reset(request: Request) -> dict[str, str]:
    body = await request.json() if request.headers.get("content-length") not in (None, "0") else {}
    STATE.update(requests=0, last=None, fail=bool(body.get("fail", False)), hooks=[])
    return {"status": "reset"}


@app.post("/webhook")
async def webhook(request: Request) -> dict[str, str]:
    raw = await request.body()
    STATE["hooks"].append({"headers": dict(request.headers), "body": raw.decode()})
    del STATE["hooks"][:-200]
    return {"status": "received"}


@app.get("/feed/leads")
async def leads(bad: int = 3, rows: int = 40) -> dict[str, Any]:
    """A partner's REST feed of leads, for REST datasets: ``bad`` of them lack an email."""
    items = [
        {
            "lead_id": f"L-{1000 + i}",
            "email": None if i < bad else f"lead{i}@partner.example",
            "score": (i * 37) % 100,
            "source": ["ads", "referral", "event"][i % 3],
            "meta": {"campaign": f"c{i % 4}"},
        }
        for i in range(rows)
    ]
    return {"data": {"items": items}, "next": None}


@app.get("/webhook")
async def webhooks() -> list[dict[str, Any]]:
    return list(STATE["hooks"])


def _draft(user: dict[str, Any]) -> dict[str, Any]:
    rule = str(user.get("rule", "")).lower()
    cols = [c["name"] for c in user.get("columns", [])]

    def col(*words: str) -> str | None:
        return next((c for c in cols for w in words if w in c.lower()), None) or (
            cols[0] if cols else None
        )

    if "email" in rule:
        c = col("email")
        return {
            "name": f"{c} is a valid email",
            "type": "pattern",
            "column": c,
            "params": {"preset": "email"},
            "severity": "error",
            "explanation": "Every email must look like name@domain.tld.",
        }
    if "negative" in rule or "positive" in rule or "price" in rule:
        c = col("price", "amount", "total")
        return {
            "name": f"{c} is not negative",
            "type": "range",
            "column": c,
            "params": {"min": 0},
            "severity": "error",
            "explanation": "Values below zero are refused.",
        }
    if "unique" in rule or "duplicate" in rule:
        c = col("id")
        return {
            "name": f"{c} is unique",
            "type": "unique",
            "column": c,
            "params": {},
            "severity": "error",
            "explanation": "No two rows may share this value.",
        }
    c = col()
    return {
        "name": f"{c} is present",
        "type": "not_null",
        "column": c,
        "params": {},
        "severity": "warn",
        "explanation": "The column must not be empty.",
    }


@app.post("/v1/chat/completions", response_model=None)
async def chat(request: Request) -> dict[str, Any] | JSONResponse:
    body = await request.json()
    STATE["requests"] += 1
    STATE["last"] = body
    if STATE["fail"]:
        return JSONResponse({"error": {"message": "mock failure"}}, status_code=503)
    messages = body.get("messages") or []
    system = next((m.get("content", "") for m in messages if m.get("role") == "system"), "")
    question = next(
        (m.get("content", "") for m in reversed(messages) if m.get("role") == "user"), ""
    )
    try:
        user = json.loads(question)
    except ValueError:
        user = {}
    if "DRAFT_CHECK" in system:
        content = json.dumps(_draft(user))
    else:
        incident = user.get("incident", {})
        failing = user.get("failing_checks", [])
        content = (
            f"{incident.get('title', 'This incident')} has been seen {incident.get('occurrences', 1)} times. "
            f"{len(failing)} checks fail in the latest scan. A recent load most likely brought in rows that "
            "skipped validation upstream; compare the failing samples with the previous load first. "
            "(mock explanation)"
        )
    words = len(str(question).split())
    return {
        "id": f"mock-{STATE['requests']}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": body.get("model", "mock"),
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": words, "completion_tokens": 40, "total_tokens": words + 40},
    }
