"""Turn a finished scan into incidents and notifications, in the scan's own transaction.

For every enabled rule that covers the dataset, the scan yields a set of *problems*, each
with a stable key (``<dataset>:check:<check id>``, ``<dataset>:score``...):

* a problem with no open incident opens one and queues one notification per channel;
* a problem that already has an open incident only counts another occurrence (no new
  notification: the team heard about it already);
* an open incident whose problem is gone resolves, and queues a "resolved" notification
  when the rule asks for one.

The partial unique index on open incidents and the unique (incident, channel, event) key
on notifications make "one incident, one notification" hold even when two scans of the
same dataset finish at the same moment.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import or_, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from dataquality.alerts.models import AlertChannel, AlertRule, Incident, Notification
from dataquality.datasets.models import Dataset
from dataquality.scans.models import Anomaly, CheckResult, Scan

SEVERITY_RANK = {"warn": 0, "error": 1}


@dataclass(frozen=True)
class Problem:
    key: str
    title: str
    detail: str
    severity: str


def problems_for(
    rule: AlertRule,
    dataset: Dataset,
    scan: Scan,
    results: Sequence[CheckResult],
    anomalies: Sequence[Anomaly],
) -> list[Problem] | None:
    """The rule's problems in this scan; None when the scan says nothing about the rule
    (a failed scan cannot clear a check failure it never measured)."""
    prefix = f"{dataset.id}:"
    if rule.kind == "scan_failed":
        if scan.status == "failed":
            return [
                Problem(
                    prefix + "scan_failed",
                    f"Scan of {dataset.name} failed",
                    scan.error or "The scan failed",
                    "error",
                )
            ]
        return [] if scan.status == "succeeded" else None
    if scan.status != "succeeded":
        return None
    if rule.kind == "check_failed":
        floor = SEVERITY_RANK.get(rule.min_severity, 1)
        return [
            Problem(
                f"{prefix}check:{r.check_id or r.check_name}",
                f"{dataset.name}: {r.check_name} failed",
                r.message,
                r.severity,
            )
            for r in results
            if r.status == "fail" and SEVERITY_RANK.get(r.severity, 1) >= floor
        ]
    if rule.kind == "score_below":
        if scan.score is not None and rule.threshold is not None and scan.score < rule.threshold:
            return [
                Problem(
                    prefix + "score",
                    f"{dataset.name}: quality score {scan.score:.1f}% is below {rule.threshold:g}%",
                    "Dimension scores: "
                    + ", ".join(f"{k} {v:.1f}%" for k, v in (scan.dimension_scores or {}).items()),
                    "error",
                )
            ]
        return []
    if rule.kind in ("anomaly", "schema_change"):
        kind = "metric" if rule.kind == "anomaly" else "schema"
        return [
            Problem(
                f"{prefix}{kind}:{a.metric}:{a.key}",
                f"{dataset.name}: {a.explanation.split(';')[0]}",
                a.explanation,
                "warn" if kind == "metric" else "error",
            )
            for a in anomalies
            if a.kind == kind
        ]
    return None


async def evaluate(
    session: AsyncSession,
    dataset: Dataset,
    scan: Scan,
    results: Sequence[CheckResult],
    anomalies: Sequence[Anomaly],
) -> tuple[int, int]:
    """Open and resolve incidents for this scan. Returns (opened, resolved)."""
    rules = (
        await session.scalars(
            select(AlertRule).where(
                AlertRule.project_id == dataset.project_id,
                AlertRule.enabled.is_(True),
                or_(AlertRule.dataset_id.is_(None), AlertRule.dataset_id == dataset.id),
            )
        )
    ).all()
    if not rules:
        return 0, 0
    channel_ids = {uuid.UUID(c) for r in rules for c in r.channel_ids or []}
    enabled = set()
    if channel_ids:
        enabled = set(
            (
                await session.scalars(
                    select(AlertChannel.id).where(
                        AlertChannel.id.in_(channel_ids),
                        AlertChannel.project_id == dataset.project_id,
                        AlertChannel.enabled.is_(True),
                    )
                )
            ).all()
        )
    now = datetime.now(UTC)
    opened = resolved = 0
    for rule in rules:
        found = problems_for(rule, dataset, scan, results, anomalies)
        if found is None:
            continue
        channels = [uuid.UUID(c) for c in rule.channel_ids or [] if uuid.UUID(c) in enabled]
        current = {
            i.key: i
            for i in (
                await session.scalars(
                    select(Incident)
                    .where(
                        Incident.rule_id == rule.id,
                        Incident.dataset_id == dataset.id,
                        Incident.status != "resolved",
                    )
                    .with_for_update()
                )
            ).all()
        }
        keys = {p.key for p in found}
        for problem in found:
            incident = current.get(problem.key)
            if incident is not None:
                incident.occurrences += 1
                incident.last_seen_at = now
                incident.last_scan_id = scan.id
                incident.detail = problem.detail
                continue
            new_id = await session.scalar(
                insert(Incident)
                .values(
                    id=uuid.uuid4(),
                    project_id=dataset.project_id,
                    dataset_id=dataset.id,
                    rule_id=rule.id,
                    key=problem.key,
                    status="open",
                    severity=problem.severity,
                    title=problem.title[:300],
                    detail=problem.detail,
                    first_scan_id=scan.id,
                    last_scan_id=scan.id,
                    opened_at=now,
                    last_seen_at=now,
                )
                .on_conflict_do_nothing(
                    index_elements=["rule_id", "key"], index_where=text("status <> 'resolved'")
                )
                .returning(Incident.id)
            )
            if new_id is None:
                continue  # another scan opened it a moment ago
            opened += 1
            await _notify(session, dataset.project_id, new_id, channels, "opened")
        for key, incident in current.items():
            if key in keys:
                continue
            incident.status = "resolved"
            incident.resolved_at = now
            incident.resolution = "cleared"
            incident.last_scan_id = scan.id
            resolved += 1
            if rule.notify_on_resolve:
                await _notify(session, dataset.project_id, incident.id, channels, "resolved")
    return opened, resolved


async def _notify(
    session: AsyncSession,
    project_id: uuid.UUID,
    incident_id: uuid.UUID,
    channels: list[uuid.UUID],
    event: str,
) -> None:
    for channel_id in channels:
        await session.execute(
            insert(Notification)
            .values(
                id=uuid.uuid4(),
                project_id=project_id,
                incident_id=incident_id,
                channel_id=channel_id,
                event=event,
            )
            .on_conflict_do_nothing(constraint="uq_notifications_once")
        )
