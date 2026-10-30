"""Send queued notifications: email, Slack, or a signed webhook, with retries.

The outbox row is claimed with ``FOR UPDATE SKIP LOCKED``; a failure is retried with
exponential backoff (1, 2, 4... minutes, at most an hour) up to ``MAX_ATTEMPTS``, then the
notification is marked failed and stays visible on the incident.

Webhooks carry ``X-DQ-Signature: t=<unix time>,v1=<hex HMAC-SHA256 of "<t>.<body>">`` with
the channel's secret, so the receiver can prove the request came from this deployment and
reject replays (``docs/architecture/alerts.md`` has a verifier).
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import orjson
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dataquality.alerts.models import AlertChannel, Incident, Notification
from dataquality.core import mail
from dataquality.core.container import Container
from dataquality.core.net import check_url, resolves_safely
from dataquality.datasets.models import Dataset
from dataquality.observability.metrics import NOTIFICATIONS

log = logging.getLogger("dataquality.alerts")
MAX_ATTEMPTS = 8
SIGNATURE_HEADER = "x-dq-signature"


class DeliveryError(Exception):
    """The channel refused the notification (retried later)."""


def channel_context(channel: AlertChannel) -> str:
    return f"alert_channel:{channel.id}:secret"


def sign(secret: str, body: bytes, ts: int | None = None) -> str:
    ts = int(time.time()) if ts is None else ts
    mac = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={ts},v1={mac}"


def verify(secret: str, body: bytes, header: str, tolerance_s: int = 300) -> bool:
    """What a receiver does (used by the tests and shown in the docs)."""
    try:
        parts = dict(p.split("=", 1) for p in header.split(","))
        ts = int(parts["t"])
    except (ValueError, KeyError):
        return False
    if abs(time.time() - ts) > tolerance_s:
        return False
    return hmac.compare_digest(sign(secret, body, ts), header)


@dataclass(frozen=True)
class Message:
    event: str
    title: str
    text: str
    url: str
    payload: dict[str, Any]


def render(
    settings_url: str, n: Notification, incident: Incident, dataset: Dataset | None
) -> Message:
    url = f"{settings_url.rstrip('/')}/projects/{incident.project_id}/incidents/{incident.id}"
    word = {"opened": "Problem", "resolved": "Resolved", "test": "Test"}.get(n.event, n.event)
    title = f"[{word}] {incident.title}"
    lines = [incident.title, "", incident.detail]
    if n.event == "resolved":
        lines = [f"Resolved: {incident.title}", "", "The latest scan no longer shows this problem."]
    lines += ["", f"Open in DataQuality: {url}"]
    payload = {
        "event": f"incident.{n.event}",
        "incident": {
            "id": str(incident.id),
            "status": incident.status,
            "severity": incident.severity,
            "title": incident.title,
            "detail": incident.detail,
            "opened_at": incident.opened_at.isoformat() if incident.opened_at else None,
            "occurrences": incident.occurrences,
            "url": url,
        },
        "dataset": {"id": str(dataset.id), "name": dataset.name, "slug": dataset.slug}
        if dataset
        else None,
        "project_id": str(incident.project_id),
        "sent_at": datetime.now(UTC).isoformat(),
    }
    return Message(n.event, title, "\n".join(lines), url, payload)


async def _post(container: Container, url: str, body: bytes, headers: dict[str, str]) -> None:
    check_url(url)
    if not await resolves_safely(url, allow_private=container.settings.outbound_allow_private):
        raise DeliveryError(
            "the URL resolves to a private or metadata address, which this deployment refuses"
        )
    try:
        resp = await container.http.post(
            url, content=body, headers={"content-type": "application/json", **headers}, timeout=10
        )
    except Exception as exc:  # httpx raises many transport errors
        raise DeliveryError(f"could not reach the endpoint ({type(exc).__name__})") from exc
    if resp.status_code >= 300:
        raise DeliveryError(f"the endpoint answered HTTP {resp.status_code}")


async def send(container: Container, channel: AlertChannel, message: Message) -> None:
    if channel.kind == "email":
        recipients = [r for r in (channel.config or {}).get("recipients", []) if r]
        if not recipients:
            raise DeliveryError("the channel has no recipients")
        for to in recipients:
            try:
                await mail.send(container.settings, to, message.title, message.text)
            except mail.MailError as exc:
                raise DeliveryError(str(exc)) from exc
        return
    secret = (
        orjson.loads(await container.sealer.open(channel.secret_sealed, channel_context(channel)))
        if channel.secret_sealed
        else {}
    )
    url = str(secret.get("url", ""))
    if channel.kind == "slack":
        emoji = {"opened": ":red_circle:", "resolved": ":large_green_circle:"}.get(
            message.event, ":large_blue_circle:"
        )
        body = orjson.dumps({"text": f"{emoji} {message.title}\n{message.text}"})
        await _post(container, url, body, {})
        return
    body = orjson.dumps(message.payload)
    headers = (
        {SIGNATURE_HEADER: sign(str(secret.get("secret", "")), body)}
        if secret.get("secret")
        else {}
    )
    await _post(container, url, body, {**headers, "x-dq-event": message.payload["event"]})


async def deliver_due(container: Container, session: AsyncSession, batch: int = 20) -> int:
    """Send due notifications; returns how many were handled."""
    now = datetime.now(UTC)
    rows = (
        await session.scalars(
            select(Notification)
            .where(Notification.status == "pending", Notification.next_attempt_at <= now)
            .order_by(Notification.next_attempt_at)
            .limit(batch)
            .with_for_update(skip_locked=True)
        )
    ).all()
    for n in rows:
        channel = await session.get(AlertChannel, n.channel_id)
        incident = await session.get(Incident, n.incident_id)
        if channel is None or incident is None or not channel.enabled:
            n.status, n.last_error = "skipped", "The channel was disabled or deleted"
            continue
        dataset = await session.get(Dataset, incident.dataset_id)
        n.attempts += 1
        try:
            await send(
                container, channel, render(container.settings.public_url, n, incident, dataset)
            )
        except DeliveryError as exc:
            n.last_error = str(exc)[:500]
            if n.attempts >= MAX_ATTEMPTS:
                n.status = "failed"
            else:
                n.next_attempt_at = now + timedelta(minutes=min(2 ** (n.attempts - 1), 60))
            NOTIFICATIONS.labels(channel.kind, "error").inc()
            log.warning(
                "notification failed",
                extra={"channel": channel.kind, "attempt": n.attempts, "error": n.last_error},
            )
            continue
        n.status, n.sent_at, n.last_error = "sent", datetime.now(UTC), None
        NOTIFICATIONS.labels(channel.kind, "sent").inc()
    await session.commit()
    return len(rows)


async def send_test(container: Container, channel: AlertChannel) -> None:
    """Send a test message right away (not queued); raises DeliveryError."""
    incident = Incident(
        id=uuid.uuid4(),
        project_id=channel.project_id,
        dataset_id=uuid.uuid4(),
        rule_id=uuid.uuid4(),
        key="test",
        status="open",
        severity="warn",
        title="Test notification from DataQuality",
        detail="If you can read this, the channel works.",
        occurrences=1,
        opened_at=datetime.now(UTC),
    )
    n = Notification(
        event="test", incident_id=incident.id, channel_id=channel.id, project_id=channel.project_id
    )
    await send(container, channel, render(container.settings.public_url, n, incident, None))
