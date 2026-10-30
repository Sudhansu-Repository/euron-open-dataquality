"""Alert channels, rules and incidents from the API's side."""

from __future__ import annotations

import secrets
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import orjson
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dataquality.alerts.delivery import DeliveryError, channel_context, send_test
from dataquality.alerts.models import AlertChannel, AlertRule, Incident, Notification
from dataquality.alerts.schemas import (
    ChannelCreated,
    ChannelIn,
    ChannelOut,
    ChannelUpdate,
    IncidentDetail,
    IncidentOut,
    NotificationOut,
    RuleIn,
    RuleUpdate,
)
from dataquality.audit.service import audit
from dataquality.core.container import Container
from dataquality.core.errors import AppError, ConflictError, NotFoundError
from dataquality.core.net import host_of
from dataquality.datasets.models import Dataset
from dataquality.projects.access import Principal


def channel_out(c: AlertChannel) -> ChannelOut:
    return ChannelOut(
        id=c.id,
        name=c.name,
        kind=c.kind,
        recipients=list((c.config or {}).get("recipients", [])),
        target_hint=c.target_hint,
        enabled=c.enabled,
        created_at=c.created_at,
    )


async def get_channel(
    session: AsyncSession, project_id: uuid.UUID, channel_id: uuid.UUID
) -> AlertChannel:
    c = await session.scalar(
        select(AlertChannel).where(
            AlertChannel.id == channel_id, AlertChannel.project_id == project_id
        )
    )
    if c is None:
        raise NotFoundError("Channel not found")
    return c


async def list_channels(session: AsyncSession, project_id: uuid.UUID) -> Sequence[AlertChannel]:
    return (
        await session.scalars(
            select(AlertChannel)
            .where(AlertChannel.project_id == project_id)
            .order_by(AlertChannel.name)
        )
    ).all()


async def _seal(container: Container, c: AlertChannel, url: str, secret: str | None) -> None:
    payload = {"url": url} | ({"secret": secret} if secret else {})
    c.secret_sealed = await container.sealer.seal(
        orjson.dumps(payload).decode(), channel_context(c)
    )
    c.target_hint = host_of(url)


async def create_channel(
    container: Container, session: AsyncSession, p: Principal, data: ChannelIn
) -> ChannelCreated:
    if await session.scalar(
        select(AlertChannel.id).where(
            AlertChannel.project_id == p.project_id, AlertChannel.name == data.name
        )
    ):
        raise ConflictError("A channel with this name exists", code="name_taken")
    c = AlertChannel(
        id=uuid.uuid4(),
        project_id=p.project_id,
        name=data.name.strip(),
        kind=data.kind,
        enabled=data.enabled,
    )
    signing = None
    if data.kind == "email":
        c.config = {"recipients": list(data.recipients)}
        c.target_hint = ", ".join(data.recipients[:3]) + ("..." if len(data.recipients) > 3 else "")
    else:
        if data.kind == "webhook":
            signing = data.secret or secrets.token_urlsafe(32)
        await _seal(container, c, str(data.url), signing)
    session.add(c)
    audit(
        session, p.actor, "alert_channel.created", "alert_channel", c.id, name=c.name, kind=c.kind
    )
    await session.commit()
    await session.refresh(c)
    return ChannelCreated(
        **channel_out(c).model_dump(), signing_secret=signing if data.secret is None else None
    )


async def update_channel(
    container: Container, session: AsyncSession, p: Principal, c: AlertChannel, data: ChannelUpdate
) -> AlertChannel:
    changes = data.model_dump(exclude_unset=True)
    if changes.get("name"):
        c.name = changes["name"].strip()
    if changes.get("enabled") is not None:
        c.enabled = bool(changes["enabled"])
    if c.kind == "email" and data.recipients is not None:
        if not data.recipients:
            raise AppError("An email channel needs at least one recipient", code="no_recipients")
        c.config = {"recipients": list(data.recipients)}
        c.target_hint = ", ".join(data.recipients[:3]) + ("..." if len(data.recipients) > 3 else "")
    if c.kind != "email" and (data.url or data.secret):
        current = (
            orjson.loads(await container.sealer.open(c.secret_sealed, channel_context(c)))
            if c.secret_sealed
            else {}
        )
        await _seal(
            container, c, data.url or current.get("url", ""), data.secret or current.get("secret")
        )
    audit(session, p.actor, "alert_channel.updated", "alert_channel", c.id, fields=sorted(changes))
    await session.commit()
    await session.refresh(c)
    return c


async def delete_channel(session: AsyncSession, p: Principal, c: AlertChannel) -> None:
    audit(session, p.actor, "alert_channel.deleted", "alert_channel", c.id, name=c.name)
    await session.delete(c)
    await session.commit()


async def test_channel(container: Container, c: AlertChannel) -> str:
    try:
        await send_test(container, c)
    except DeliveryError as exc:
        raise AppError(
            f"The test message was not delivered: {exc}", code="delivery_failed"
        ) from exc
    return "Test message sent"


async def _validate_rule(
    session: AsyncSession, p: Principal, dataset_id: uuid.UUID | None, channels: list[uuid.UUID]
) -> None:
    if dataset_id and not await session.scalar(
        select(Dataset.id).where(Dataset.id == dataset_id, Dataset.project_id == p.project_id)
    ):
        raise NotFoundError("Dataset not found")
    if channels:
        found = set(
            (
                await session.scalars(
                    select(AlertChannel.id).where(
                        AlertChannel.id.in_(channels), AlertChannel.project_id == p.project_id
                    )
                )
            ).all()
        )
        if found != set(channels):
            raise NotFoundError("A channel in the list does not exist in this project")


