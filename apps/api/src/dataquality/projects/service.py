"""Projects, members and API keys. Guards keep at least one owner in every project."""

from __future__ import annotations

import re
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from dataquality.audit.service import Actor, audit
from dataquality.core.errors import ConflictError, NotFoundError, PermissionDeniedError
from dataquality.core.security import generate_api_key
from dataquality.projects.access import Principal
from dataquality.projects.models import ApiKey, Project, ProjectMember
from dataquality.projects.schemas import (
    ApiKeyCreate,
    MemberAdd,
    ProjectCreate,
    ProjectOut,
    ProjectUpdate,
)
from dataquality.users.models import User


def slugify(text: str, fallback: str = "item") -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60].strip("-")
    return slug or fallback


async def unique_slug(session: AsyncSession, base: str) -> str:
    slug, n = base, 2
    while await session.scalar(select(Project.id).where(Project.slug == slug)):
        slug = f"{base[:56]}-{n}"
        n += 1
    return slug


async def list_projects(session: AsyncSession, user: User) -> list[ProjectOut]:
    """Every project the user can see, with their role, dataset count and current score,
    in three queries whatever the number of projects."""
    from dataquality.datasets.models import Dataset

    if user.role == "admin":
        rows = [
            (p, "owner")
            for p in (await session.scalars(select(Project).order_by(Project.name))).all()
        ]
    else:
        result = await session.execute(
            select(Project, ProjectMember.role)
            .join(ProjectMember, ProjectMember.project_id == Project.id)
            .where(ProjectMember.user_id == user.id)
            .order_by(Project.name)
        )
        rows = [(p, str(r)) for p, r in result.all()]
    ids = [p.id for p, _ in rows]
    stats: dict[uuid.UUID, tuple[int, float | None]] = {}
    if ids:
        for pid, count, avg in (
            await session.execute(
                select(Dataset.project_id, func.count(), func.avg(Dataset.last_score))
                .where(Dataset.project_id.in_(ids))
                .group_by(Dataset.project_id)
            )
        ).all():
            stats[pid] = (int(count), round(float(avg), 1) if avg is not None else None)
    out = []
    for p, role in rows:
        count, score = stats.get(p.id, (0, None))
        item = ProjectOut.model_validate(p)
        out.append(item.model_copy(update={"role": role, "datasets": count, "score": score}))
    return out


async def create_project(
    session: AsyncSession, data: ProjectCreate, user: User, actor: Actor
) -> Project:
    slug = data.slug or slugify(data.name, "project")
    if data.slug and await session.scalar(select(Project.id).where(Project.slug == data.slug)):
        raise ConflictError("A project with this slug exists", code="slug_taken")
    project = Project(
        name=data.name.strip(),
        slug=await unique_slug(session, slug),
        description=data.description,
        created_by=user.id,
    )
    session.add(project)
    await session.flush()
    session.add(ProjectMember(project_id=project.id, user_id=user.id, role="owner"))
    audit(session, actor, "project.created", "project", project.id, name=project.name)
    await session.commit()
    return project


async def update_project(session: AsyncSession, p: Principal, data: ProjectUpdate) -> Project:
    project = p.project
    changes = data.model_dump(exclude_unset=True, exclude_none=True)
    for field, value in changes.items():
        setattr(project, field, value)
    audit(session, p.actor, "project.updated", "project", project.id, fields=sorted(changes))
    await session.commit()
    await session.refresh(project)
    return project


async def delete_project(session: AsyncSession, p: Principal) -> None:
    audit(session, p.actor, "project.deleted", "project", p.project_id, name=p.project.name)
    await session.delete(p.project)
    await session.commit()


async def members(
    session: AsyncSession, project_id: uuid.UUID
) -> Sequence[tuple[ProjectMember, User]]:
    result = await session.execute(
        select(ProjectMember, User)
        .join(User, User.id == ProjectMember.user_id)
        .where(ProjectMember.project_id == project_id)
        .order_by(User.name)
    )
    return [(m, u) for m, u in result.all()]


