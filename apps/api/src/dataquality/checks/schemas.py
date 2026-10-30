from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import Field

from dataquality.core.schemas import ApiModel
from dataquality.engine.spec import CheckType, Dimension, Severity, Tolerance


class CheckIn(ApiModel):
    name: str | None = Field(
        None, max_length=160, description="Defaults to a name built from the type and column"
    )
    description: str = Field("", max_length=2000)
    type: CheckType
    column: str | None = Field(None, max_length=128)
    params: dict[str, Any] = Field(default_factory=dict)
    filter_sql: str | None = Field(None, max_length=2000)
    severity: Severity = Severity.ERROR
    tolerance: Tolerance = Field(default_factory=Tolerance)
    dimension: Dimension | None = None
    enabled: bool = True


class CheckUpdate(ApiModel):
    name: str | None = Field(None, min_length=1, max_length=160)
    description: str | None = Field(None, max_length=2000)
    column: str | None = Field(None, max_length=128)
    params: dict[str, Any] | None = None
    filter_sql: str | None = Field(None, max_length=2000)
    severity: Severity | None = None
    tolerance: Tolerance | None = None
    dimension: Dimension | None = None
    enabled: bool | None = None


class LastResult(ApiModel):
    scan_id: uuid.UUID
    status: str
    evaluated: int
    failed: int
    failed_pct: float
    message: str


class CheckOut(ApiModel):
    id: uuid.UUID
    dataset_id: uuid.UUID
    name: str
    description: str
    type: str
    column: str | None
    params: dict[str, Any]
    filter_sql: str | None
    severity: str
    tolerance: dict[str, Any]
    dimension: str
    enabled: bool
    origin: str
    created_at: datetime
    updated_at: datetime
    last: LastResult | None = None


class BulkCreate(ApiModel):
    checks: list[CheckIn] = Field(min_length=1, max_length=500)
    origin: str = Field("manual", pattern=r"^(manual|suggested|ai|yaml)$")


class BulkResult(ApiModel):
    created: int
    updated: int = 0
    skipped: list[str] = Field(default_factory=list)
    removed: list[str] = Field(default_factory=list)
    checks: list[CheckOut] = Field(default_factory=list)


class YamlIn(ApiModel):
    yaml: str = Field(min_length=1, max_length=1_000_000)
    # Remove checks that the file no longer lists (true checks-as-code).
    prune: bool = False


class DraftRequest(ApiModel):
    prompt: str = Field(min_length=3, max_length=1000)


class DraftOut(ApiModel):
    check: CheckIn
    explanation: str
