"""Datasets: what gets profiled and checked. A table or query in a connection, an uploaded
file (with versions), a REST endpoint, or records pushed by an application."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
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

DATASET_KINDS = ("table", "query", "file", "rest", "push")
FILE_FORMATS = ("csv", "tsv", "json", "ndjson", "parquet", "xlsx")


class Dataset(TimestampMixin, Base):
    __tablename__ = "datasets"
    __table_args__ = (
        UniqueConstraint("project_id", "slug", name="uq_datasets_project_slug"),
        CheckConstraint(
            "kind IN ('table', 'query', 'file', 'rest', 'push')", name="ck_datasets_kind"
        ),
        Index("ix_datasets_due", "next_run_at", postgresql_where="schedule_enabled"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    kind: Mapped[str] = mapped_column(String(8), nullable=False)
    connection_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("connections.id", ondelete="RESTRICT"), index=True
    )
    schema_name: Mapped[str | None] = mapped_column(String(128))
    table_name: Mapped[str | None] = mapped_column(String(128))
    query_sql: Mapped[str | None] = mapped_column(Text)
    # Files: the format and reader options (sheet, delimiter); REST: url, records path.
    options: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    # REST: the request headers (an Authorization header, say), sealed.
    secret_sealed: Mapped[bytes | None] = mapped_column(LargeBinary)
    current_file_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    filter_sql: Mapped[str | None] = mapped_column(Text)
    masked_columns: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    tags: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    profile_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    scan_timeout_s: Mapped[int] = mapped_column(Integer, nullable=False, default=1800)
    schedule_cron: Mapped[str | None] = mapped_column(String(120))
    schedule_tz: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
    schedule_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # The latest finished scan, denormalised for the dataset list and the dashboard.
    last_scan_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    last_scan_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_status: Mapped[str | None] = mapped_column(String(16))
    last_score: Mapped[float | None] = mapped_column(Float)
    last_row_count: Mapped[int | None] = mapped_column(BigInteger)
    last_failed_checks: Mapped[int | None] = mapped_column(Integer)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )


class DatasetFile(Base):
    """One uploaded version of a file dataset (or one pushed batch)."""

    __tablename__ = "dataset_files"
    __table_args__ = (UniqueConstraint("dataset_id", "version", name="uq_dataset_files_version"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    filename: Mapped[str] = mapped_column(String(300), nullable=False)
    format: Mapped[str] = mapped_column(String(8), nullable=False)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(300), nullable=False)
    records: Mapped[int | None] = mapped_column(BigInteger)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
