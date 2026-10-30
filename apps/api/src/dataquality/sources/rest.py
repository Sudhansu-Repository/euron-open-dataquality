"""REST datasets: fetch JSON from a URL, take the records, write them as NDJSON for DuckDB.

The URL is checked at fetch time against the address it resolves to (no instance metadata,
no private network unless allowed), redirects are not followed, the body is capped, and the
headers (an Authorization header, typically) come from the sealed store.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import httpx

from dataquality.core.net import check_url, resolves_safely


class RestSourceError(Exception):
    """The endpoint could not be read as records."""


def records_at(document: Any, path: str | None) -> list[Any]:
    """The records under a dotted path (``data.items``); the document itself when empty."""
    node = document
    for part in [p for p in (path or "").split(".") if p]:
        if isinstance(node, Mapping) and part in node:
            node = node[part]
        elif isinstance(node, list) and part.isdigit() and int(part) < len(node):
            node = node[int(part)]
        else:
            raise RestSourceError(f"the response has nothing at {path!r} (stopped at {part!r})")
    if isinstance(node, Mapping):
        node = [node]
    if not isinstance(node, list):
        raise RestSourceError("the records must be a JSON array of objects")
    return node


def flatten(record: Any) -> dict[str, Any]:
    """One level: nested objects and arrays become JSON text, so every column is checkable."""
    if not isinstance(record, Mapping):
        return {"value": record}
    return {
        str(k): (
            json.dumps(v, separators=(",", ":"), default=str)
            if isinstance(v, Mapping | list)
            else v
        )
        for k, v in record.items()
    }


def write_ndjson(records: list[Any], path: Path) -> int:
    with path.open("w", encoding="utf-8") as out:
        for record in records:
            out.write(json.dumps(flatten(record), default=str))
            out.write("\n")
    return len(records)


async def fetch_records(
    http: httpx.AsyncClient,
    url: str,
    *,
    headers: dict[str, str],
    records_path: str | None,
    max_bytes: int,
    allow_private: bool,
    timeout_s: float = 60.0,
) -> list[Any]:
    try:
        check_url(url)
    except ValueError as exc:
        raise RestSourceError(str(exc)) from exc
    if not await resolves_safely(url, allow_private=allow_private):
        raise RestSourceError(
            "the URL resolves to a private or metadata address, which this deployment refuses"
        )
    body = bytearray()
    try:
        async with http.stream("GET", url, headers=headers, timeout=timeout_s) as resp:
            if resp.status_code >= 400:
                raise RestSourceError(f"the endpoint answered HTTP {resp.status_code}")
            if 300 <= resp.status_code < 400:
                raise RestSourceError("the endpoint redirected; use the final URL")
            async for chunk in resp.aiter_bytes():
                body.extend(chunk)
                if len(body) > max_bytes:
                    raise RestSourceError(f"the response is larger than {max_bytes:,} bytes")
    except httpx.HTTPError as exc:
        raise RestSourceError(f"the endpoint could not be reached ({type(exc).__name__})") from exc
    try:
        document = json.loads(body)
    except ValueError as exc:
        raise RestSourceError("the response is not JSON") from exc
    return records_at(document, records_path)
