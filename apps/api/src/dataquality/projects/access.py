"""Who may do what in a project. Every project route resolves a ``Principal`` first.

People hold a project role (viewer < editor < owner); instance admins act as owners
everywhere. API keys belong to one project and carry scopes:

* ``read``: everything a viewer sees
* ``scan``: trigger scans and wait for them
* ``push``: send records to push datasets
* ``manage``: edit datasets and checks (checks as code from CI)

A project the caller cannot see answers 404, never 403, so its existence does not leak.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import Depends, Path, Request
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from dataquality.audit.service import Actor
from dataquality.auth.dependencies import api_key_from, current_user
from dataquality.core.deps import ContainerDep, SessionDep, client_ip
from dataquality.core.errors import AuthenticationError, NotFoundError, PermissionDeniedError
from dataquality.core.security import constant_time_equals, hash_key_secret, parse_api_key
from dataquality.projects.models import ApiKey, Project, ProjectMember

ROLE_RANK = {"viewer": 0, "editor": 1, "owner": 2}
SCOPES = ("read", "scan", "push", "manage")
_TOUCH_EVERY = timedelta(minutes=5)


@dataclass(frozen=True)
class Principal:
    project: Project
    role: str  # viewer, editor, owner
    actor: Actor
    key: ApiKey | None = None

    @property
    def project_id(self) -> uuid.UUID:
        return self.project.id

    @property
    def user_id(self) -> uuid.UUID | None:
        return None if self.key is not None else self.actor.id

    def at_least(self, role: str) -> bool:
        return ROLE_RANK[self.role] >= ROLE_RANK[role]

    def has_scope(self, scope: str) -> bool:
        return self.key is None or scope in (self.key.scopes or [])


async def _key_principal(
    request: Request, session: AsyncSession, raw: str, pepper: str, project: Project | None
) -> tuple[ApiKey, Project]:
    parsed = parse_api_key(raw)
    if parsed is None:
        raise AuthenticationError("The API key is malformed", code="invalid_api_key")
    prefix, secret = parsed
    key = await session.scalar(select(ApiKey).where(ApiKey.prefix == prefix))
    if (
        key is None
        or key.revoked_at is not None
        or not constant_time_equals(key.secret_hash, hash_key_secret(secret, pepper))
    ):
        raise AuthenticationError("The API key is not valid", code="invalid_api_key")
    now = datetime.now(UTC)
    if key.last_used_at is None or now - key.last_used_at > _TOUCH_EVERY:
        await session.execute(update(ApiKey).where(ApiKey.id == key.id).values(last_used_at=now))
        await session.commit()
    owner = project or await session.get(Project, key.project_id)
    if owner is None or owner.id != key.project_id:
        # A key for another project: the same answer as a project that does not exist.
        raise NotFoundError("Project not found")
    request.state.actor = Actor(None, f"api-key:{key.name}", "api_key", client_ip(request))
    return key, owner


async def resolve(
    request: Request,
    container: ContainerDep,
    session: SessionDep,
    project_id: uuid.UUID,
) -> Principal:
    raw_key = api_key_from(request)
    project = await session.get(Project, project_id)
    if raw_key:
        key, owner = await _key_principal(
            request, session, raw_key, container.settings.api_key_pepper, project
        )
        role = "editor" if "manage" in (key.scopes or []) else "viewer"
        return Principal(owner, role, request.state.actor, key)
    user = await current_user(request, container, session)
    if project is None:
        raise NotFoundError("Project not found")
    if user.role == "admin":
        role = "owner"
    else:
        member = await session.get(ProjectMember, (project.id, user.id))
        if member is None:
            raise NotFoundError("Project not found")
        role = member.role
    return Principal(project, role, request.state.actor)


def project_role(role: str, scope: str = "read") -> Callable[..., Coroutine[Any, Any, Principal]]:
    """A dependency: the caller holds at least ``role`` in the path's project (people) or
    the ``scope`` (API keys)."""

    async def dependency(
        request: Request,
        container: ContainerDep,
        session: SessionDep,
        project_id: Annotated[uuid.UUID, Path()],
    ) -> Principal:
        p = await resolve(request, container, session, project_id)
        if p.key is not None:
            if scope not in (p.key.scopes or []):
                raise PermissionDeniedError(
                    f"This API key lacks the {scope!r} scope", code="insufficient_scope"
                )
            return p
        if not p.at_least(role):
            raise PermissionDeniedError(
                f"This action needs the {role} role in this project", code="insufficient_role"
            )
        return p

    return dependency


Viewer = Annotated[Principal, Depends(project_role("viewer", "read"))]
Editor = Annotated[Principal, Depends(project_role("editor", "manage"))]
Owner = Annotated[Principal, Depends(project_role("owner", "__owner_only__"))]
Scanner = Annotated[Principal, Depends(project_role("editor", "scan"))]
Pusher = Annotated[Principal, Depends(project_role("editor", "push"))]
