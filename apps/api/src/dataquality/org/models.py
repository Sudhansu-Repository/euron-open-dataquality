"""SQLAlchemy models for the org domain: one row of organisation-wide settings."""

from __future__ import annotations

from sqlalchemy import Boolean, CheckConstraint, Integer, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

from dataquality.core.db import Base, TimestampMixin

SINGLETON_ID = 1


class OrgSettings(TimestampMixin, Base):
    """Organisation settings. Exactly one row (id 1), created with defaults on first read.

    The AI assistant (plain-language rules, incident explanations) is off until an admin
    turns it on and names an OpenAI-compatible endpoint.
    """

    __tablename__ = "org_settings"
    __table_args__ = (CheckConstraint("id = 1", name="ck_org_settings_singleton"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=SINGLETON_ID)
    site_name: Mapped[str] = mapped_column(String(80), nullable=False, default="DataQuality")
    # Off by default: an admin invites people; open sign-up suits a sandbox instance.
    allow_signup: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    ai_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    ai_base_url: Mapped[str | None] = mapped_column(String(500))
    ai_model: Mapped[str | None] = mapped_column(String(120))
    # Sealed with the key sealer (local AES-GCM or KMS); never returned by the API.
    ai_api_key_sealed: Mapped[bytes | None] = mapped_column(LargeBinary)
