"""Projects group datasets, connections, checks and alerts; members hold a role in each."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from dataquality.core.db import Base, TimestampMixin, new_id

PROJECT_ROLES = ("viewer", "editor", "owner")


class Project(TimestampMixin, Base):
    __tablename__ = "projects"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Failing rows kept per check in a scan result (0 keeps none: counts only).
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    # Scan results older than this are purged (the history metrics stay).
    retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=90)
    # Whether the optional AI assistant may see sample values (it always sees names and stats).
    ai_allow_samples: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Robust z-score above which a metric is anomalous.
    anomaly_sensitivity: Mapped[float] = mapped_column(nullable=False, default=3.5)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )


class ProjectMember(TimestampMixin, Base):
    __tablename__ = "project_members"
    __table_args__ = (
        CheckConstraint("role IN ('viewer', 'editor', 'owner')", name="ck_member_role"),
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)


class ApiKey(TimestampMixin, Base):
    """A project's key for other applications and CI. Only a peppered hash is stored."""

    __tablename__ = "api_keys"
    __table_args__ = (UniqueConstraint("prefix", name="uq_api_keys_prefix"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    secret_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    scopes: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
