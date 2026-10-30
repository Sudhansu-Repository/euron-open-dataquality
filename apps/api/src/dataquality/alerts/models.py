"""Alerts: channels (where to send), rules (when), incidents (what is wrong now) and the
notification outbox (what was sent, exactly once per incident, channel and event)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from dataquality.core.db import Base, TimestampMixin, new_id

CHANNEL_KINDS = ("email", "slack", "webhook")
RULE_KINDS = ("check_failed", "score_below", "anomaly", "schema_change", "scan_failed")


class AlertChannel(TimestampMixin, Base):
    __tablename__ = "alert_channels"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_alert_channels_name"),
        CheckConstraint("kind IN ('email', 'slack', 'webhook')", name="ck_alert_channels_kind"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    # email: recipients. Nothing secret.
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    # slack: the webhook URL; webhook: the URL and the signing secret. Sealed.
    secret_sealed: Mapped[bytes | None] = mapped_column(LargeBinary)
    # Shown instead of the sealed URL: the host only.
    target_hint: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class AlertRule(TimestampMixin, Base):
    __tablename__ = "alert_rules"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('check_failed', 'score_below', 'anomaly', 'schema_change', 'scan_failed')",
            name="ck_alert_rules_kind",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    # None: every dataset in the project.
    dataset_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("datasets.id", ondelete="CASCADE")
    )
    # check_failed: the lowest severity that alerts (warn or error).
    min_severity: Mapped[str] = mapped_column(String(8), nullable=False, default="error")
    # score_below: the threshold in percent.
    threshold: Mapped[float | None] = mapped_column(Float)
    channel_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    notify_on_resolve: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Incident(Base):
    """One problem, open until a later scan shows it is gone. ``key`` identifies the problem
    (the rule plus the failing check or metric), so a problem that persists over many scans
    is one incident with many occurrences, and one notification."""

    __tablename__ = "incidents"
    __table_args__ = (
        CheckConstraint(
            "status IN ('open', 'acknowledged', 'resolved')", name="ck_incidents_status"
        ),
        # At most one unresolved incident per rule and problem.
        Index(
            "uq_incidents_open_key",
            "rule_id",
            "key",
            unique=True,
            postgresql_where="status <> 'resolved'",
        ),
        Index("ix_incidents_project_opened", "project_id", "opened_at"),
        Index("ix_incidents_dataset_status", "dataset_id", "status"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False
    )
    rule_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("alert_rules.id", ondelete="CASCADE"), nullable=False
    )
    key: Mapped[str] = mapped_column(String(240), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    severity: Mapped[str] = mapped_column(String(8), nullable=False, default="error")
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False, default="")
    first_scan_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    last_scan_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    occurrences: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution: Mapped[str | None] = mapped_column(String(32))


class Notification(Base):
    """The outbox. Written in the same transaction as the incident change; a delivery task
    sends it with retries. The unique key makes "notify once" a database fact."""

    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint("incident_id", "channel_id", "event", name="uq_notifications_once"),
        Index("ix_notifications_due", "next_attempt_at", postgresql_where="status = 'pending'"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    incident_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False
    )
    channel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("alert_channels.id", ondelete="CASCADE"), nullable=False
    )
    event: Mapped[str] = mapped_column(String(16), nullable=False)  # opened, resolved, test
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_error: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
