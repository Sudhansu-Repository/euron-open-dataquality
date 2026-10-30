from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import Field

from dataquality.core.schemas import ApiModel


class ScanRequest(ApiModel):
    # Retried requests with the same key return the same scan instead of starting another.
    idempotency_key: str | None = Field(None, max_length=128)
    profile: bool | None = Field(
        None, description="Profile columns too (defaults to the dataset's setting)"
    )


class ScanColumn(ApiModel):
    name: str
    type: str
    native: str | None = None


class ScanOut(ApiModel):
    id: uuid.UUID
    project_id: uuid.UUID
    dataset_id: uuid.UUID
    dataset_name: str | None = None
    status: str
    trigger: str
    attempt: int
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    duration_ms: int | None
    row_count: int | None
    score: float | None
    dimension_scores: dict[str, float]
    checks_total: int
    checks_passed: int
    checks_failed: int
    checks_warned: int
    checks_errored: int
    failed_rows: int
    duplicate_rows: int
    file_id: uuid.UUID | None
    columns: list[ScanColumn]
    error: str | None
    cancel_requested: bool


class ResultOut(ApiModel):
    id: uuid.UUID
    check_id: uuid.UUID | None
    check_name: str
    type: str
    column: str | None
    params: dict[str, Any]
    severity: str
    dimension: str
    status: str
    evaluated: int
    failed: int
    failed_pct: float
    observed: dict[str, Any]
    sample: list[dict[str, Any]]
    message: str
    error: str | None
    ms: float


class ScanDetail(ScanOut):
    results: list[ResultOut] = Field(default_factory=list)


class AnomalyOut(ApiModel):
    id: uuid.UUID
    dataset_id: uuid.UUID
    scan_id: uuid.UUID | None
    kind: str
    metric: str
    key: str
    value: float | None
    expected: float | None
    z: float | None
    direction: str
    explanation: str
    created_at: datetime


class PushResult(ApiModel):
    scan: ScanDetail
    records: int
    passed: bool = Field(description="True when no error-severity check failed")
