"""Organisation settings and self sign-up.

Settings live in one row, created with safe defaults on first read: sign-up closed, the AI
assistant off. The AI provider key is sealed before it is stored (the same sealer
as every other secret) and is never returned; ``ai_api_key`` opens it only for the AI call
itself.

``AI_ALLOW_PRIVATE_ENDPOINTS`` (default true) lets the AI endpoint be a private address,
which is what a local model (Ollama, vLLM on the same network) needs. Set it to false when
only hosted providers are allowed: private, loopback and single-label hosts are then
refused. Instance metadata addresses are refused either way.
"""

from __future__ import annotations

import asyncio

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from dataquality.audit.service import Actor, audit
from dataquality.core.container import Container
from dataquality.core.errors import AppError, ConflictError, PermissionDeniedError
from dataquality.core.net import host_of, is_private_host
from dataquality.core.security import hash_password, password_problems
from dataquality.org.models import SINGLETON_ID, OrgSettings
from dataquality.org.schemas import AdminSettings, PublicSettings, SettingsUpdate, SignupRequest
from dataquality.users.models import User

KEY_CONTEXT = "org_settings:ai_api_key"


async def get(session: AsyncSession) -> OrgSettings:
    row = await session.get(OrgSettings, SINGLETON_ID)
    if row is None:
        await session.execute(insert(OrgSettings).values(id=SINGLETON_ID).on_conflict_do_nothing())
        await session.commit()
        row = await session.get(OrgSettings, SINGLETON_ID)
    assert row is not None
    return row


def public(row: OrgSettings) -> PublicSettings:
    return PublicSettings(
        site_name=row.site_name,
        allow_signup=row.allow_signup,
        ai_enabled=row.ai_enabled,
    )


def admin(row: OrgSettings) -> AdminSettings:
    return AdminSettings(
        site_name=row.site_name,
        allow_signup=row.allow_signup,
        ai_enabled=row.ai_enabled,
        ai_base_url=row.ai_base_url,
        ai_model=row.ai_model,
        ai_has_key=row.ai_api_key_sealed is not None,
    )


def check_endpoint(container: Container, url: str) -> None:
    """Refuse a private AI endpoint unless private endpoints are allowed (local models)."""
    if not container.settings.ai_allow_private_endpoints and is_private_host(host_of(url)):
        raise AppError(
            "The AI endpoint is a private address, which this deployment does not allow. "
            "Use a public provider URL, or set AI_ALLOW_PRIVATE_ENDPOINTS=true",
            code="ai_endpoint_private",
        )


async def update(
    container: Container, session: AsyncSession, data: SettingsUpdate, actor: Actor
) -> OrgSettings:
    row = await get(session)
    changes = data.model_dump(exclude_unset=True)
    key = changes.pop("ai_api_key", None)
    for required in ("site_name", "allow_signup", "ai_enabled"):
        if required in changes and changes[required] is None:
            changes.pop(required)
    if "ai_base_url" in changes:
        changes["ai_base_url"] = changes["ai_base_url"] or None
        if changes["ai_base_url"]:
            check_endpoint(container, changes["ai_base_url"])
    if "ai_model" in changes:
        changes["ai_model"] = (changes["ai_model"] or "").strip() or None
    for field, value in changes.items():
        setattr(row, field, value)
    if key is not None:
        row.ai_api_key_sealed = await container.sealer.seal(key, KEY_CONTEXT) if key else None
    if row.ai_enabled and not (row.ai_base_url and row.ai_model):
        raise AppError(
            "Set the AI endpoint URL and model before turning the assistant on",
            code="ai_endpoint_required",
        )
    fields = sorted(changes) + (["ai_api_key"] if key is not None else [])
    audit(session, actor, "org.settings_updated", "org_settings", row.id, fields=fields)
    await session.commit()
    await session.refresh(row)
    return row


async def ai_api_key(container: Container, row: OrgSettings) -> str | None:
    if row.ai_api_key_sealed is None:
        return None
    return await container.sealer.open(row.ai_api_key_sealed, KEY_CONTEXT)


async def signup(session: AsyncSession, data: SignupRequest, ip: str | None) -> User:
    """An account, when the instance allows people to register themselves. The first
    account on a fresh instance is always allowed and becomes the admin."""
    row = await get(session)
    first = not await session.scalar(select(User.id).limit(1))
    if not row.allow_signup and not first:
        raise PermissionDeniedError(
            "Sign-up is closed. Ask an administrator for an account", code="signup_closed"
        )
    if problems := password_problems(data.password):
        raise AppError(
            "Password needs " + ", ".join(problems),
            code="weak_password",
            details={"problems": problems},
        )
    if await session.scalar(select(User.id).where(func.lower(User.email) == data.email.lower())):
        raise ConflictError(
            "An account with this email exists. Sign in instead", code="email_taken"
        )
    user = User(
        email=data.email.lower(),
        name=data.name.strip(),
        role="admin" if first else "user",
        password_hash=await asyncio.to_thread(hash_password, data.password),
    )
    session.add(user)
    await session.flush()
    actor = Actor(user.id, user.email, user.role, ip)
    audit(session, actor, "auth.signup", "user", user.id)
    await session.commit()
    await session.refresh(user)
    return user