async def add_member(
    session: AsyncSession, p: Principal, data: MemberAdd
) -> tuple[ProjectMember, User]:
    user = await session.scalar(select(User).where(func.lower(User.email) == data.email.lower()))
    if user is None:
        raise NotFoundError(
            "No user with this email. Ask an admin to create the account first",
            code="user_not_found",
        )
    if await session.get(ProjectMember, (p.project_id, user.id)):
        raise ConflictError("This person is already a member", code="already_member")
    member = ProjectMember(project_id=p.project_id, user_id=user.id, role=data.role)
    session.add(member)
    audit(
        session,
        p.actor,
        "project.member_added",
        "project",
        p.project_id,
        user=user.email,
        role=data.role,
    )
    await session.commit()
    await session.refresh(member)
    return member, user


async def _owners(session: AsyncSession, project_id: uuid.UUID) -> int:
    rows = await session.scalars(
        select(ProjectMember.user_id)
        .where(ProjectMember.project_id == project_id, ProjectMember.role == "owner")
        .with_for_update()
    )
    return len(rows.all())


async def update_member(
    session: AsyncSession, p: Principal, user_id: uuid.UUID, role: str
) -> ProjectMember:
    member = await session.get(ProjectMember, (p.project_id, user_id))
    if member is None:
        raise NotFoundError("Member not found")
    if member.role == "owner" and role != "owner" and await _owners(session, p.project_id) <= 1:
        raise ConflictError("A project needs at least one owner", code="last_owner")
    member.role = role
    audit(
        session,
        p.actor,
        "project.member_updated",
        "project",
        p.project_id,
        user_id=str(user_id),
        role=role,
    )
    await session.commit()
    return member


async def remove_member(session: AsyncSession, p: Principal, user_id: uuid.UUID) -> None:
    member = await session.get(ProjectMember, (p.project_id, user_id))
    if member is None:
        raise NotFoundError("Member not found")
    if member.role == "owner" and await _owners(session, p.project_id) <= 1:
        raise ConflictError("A project needs at least one owner", code="last_owner")
    await session.delete(member)
    audit(session, p.actor, "project.member_removed", "project", p.project_id, user_id=str(user_id))
    await session.commit()


async def list_keys(session: AsyncSession, project_id: uuid.UUID) -> Sequence[ApiKey]:
    return (
        await session.scalars(
            select(ApiKey).where(ApiKey.project_id == project_id).order_by(ApiKey.created_at.desc())
        )
    ).all()


async def create_key(
    session: AsyncSession, p: Principal, data: ApiKeyCreate, pepper: str
) -> tuple[ApiKey, str]:
    if p.key is not None:
        raise PermissionDeniedError(
            "API keys cannot create API keys", code="key_cannot_create_keys"
        )
    generated = generate_api_key(pepper)
    key = ApiKey(
        project_id=p.project_id,
        name=data.name.strip(),
        prefix=generated.prefix,
        secret_hash=generated.secret_hash,
        scopes=list(data.scopes),
        created_by=p.user_id,
    )
    session.add(key)
    await session.flush()
    audit(session, p.actor, "api_key.created", "api_key", key.id, name=key.name, scopes=key.scopes)
    await session.commit()
    await session.refresh(key)
    return key, generated.plaintext


async def revoke_key(session: AsyncSession, p: Principal, key_id: uuid.UUID) -> ApiKey:
    key = await session.scalar(
        select(ApiKey).where(ApiKey.id == key_id, ApiKey.project_id == p.project_id)
    )
    if key is None:
        raise NotFoundError("API key not found")
    if key.revoked_at is None:
        key.revoked_at = datetime.now(UTC)
        audit(session, p.actor, "api_key.revoked", "api_key", key.id, name=key.name)
        await session.commit()
    return key