async def list_rules(session: AsyncSession, project_id: uuid.UUID) -> Sequence[AlertRule]:
    return (
        await session.scalars(
            select(AlertRule)
            .where(AlertRule.project_id == project_id)
            .order_by(AlertRule.created_at)
        )
    ).all()


async def get_rule(session: AsyncSession, project_id: uuid.UUID, rule_id: uuid.UUID) -> AlertRule:
    r = await session.scalar(
        select(AlertRule).where(AlertRule.id == rule_id, AlertRule.project_id == project_id)
    )
    if r is None:
        raise NotFoundError("Rule not found")
    return r


async def create_rule(session: AsyncSession, p: Principal, data: RuleIn) -> AlertRule:
    await _validate_rule(session, p, data.dataset_id, data.channel_ids)
    r = AlertRule(
        project_id=p.project_id,
        name=data.name.strip(),
        kind=data.kind,
        dataset_id=data.dataset_id,
        min_severity=data.min_severity,
        threshold=data.threshold,
        channel_ids=[str(c) for c in data.channel_ids],
        notify_on_resolve=data.notify_on_resolve,
        enabled=data.enabled,
    )
    session.add(r)
    await session.flush()
    audit(session, p.actor, "alert_rule.created", "alert_rule", r.id, name=r.name, kind=r.kind)
    await session.commit()
    return r


async def update_rule(
    session: AsyncSession, p: Principal, r: AlertRule, data: RuleUpdate
) -> AlertRule:
    changes = data.model_dump(exclude_unset=True)
    await _validate_rule(session, p, changes.get("dataset_id"), data.channel_ids or [])
    for field in ("name", "min_severity", "threshold", "notify_on_resolve", "enabled"):
        if field in changes and (changes[field] is not None or field == "threshold"):
            setattr(r, field, changes[field])
    if "dataset_id" in changes:
        r.dataset_id = changes["dataset_id"]
    if data.channel_ids is not None:
        r.channel_ids = [str(c) for c in data.channel_ids]
    if r.kind == "score_below" and r.threshold is None:
        raise AppError("A score rule needs a threshold", code="threshold_required")
    audit(session, p.actor, "alert_rule.updated", "alert_rule", r.id, fields=sorted(changes))
    await session.commit()
    await session.refresh(r)
    return r


async def delete_rule(session: AsyncSession, p: Principal, r: AlertRule) -> None:
    audit(session, p.actor, "alert_rule.deleted", "alert_rule", r.id, name=r.name)
    await session.delete(r)
    await session.commit()


async def incident_outs(session: AsyncSession, rows: Sequence[Incident]) -> list[IncidentOut]:
    ds = {i.dataset_id for i in rows}
    rs = {i.rule_id for i in rows}
    names = (
        dict(
            (
                await session.execute(select(Dataset.id, Dataset.name).where(Dataset.id.in_(ds)))
            ).all()
        )
        if ds
        else {}
    )
    rules = (
        {
            r.id: r
            for r in (await session.scalars(select(AlertRule).where(AlertRule.id.in_(rs)))).all()
        }
        if rs
        else {}
    )
    return [
        IncidentOut.model_validate(i).model_copy(
            update={
                "dataset_name": names.get(i.dataset_id),
                "rule_name": rules[i.rule_id].name if i.rule_id in rules else None,
                "rule_kind": rules[i.rule_id].kind if i.rule_id in rules else None,
            }
        )
        for i in rows
    ]


async def list_incidents(
    session: AsyncSession,
    project_id: uuid.UUID,
    status: str | None,
    dataset_id: uuid.UUID | None,
    limit: int,
) -> list[IncidentOut]:
    stmt = select(Incident).where(Incident.project_id == project_id)
    if status == "active":
        stmt = stmt.where(Incident.status != "resolved")
    elif status:
        stmt = stmt.where(Incident.status == status)
    if dataset_id:
        stmt = stmt.where(Incident.dataset_id == dataset_id)
    rows = (await session.scalars(stmt.order_by(Incident.last_seen_at.desc()).limit(limit))).all()
    return await incident_outs(session, rows)


async def get_incident(
    session: AsyncSession, project_id: uuid.UUID, incident_id: uuid.UUID
) -> Incident:
    i = await session.scalar(
        select(Incident).where(Incident.id == incident_id, Incident.project_id == project_id)
    )
    if i is None:
        raise NotFoundError("Incident not found")
    return i


async def incident_detail(session: AsyncSession, i: Incident) -> IncidentDetail:
    base = (await incident_outs(session, [i]))[0]
    rows = (
        await session.execute(
            select(Notification, AlertChannel.name)
            .join(AlertChannel, AlertChannel.id == Notification.channel_id, isouter=True)
            .where(Notification.incident_id == i.id)
            .order_by(Notification.created_at)
        )
    ).all()
    notes = [
        NotificationOut.model_validate(n).model_copy(update={"channel_name": name})
        for n, name in rows
    ]
    return IncidentDetail(**base.model_dump(), notifications=notes)


async def acknowledge(session: AsyncSession, p: Principal, i: Incident) -> Incident:
    if i.status == "resolved":
        raise ConflictError("The incident is already resolved", code="incident_resolved")
    i.status = "acknowledged"
    i.acknowledged_at = datetime.now(UTC)
    i.acknowledged_by = p.user_id
    audit(session, p.actor, "incident.acknowledged", "incident", i.id)
    await session.commit()
    return i


async def resolve(session: AsyncSession, p: Principal, i: Incident) -> Incident:
    if i.status == "resolved":
        return i
    i.status = "resolved"
    i.resolved_at = datetime.now(UTC)
    i.resolution = "manual"
    audit(session, p.actor, "incident.resolved", "incident", i.id)
    await session.commit()
    return i
