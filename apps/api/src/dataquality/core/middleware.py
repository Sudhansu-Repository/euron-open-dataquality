"""Pure ASGI middleware (no BaseHTTPMiddleware: it buffers streams and adds latency)."""

from __future__ import annotations

import json
import logging
import re
import secrets
import time

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from dataquality.core.config import Settings
from dataquality.core.logs import request_id_var
from dataquality.core.security import decode_session, parse_api_key

log = logging.getLogger("dataquality.http")

SECURITY_HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
    (b"cross-origin-opener-policy", b"same-origin"),
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
]
_QUIET = {"/healthz", "/readyz", "/metrics"}


class RequestContextMiddleware:
    """Assigns a request id, adds security headers, logs one line per request."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        incoming = dict(scope.get("headers") or []).get(b"x-request-id", b"").decode()[:64]
        rid = incoming if incoming.replace("-", "").replace("_", "").isalnum() else ""
        rid = rid or secrets.token_hex(8)
        token = request_id_var.set(rid)
        started = time.perf_counter()
        status = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", rid.encode()))
                headers.extend(SECURITY_HEADERS)
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            path = scope.get("path", "")
            if path not in _QUIET:
                log.info(
                    "request",
                    extra={
                        "method": scope.get("method"),
                        "path": path,
                        "status": status,
                        "ms": round((time.perf_counter() - started) * 1000, 1),
                    },
                )
            request_id_var.reset(token)


_BODY_METHODS = {"POST", "PUT", "PATCH"}


_UPLOAD_PATH = re.compile(
    r"^/api/v1/projects/[0-9a-f-]{36}/(datasets/upload|datasets/[0-9a-f-]{36}/files|connections/sqlite)$"
)
_PUSH_PATH = re.compile(
    r"^/api/v1/projects/[0-9a-f-]{36}/datasets/[0-9a-f-]{36}/(records|checks/yaml)$"
)


def _bearer(headers: dict[bytes, bytes]) -> str:
    value = headers.get(b"authorization", b"").decode("latin-1")
    return value[7:].strip() if value.lower().startswith("bearer ") else ""


def _may_send_large(headers: dict[bytes, bytes], secret: str) -> bool:
    """A genuine (signed, unexpired) session, or something shaped like an API key. Checked
    without the database: the route still authorizes the request fully; this only decides
    whether a large body may be read at all, so anonymous and forged-session requests stay
    at the small limit. A forged key costs the server one bounded read before its 401."""
    token = _bearer(headers) or headers.get(b"x-api-key", b"").decode("latin-1").strip()
    if token.startswith("dq_"):
        return parse_api_key(token) is not None
    if not token:
        for part in headers.get(b"cookie", b"").decode("latin-1").split(";"):
            name, _, value = part.strip().partition("=")
            if name == "dq_session":
                token = value
    return bool(token) and decode_session(token, secret) is not None


class BodySizeLimitMiddleware:
    """Refuses request bodies over ``limit`` bytes with 413, whatever their framing.

    ``Content-Length`` is checked up front; chunked bodies (no length) are counted as they
    arrive and refused the moment they pass the limit, before any route parses them. The
    accepted body is then replayed to the app unchanged.
    """

    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self.settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") not in _BODY_METHODS:
            await self.app(scope, receive, send)
            return
        limit = self.settings.max_body_bytes
        path = scope.get("path", "")
        headers = dict(scope.get("headers") or [])
        streaming = False
        if _UPLOAD_PATH.match(path) and _may_send_large(headers, self.settings.session_secret):
            # Uploads are large by nature: never buffered here, counted as they stream to
            # the route (which spools them to a temp file).
            limit = self.settings.max_upload_bytes
            streaming = True
        elif _PUSH_PATH.match(path) and _may_send_large(headers, self.settings.session_secret):
            limit = self.settings.max_push_bytes
        length = headers.get(b"content-length", b"")
        if length.isdigit() and int(length) > limit:
            await self._refuse(send, limit)
            return
        if streaming:
            await self._stream(scope, receive, send, limit)
            return
        chunks: list[bytes] = []
        size = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body = message.get("body", b"")
            size += len(body)
            if size > limit:
                await self._refuse(send, limit)
                return
            chunks.append(body)
            if not message.get("more_body", False):
                break
        replayed = False

        async def replay() -> Message:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": b"".join(chunks), "more_body": False}
            return await receive()  # after the body: wait for a disconnect

        await self.app(scope, replay, send)

    async def _stream(self, scope: Scope, receive: Receive, send: Send, limit: int) -> None:
        """Pass the body through, counting it. Past the limit the app sees a disconnect
        (it stops reading) and the client gets 413, unless a response already started."""
        size = 0
        started = False
        refused = False

        async def counted() -> Message:
            nonlocal size, refused
            if refused:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                size += len(message.get("body", b""))
                if size > limit:
                    refused = True
                    if not started:
                        await self._refuse(send, limit)
                    return {"type": "http.disconnect"}
            return message

        async def guarded_send(message: Message) -> None:
            nonlocal started
            if refused:
                return  # the 413 already went out
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        await self.app(scope, counted, guarded_send)

    async def _refuse(self, send: Send, limit: int) -> None:
        body = json.dumps(
            {
                "error": {
                    "code": "payload_too_large",
                    "type": "invalid_request_error",
                    "message": f"The request body is larger than {limit:,} bytes. Split "
                    "it, use a background job, or raise MAX_BODY_BYTES",
                    "details": {"limit_bytes": limit},
                }
            }
        ).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                    (b"connection", b"close"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
