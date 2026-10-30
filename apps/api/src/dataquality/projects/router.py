from __future__ import annotations

import uuid

from fastapi import APIRouter, Request, Response

from dataquality.auth.dependencies import CurrentUser
from dataquality.core.deps import ContainerDep, SessionDep
from dataquality.core.schemas import Ack
from dataquality.projects import service
from dataquality.projects.access import Owner, Viewer
from dataquality.projects.schemas import (
    ApiKeyCreate,
    ApiKeyCreated,
    ApiKeyOut,
    MemberAdd,
    MemberOut,
    MemberUpdate,
    ProjectCreate,
    ProjectOut,
    ProjectUpdate,
)

router = APIRouter(prefix="/api/v1/projects", tags=["projects"])


def _out(project: object, role: str) -> ProjectOut:
    return ProjectOut.model_validate(project).model_copy(update={"role": role})


@router.get("", response_model=list[ProjectOut], summary="Projects you can see")
async def list_projects(user: CurrentUser, session: SessionDep) -> list[ProjectOut]:
    return await service.list_projects(session, user)


@router.post(
    "",
    response_model=ProjectOut,
    status_code=201,
    summary="Create a project (you become its owner)",
)
async def create_project(
    body: ProjectCreate, request: Request, user: CurrentUser, session: SessionDep
) -> ProjectOut:
    return _out(await service.create_project(session, body, user, request.state.actor), "owner")


@router.get("/{project_id}", response_model=ProjectOut, summary="One project")
async def get_project(p: Viewer) -> ProjectOut:
    return _out(p.project, p.role)


@router.patch("/{project_id}", response_model=ProjectOut, summary="Change a project's settings")
async def update_project(body: ProjectUpdate, p: Owner, session: SessionDep) -> ProjectOut:
    return _out(await service.update_project(session, p, body), p.role)


@router.delete("/{project_id}", status_code=204, summary="Delete a project and everything in it")
async def delete_project(p: Owner, session: SessionDep) -> Response:
    await service.delete_project(session, p)
    return Response(status_code=204)


@router.get("/{project_id}/members", response_model=list[MemberOut], summary="Project members")
async def list_members(p: Viewer, session: SessionDep) -> list[MemberOut]:
    return [
        MemberOut(user_id=u.id, email=u.email, name=u.name, role=m.role, created_at=m.created_at)
        for m, u in await service.members(session, p.project_id)
    ]


@router.post(
    "/{project_id}/members", response_model=MemberOut, status_code=201, summary="Add a member"
)
async def add_member(body: MemberAdd, p: Owner, session: SessionDep) -> MemberOut:
    m, u = await service.add_member(session, p, body)
    return MemberOut(user_id=u.id, email=u.email, name=u.name, role=m.role, created_at=m.created_at)


@router.patch(
    "/{project_id}/members/{user_id}", response_model=Ack, summary="Change a member's role"
)
async def update_member(
    user_id: uuid.UUID, body: MemberUpdate, p: Owner, session: SessionDep
) -> Ack:
    await service.update_member(session, p, user_id, body.role)
    return Ack(message="Role updated")


@router.delete("/{project_id}/members/{user_id}", status_code=204, summary="Remove a member")
async def remove_member(user_id: uuid.UUID, p: Owner, session: SessionDep) -> Response:
    await service.remove_member(session, p, user_id)
    return Response(status_code=204)


@router.get("/{project_id}/api-keys", response_model=list[ApiKeyOut], summary="API keys")
async def list_keys(p: Owner, session: SessionDep) -> list[ApiKeyOut]:
    return [ApiKeyOut.model_validate(k) for k in await service.list_keys(session, p.project_id)]


@router.post(
    "/{project_id}/api-keys",
    response_model=ApiKeyCreated,
    status_code=201,
    summary="Create an API key (shown once)",
)
async def create_key(
    body: ApiKeyCreate, p: Owner, session: SessionDep, container: ContainerDep
) -> ApiKeyCreated:
    key, plaintext = await service.create_key(session, p, body, container.settings.api_key_pepper)
    return ApiKeyCreated(**ApiKeyOut.model_validate(key).model_dump(), key=plaintext)


@router.delete(
    "/{project_id}/api-keys/{key_id}", response_model=ApiKeyOut, summary="Revoke an API key"
)
async def revoke_key(key_id: uuid.UUID, p: Owner, session: SessionDep) -> ApiKeyOut:
    return ApiKeyOut.model_validate(await service.revoke_key(session, p, key_id))
