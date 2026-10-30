"""Database connections. The password is sealed (envelope encryption) and never returned."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from dataquality.core.db import Base, TimestampMixin, new_id

CONNECTION_KINDS = ("postgresql", "mysql", "sqlite", "mssql")


class Connection(TimestampMixin, Base):
    __tablename__ = "connections"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_connections_project_name"),
        CheckConstraint(
            "kind IN ('postgresql', 'mysql', 'sqlite', 'mssql')", name="ck_connections_kind"
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
    # host, port, database, username, ssl_mode, default schema: nothing secret.
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    # The password, sealed with the record id as context; never returned by the API.
    secret_sealed: Mapped[bytes | None] = mapped_column(LargeBinary)
    # SQLite: the uploaded database file in object storage.
    file_key: Mapped[str | None] = mapped_column(String(300))
    file_name: Mapped[str | None] = mapped_column(String(300))
    file_size: Mapped[int | None] = mapped_column(Integer)
    # Scans that may run against this database at once (protects production databases).
    max_concurrent_scans: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_test_ok: Mapped[bool | None] = mapped_column()
    last_test_message: Mapped[str | None] = mapped_column(Text)
    server_version: Mapped[str | None] = mapped_column(String(200))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
