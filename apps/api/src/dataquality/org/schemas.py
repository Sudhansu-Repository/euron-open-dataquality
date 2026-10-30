"""Request and response models for organisation settings and self sign-up."""

from __future__ import annotations

from pydantic import Field, field_validator

from dataquality.core.net import check_url
from dataquality.core.schemas import ApiModel, Email


class PublicSettings(ApiModel):
    """What the sign-in page needs. No secrets, no AI endpoint."""

    site_name: str
    allow_signup: bool
    ai_enabled: bool
    # True on a fresh instance: the first sign-up creates the admin.
    needs_setup: bool = False


class AdminSettings(ApiModel):
    site_name: str
    allow_signup: bool
    ai_enabled: bool
    ai_base_url: str | None
    ai_model: str | None
    # The key itself is never returned, only whether one is stored.
    ai_has_key: bool


class SettingsUpdate(ApiModel):
    site_name: str | None = Field(None, min_length=1, max_length=80)
    allow_signup: bool | None = None
    ai_enabled: bool | None = None
    ai_base_url: str | None = Field(None, max_length=500)
    ai_model: str | None = Field(None, max_length=120)
    # A new key replaces the stored one; an empty string removes it.
    ai_api_key: str | None = Field(None, max_length=500)

    @field_validator("ai_base_url")
    @classmethod
    def _url(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return None if v is None else ""
        return check_url(v, "ai_base_url")


class SignupRequest(ApiModel):
    email: Email
    name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1, max_length=256)
