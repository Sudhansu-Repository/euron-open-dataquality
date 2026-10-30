from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter
from pydantic import Field, field_validator, model_validator

from dataquality.core.net import check_url
from dataquality.core.schemas import ApiModel

DatasetKind = Literal["table", "query", "file", "rest", "push"]


def _cron(v: str | None) -> str | None:
    if v is None or not v.strip():
        return None
    v = " ".join(v.split())
    if not croniter.is_valid(v) or len(v.split()) != 5:
        raise ValueError(
            "use a five-field cron expression, such as '0 6 * * *' (every day at 06:00)"
        )
    return v


def _tz(v: str) -> str:
    try:
        ZoneInfo(v)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"unknown time zone {v!r}; use an IANA name such as Asia/Kolkata") from exc
    return v


class _Common(ApiModel):
    description: str | None = Field(None, max_length=2000)
    filter_sql: str | None = Field(None, max_length=2000)
    masked_columns: list[str] | None = Field(None, max_length=200)
    tags: list[str] | None = Field(None, max_length=20)
    profile_enabled: bool | None = None
    scan_timeout_s: int | None = Field(None, ge=10, le=86_400)
    schedule_cron: str | None = Field(None, max_length=120)
    schedule_tz: str | None = Field(None, max_length=64)
    schedule_enabled: bool | None = None

    @field_validator("schedule_cron")
    @classmethod
    def _check_cron(cls, v: str | None) -> str | None:
        return _cron(v)

    @field_validator("schedule_tz")
    @classmethod
    def _check_tz(cls, v: str | None) -> str | None:
        return _tz(v) if v else None


class RestOptions(ApiModel):
    url: str = Field(min_length=8, max_length=2000)
    records_path: str | None = Field(None, max_length=200)

    @field_validator("url")
    @classmethod
    def _url(cls, v: str) -> str:
        return check_url(v)


class DatasetCreate(_Common):
    name: str = Field(min_length=1, max_length=120)
    kind: Literal["table", "query", "rest", "push"]
    connection_id: uuid.UUID | None = None
    schema_name: str | None = Field(None, max_length=128)
    table_name: str | None = Field(None, max_length=128)
    query_sql: str | None = Field(None, max_length=20_000)
    rest: RestOptions | None = None
    # REST request headers (Authorization...). Sealed; never returned.
    rest_headers: dict[str, str] | None = Field(None, max_length=20)

    @model_validator(mode="after")
    def _by_kind(self) -> DatasetCreate:
        if self.kind in ("table", "query") and self.connection_id is None:
            raise ValueError("a table or query dataset needs a connection")
        if self.kind == "table" and not self.table_name:
            raise ValueError("name the table")
        if self.kind == "query" and not (self.query_sql or "").strip():
            raise ValueError("write the query")
        if self.kind == "rest" and self.rest is None:
            raise ValueError("a REST dataset needs a URL")
        return self


class DatasetUpdate(_Common):
    name: str | None = Field(None, min_length=1, max_length=120)
    schema_name: str | None = Field(None, max_length=128)
    table_name: str | None = Field(None, max_length=128)
    query_sql: str | None = Field(None, max_length=20_000)
    rest: RestOptions | None = None
    rest_headers: dict[str, str] | None = Field(None, max_length=20)
    options: dict[str, Any] | None = None


class DatasetOut(ApiModel):
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    slug: str
    description: str
    kind: str
    connection_id: uuid.UUID | None
    connection_name: str | None = None
    file_name: str | None = None
    file_format: str | None = None
    schema_name: str | None
    table_name: str | None
    query_sql: str | None
    options: dict[str, Any]
    has_secret: bool = False
    current_file_id: uuid.UUID | None
    filter_sql: str | None
    masked_columns: list[str]
    tags: list[str]
    profile_enabled: bool
    scan_timeout_s: int
    schedule_cron: str | None
    schedule_tz: str
    schedule_enabled: bool
    next_run_at: datetime | None
    last_scan_id: uuid.UUID | None
    last_scan_at: datetime | None
    last_status: str | None
    last_score: float | None
    last_row_count: int | None
    last_failed_checks: int | None
    checks: int = 0
    open_incidents: int = 0
    created_at: datetime
    updated_at: datetime


class FileOut(ApiModel):
    id: uuid.UUID
    version: int
    filename: str
    format: str
    size: int
    sha256: str
    records: int | None
    created_at: datetime


class PreviewOut(ApiModel):
    columns: list[dict[str, Any]]
    rows: list[dict[str, Any]]


class ValueCount(ApiModel):
    value: Any
    count: int


class ShapeCount(ApiModel):
    shape: str
    count: int


class HistogramBin(ApiModel):
    low: float
    high: float
    count: int


class ColumnProfileOut(ApiModel):
    name: str
    logical: str
    native: str
    rows: int
    nulls: int
    blanks: int
    distinct: int | None
    min: Any = None
    max: Any = None
    mean: float | None
    stddev: float | None
    quantiles: dict[str, Any]
    histogram: list[HistogramBin]
    top_values: list[ValueCount]
    shapes: list[ShapeCount]
    min_length: int | None
    max_length: int | None
    mean_length: float | None
    semantic: dict[str, float]


class ProfileOut(ApiModel):
    scan_id: uuid.UUID
    row_count: int
    rows_profiled: int
    sampled: bool
    ms: float
    columns: list[ColumnProfileOut]
    created_at: datetime


class SuggestionOut(ApiModel):
    key: str
    type: str
    column: str | None
    params: dict[str, Any]
    severity: str
    reason: str
    exists: bool = False


class PushRequest(ApiModel):
    records: list[dict[str, Any]] = Field(min_length=1)


class SchemaChange(ApiModel):
    column: str
    change: Literal["added", "removed", "retyped"]
    before: str | None
    after: str | None


class MetricSeries(ApiModel):
    metric: str
    key: str
    points: list[dict[str, Any]]
