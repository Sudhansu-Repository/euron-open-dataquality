from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator

from dataquality.core.schemas import ApiModel, Email

ProjectRole = Literal["viewer", "editor", "owner"]
Scope = Literal["read", "scan", "push", "manage"]


class ProjectCreate(ApiModel):
    name: str = Field(min_length=1, max_length=120)
    slug: str | None = Field(None, max_length=64, pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")
    description: str = Field("", max_length=2000)


class ProjectUpdate(ApiModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    description: str | None = Field(None, max_length=2000)
    sample_size: int | None = Field(None, ge=0, le=200)
    retention_days: int | None = Field(None, ge=1, le=3650)
    ai_allow_samples: bool | None = None
    anomaly_sensitivity: float | None = Field(None, ge=2.0, le=10.0)


class ProjectOut(ApiModel):
    id: uuid.UUID
    name: str
    slug: str
    description: str
    sample_size: int
    retention_days: int
    ai_allow_samples: bool
    anomaly_sensitivity: float
    created_at: datetime
    role: ProjectRole = "viewer"
    datasets: int = 0
    score: float | None = None


class MemberOut(ApiModel):
    user_id: uuid.UUID
    email: str
    name: str
    role: ProjectRole
    created_at: datetime


class MemberAdd(ApiModel):
    email: Email
    role: ProjectRole = "viewer"


class MemberUpdate(ApiModel):
    role: ProjectRole


def _default_scopes() -> list[Scope]:
    return ["read", "scan"]


class ApiKeyCreate(ApiModel):
    name: str = Field(min_length=1, max_length=120)
    scopes: list[Scope] = Field(default_factory=_default_scopes, min_length=1)

    @field_validator("scopes")
    @classmethod
    def _unique(cls, v: list[str]) -> list[str]:
        return sorted(set(v))


class ApiKeyOut(ApiModel):
    id: uuid.UUID
    name: str
    prefix: str
    scopes: list[str]
    last_used_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime


class ApiKeyCreated(ApiKeyOut):
    key: str = Field(description="Shown once. Store it now; only a hash is kept")
