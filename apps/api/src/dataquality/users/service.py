"""User management. Guards keep at least one active admin at all times."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from dataquality.audit.service import Actor, audit
from dataquality.core.errors import AppError, ConflictError, NotFoundError, PermissionDeniedError
from dataquality.core.security import hash_password, password_problems
from dataquality.users.models import User
from dataquality.users.schemas import UserCreate, UserUpdate


async def list_users(session: AsyncSession) -> Sequence[User]:
    return (await session.scalars(select(User).order_by(User.created_at))).all()


async def _active_admins(session: AsyncSession) -> int:
    """Count active admins, locking their rows until commit so two admins demoting each
    other at once cannot both pass the last-admin check."""
    rows = await session.scalars(
        select(User.id).where(User.role == "admin", User.disabled.is_(False)).with_for_update()
    )
    return len(rows.all())


async def create_user(session: AsyncSession, data: UserCreate, actor: Actor) -> User:
    if await session.scalar(select(User.id).where(func.lower(User.email) == data.email.lower())):
        raise ConflictError("A user with this email already exists", code="email_taken")
    if problems := password_problems(data.password):
        raise AppError("Password needs " + ", ".join(problems), code="weak_password")
    if data.role == "admin" and actor.role != "admin":
        raise PermissionDeniedError("Only an admin can create another admin")
    user = User(
        email=data.email.lower(),
        name=data.name,
        role=data.role,
        password_hash=await asyncio.to_thread(hash_password, data.password),
    )
    session.add(user)
    await session.flush()
    audit(session, actor, "user.created", "user", user.id, email=user.email, role=user.role)
    await session.commit()
    return user


async def update_user(
    session: AsyncSession, user_id: uuid.UUID, data: UserUpdate, actor: Actor
) -> User:
    user = await session.get(User, user_id)
    if user is None:
        raise NotFoundError("User not found")
    changes = data.model_dump(exclude_unset=True)
    if user.id == actor.id and ("role" in changes or changes.get("disabled")):
        raise PermissionDeniedError("You cannot change your own role or disable yourself")
    if (changes.get("role") == "admin" or user.role == "admin") and actor.role != "admin":
        raise PermissionDeniedError("Only an admin can change an admin")
    # Only taking away an *active* admin can leave nobody in charge; a disabled admin
    # does not count, so demoting one is always allowed.
    demoting = (
        user.role == "admin"
        and not user.disabled
        and (changes.get("role", "admin") != "admin" or changes.get("disabled"))
    )
    if demoting and await _active_admins(session) <= 1:
        raise ConflictError("At least one active admin is required", code="last_admin")
    for field, value in changes.items():
        setattr(user, field, value)
    if "role" in changes or changes.get("disabled"):
        user.session_version += 1  # role and access changes take effect immediately
    audit(session, actor, "user.updated", "user", user.id, **changes)
    await session.commit()
    return user
