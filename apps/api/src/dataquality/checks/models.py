"""Checks: the rules a dataset must satisfy. Parameters are validated per type
(``engine.spec``) before they are stored, so a stored check is always runnable."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Boolean, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from dataquality.core.db import Base, TimestampMixin, new_id


class Check(TimestampMixin, Base):
    __tablename__ = "checks"
    __table_args__ = (UniqueConstraint("dataset_id", "name", name="uq_checks_dataset_name"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("datasets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    column: Mapped[str | None] = mapped_column(String(128))
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    filter_sql: Mapped[str | None] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(8), nullable=False, default="error")
    tolerance: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    dimension: Mapped[str] = mapped_column(String(16), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # manual, suggested, ai, yaml: where the check came from.
    origin: Mapped[str] = mapped_column(String(16), nullable=False, default="manual")
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
