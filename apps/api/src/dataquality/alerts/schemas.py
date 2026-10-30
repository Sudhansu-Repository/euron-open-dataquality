from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator, model_validator

from dataquality.core.net import check_url
from dataquality.core.schemas import ApiModel, Email

ChannelKind = Literal["email", "slack", "webhook"]
RuleKind = Literal["check_failed", "score_below", "anomaly", "schema_change", "scan_failed"]


class ChannelIn(ApiModel):
    name: str = Field(min_length=1, max_length=120)
    kind: ChannelKind
    recipients: list[Email] = Field(default_factory=list, max_length=50)
    # Slack incoming webhook URL, or the webhook endpoint. Sealed, never returned.
    url: str | None = Field(None, max_length=2000)
    # Webhook signing secret (HMAC-SHA256). Generated when omitted.
    secret: str | None = Field(None, min_length=16, max_length=200)
    enabled: bool = True

    @field_validator("url")
    @classmethod
    def _url(cls, v: str | None) -> str | None:
        return check_url(v) if v else None

    @model_validator(mode="after")
    def _by_kind(self) -> ChannelIn:
        if self.kind == "email" and not self.recipients:
            raise ValueError("an email channel needs at least one recipient")
        if self.kind in ("slack", "webhook") and not self.url:
            raise ValueError(f"a {self.kind} channel needs a URL")
        return self


class ChannelUpdate(ApiModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    recipients: list[Email] | None = Field(None, max_length=50)
    url: str | None = Field(None, max_length=2000)
    secret: str | None = Field(None, min_length=16, max_length=200)
    enabled: bool | None = None

    @field_validator("url")
    @classmethod
    def _url(cls, v: str | None) -> str | None:
        return check_url(v) if v else None


class ChannelOut(ApiModel):
    id: uuid.UUID
    name: str
    kind: str
    recipients: list[str] = Field(default_factory=list)
    target_hint: str
    enabled: bool
    created_at: datetime


class ChannelCreated(ChannelOut):
    signing_secret: str | None = Field(None, description="Webhook channels: shown once")


class RuleIn(ApiModel):
    name: str = Field(min_length=1, max_length=120)
    kind: RuleKind
    dataset_id: uuid.UUID | None = None
    min_severity: Literal["warn", "error"] = "error"
    threshold: float | None = Field(None, ge=0, le=100)
    channel_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)
    notify_on_resolve: bool = True
    enabled: bool = True

    @model_validator(mode="after")
    def _threshold(self) -> RuleIn:
        if self.kind == "score_below" and self.threshold is None:
            raise ValueError("a score rule needs a threshold")
        return self


class RuleUpdate(ApiModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    dataset_id: uuid.UUID | None = None
    min_severity: Literal["warn", "error"] | None = None
    threshold: float | None = Field(None, ge=0, le=100)
    channel_ids: list[uuid.UUID] | None = Field(None, max_length=20)
    notify_on_resolve: bool | None = None
    enabled: bool | None = None


class RuleOut(ApiModel):
    id: uuid.UUID
    name: str
    kind: str
    dataset_id: uuid.UUID | None
    min_severity: str
    threshold: float | None
    channel_ids: list[str]
    notify_on_resolve: bool
    enabled: bool
    created_at: datetime


class NotificationOut(ApiModel):
    id: uuid.UUID
    channel_id: uuid.UUID
    channel_name: str | None = None
    event: str
    status: str
    attempts: int
    last_error: str | None
    sent_at: datetime | None
    created_at: datetime


class IncidentOut(ApiModel):
    id: uuid.UUID
    dataset_id: uuid.UUID
    dataset_name: str | None = None
    rule_id: uuid.UUID
    rule_name: str | None = None
    rule_kind: str | None = None
    status: str
    severity: str
    title: str
    detail: str
    occurrences: int
    first_scan_id: uuid.UUID | None
    last_scan_id: uuid.UUID | None
    opened_at: datetime
    last_seen_at: datetime
    acknowledged_at: datetime | None
    resolved_at: datetime | None
    resolution: str | None


class IncidentDetail(IncidentOut):
    notifications: list[NotificationOut] = Field(default_factory=list)


class ExplainOut(ApiModel):
    explanation: str
    model: str
