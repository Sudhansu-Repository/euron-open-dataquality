"""Scans and their results. The ``scans`` table is also the work queue: workers claim
queued rows with ``FOR UPDATE SKIP LOCKED`` and hold a lease while they run them."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from dataquality.core.db import Base, new_id

SCAN_STATUSES = ("queued", "running", "succeeded", "failed", "cancelled")
FINISHED = ("succeeded", "failed", "cancelled")


class Scan(Base):
    __tablename__ = "scans"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')",
            name="ck_scans_status",
        ),
        # A scheduled run exists once per dataset and slot, however many schedulers race.
        UniqueConstraint("dataset_id", "scheduled_for", name="uq_scans_schedule_slot"),
        UniqueConstraint("dataset_id", "idempotency_key", name="uq_scans_idempotency"),
        Index("ix_scans_queue", "queued_at", postgresql_where="status = 'queued'"),
        Index("ix_scans_lease", "lease_until", postgresql_where="status = 'running'"),
        Index("ix_scans_dataset_created", "dataset_id", "created_at"),
        Index("ix_scans_project_created", "project_id", "created_at"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False
    )
    connection_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")
    cancel_requested: Mapped[bool] = mapped_column(nullable=False, default=False)
    # manual, schedule, api, push
    trigger: Mapped[str] = mapped_column(String(16), nullable=False, default="manual")
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    idempotency_key: Mapped[str | None] = mapped_column(String(128))
    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    requested_by_key: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("api_keys.id", ondelete="SET NULL")
    )
    # The file version (or pushed batch) this scan reads.
    file_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    profile: Mapped[bool] = mapped_column(nullable=False, default=True)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    worker: Mapped[str | None] = mapped_column(String(120))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    queued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    row_count: Mapped[int | None] = mapped_column(BigInteger)
    score: Mapped[float | None] = mapped_column(Float)
    dimension_scores: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    checks_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    checks_passed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    checks_failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    checks_warned: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    checks_errored: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_rows: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    duplicate_rows: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    # The dataset's columns as this scan saw them: schema drift is the diff between scans.
    columns: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    error: Mapped[str | None] = mapped_column(Text)


class CheckResult(Base):
    __tablename__ = "check_results"
    __table_args__ = (
        Index("ix_check_results_scan", "scan_id"),
        Index("ix_check_results_check_scan", "check_id", "scan_id"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    scan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scans.id", ondelete="CASCADE"), nullable=False
    )
    check_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("checks.id", ondelete="SET NULL")
    )
    # A copy of the check as it was, so history survives edits and deletion.
    check_name: Mapped[str] = mapped_column(String(160), nullable=False)
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    column: Mapped[str | None] = mapped_column(String(128))
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    severity: Mapped[str] = mapped_column(String(8), nullable=False)
    dimension: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(8), nullable=False)
    evaluated: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    failed: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    failed_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    observed: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    sample: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    error: Mapped[str | None] = mapped_column(Text)
    ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)


class ScanProfile(Base):
    """The column profile a scan computed. Its own table: it is read only by the profile
    page, so dataset and scan lists never pull it."""

    __tablename__ = "scan_profiles"
    scan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scans.id", ondelete="CASCADE"), primary_key=True
    )
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("datasets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    row_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    rows_profiled: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sampled: Mapped[bool] = mapped_column(nullable=False, default=False)
    ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    columns: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class MetricPoint(Base):
    """History: one value per metric per scan (row count, score, a column's null rate...).
    Kept after scan results are purged, so trends and anomaly baselines outlive them."""

    __tablename__ = "metric_points"
    __table_args__ = (Index("ix_metric_points_series", "dataset_id", "metric", "key", "at"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False
    )
    scan_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    metric: Mapped[str] = mapped_column(String(32), nullable=False)
    key: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    value: Mapped[float] = mapped_column(Float, nullable=False)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Anomaly(Base):
    __tablename__ = "anomalies"
    __table_args__ = (
        Index("ix_anomalies_project_created", "project_id", "created_at"),
        Index("ix_anomalies_dataset_created", "dataset_id", "created_at"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False
    )
    scan_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scans.id", ondelete="SET NULL")
    )
    # metric (row count, null rate...) or schema (a column added, removed or retyped)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    metric: Mapped[str] = mapped_column(String(32), nullable=False)
    key: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    value: Mapped[float | None] = mapped_column(Float)
    expected: Mapped[float | None] = mapped_column(Float)
    z: Mapped[float | None] = mapped_column(Float)
    direction: Mapped[str] = mapped_column(String(8), nullable=False, default="none")
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class DailyScore(Base):
    """A pre-aggregated rollup per dataset and day, so dashboard trends never scan results."""

    __tablename__ = "daily_scores"
    __table_args__ = (Index("ix_daily_scores_project_day", "project_id", "day"),)
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("datasets.id", ondelete="CASCADE"), primary_key=True
    )
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    scans: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    score_sum: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    last_score: Mapped[float | None] = mapped_column(Float)
    failed_checks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rows_scanned: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
