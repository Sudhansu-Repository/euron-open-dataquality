from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator

from dataquality.core.net import as_ip, canonical_host, is_forbidden_ip
from dataquality.core.schemas import ApiModel

ServerKind = Literal["postgresql", "mysql", "mssql"]
SslMode = Literal["disable", "prefer", "require", "verify-full"]


def _host(v: str) -> str:
    host = canonical_host(v)
    if not host or any(c in host for c in "/?#@ "):
        raise ValueError("enter a host name or IP address, without a scheme or path")
    ip = as_ip(host)
    if ip is not None and is_forbidden_ip(ip):
        raise ValueError("link-local and instance metadata addresses are not allowed")
    return host


class ServerConnection(ApiModel):
    """A database server. The password is write-only: it is sealed and never returned."""

    name: str = Field(min_length=1, max_length=120)
    kind: ServerKind
    host: str = Field(min_length=1, max_length=255)
    port: int | None = Field(None, ge=1, le=65535)
    database: str = Field(min_length=1, max_length=128)
    username: str = Field(min_length=1, max_length=128)
    password: str | None = Field(None, max_length=1000)
    ssl_mode: SslMode = "prefer"
    default_schema: str | None = Field(None, max_length=128)
    max_concurrent_scans: int = Field(2, ge=1, le=20)

    @field_validator("host")
    @classmethod
    def _check_host(cls, v: str) -> str:
        return _host(v)


class ConnectionUpdate(ApiModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    host: str | None = Field(None, min_length=1, max_length=255)
    port: int | None = Field(None, ge=1, le=65535)
    database: str | None = Field(None, min_length=1, max_length=128)
    username: str | None = Field(None, min_length=1, max_length=128)
    # A new password replaces the sealed one; omit it to keep the current one.
    password: str | None = Field(None, max_length=1000)
    ssl_mode: SslMode | None = None
    default_schema: str | None = Field(None, max_length=128)
    max_concurrent_scans: int | None = Field(None, ge=1, le=20)

    @field_validator("host")
    @classmethod
    def _check(cls, v: str | None) -> str | None:
        return _host(v) if v is not None else None


class ConnectionOut(ApiModel):
    id: uuid.UUID
    name: str
    kind: str
    host: str | None = None
    port: int | None = None
    database: str | None = None
    username: str | None = None
    ssl_mode: str | None = None
    default_schema: str | None = None
    has_password: bool = False
    file_name: str | None = None
    file_size: int | None = None
    max_concurrent_scans: int
    last_tested_at: datetime | None
    last_test_ok: bool | None
    last_test_message: str | None
    server_version: str | None
    datasets: int = 0
    created_at: datetime


class TestResult(ApiModel):
    ok: bool
    message: str
    server_version: str | None = None
    tables: int | None = None
    ms: float


class TableOut(ApiModel):
    schema_name: str | None
    name: str
    kind: str
