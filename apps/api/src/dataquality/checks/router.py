from __future__ import annotations

import uuid

from fastapi import APIRouter, Response

from dataquality.checks import service
from dataquality.checks.schemas import (
    BulkCreate,
    BulkResult,
    CheckIn,
    CheckOut,
    CheckUpdate,
    DraftOut,
    DraftRequest,
    YamlIn,
)
from dataquality.core.deps import ContainerDep, SessionDep
from dataquality.datasets import service as datasets
from dataquality.projects.access import Editor, Viewer

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/datasets/{dataset_id}/checks", tags=["checks"]
)


@router.get(
    "", response_model=list[CheckOut], summary="A dataset's checks with their latest result"
)
async def list_checks(dataset_id: uuid.UUID, p: Viewer, session: SessionDep) -> list[CheckOut]:
    d = await datasets.get(session, p.project_id, dataset_id)
    return await service.list_checks(session, d)


@router.post("", response_model=CheckOut, status_code=201, summary="Add a check")
async def create_check(
    dataset_id: uuid.UUID, body: CheckIn, p: Editor, session: SessionDep
) -> CheckOut:
    d = await datasets.get(session, p.project_id, dataset_id)
    return CheckOut.model_validate(await service.create(session, p, d, body))


@router.post(
    "/bulk",
    response_model=BulkResult,
    status_code=201,
    summary="Add many checks (accept suggestions)",
)
async def bulk(
    dataset_id: uuid.UUID, body: BulkCreate, p: Editor, session: SessionDep
) -> BulkResult:
    d = await datasets.get(session, p.project_id, dataset_id)
    return await service.bulk_create(session, p, d, body.checks, body.origin)


@router.get("/yaml", summary="Export the checks as YAML (checks as code)", response_class=Response)
async def export_yaml(dataset_id: uuid.UUID, p: Viewer, session: SessionDep) -> Response:
    from sqlalchemy import select

    from dataquality.checks.models import Check

    d = await datasets.get(session, p.project_id, dataset_id)
    rows = (
        await session.scalars(
            select(Check).where(Check.dataset_id == d.id).order_by(Check.created_at)
        )
    ).all()
    return Response(
        service.export_yaml(d, rows),
        media_type="application/yaml",
        headers={"content-disposition": f'attachment; filename="{d.slug}.dataquality.yaml"'},
    )


@router.put("/yaml", response_model=BulkResult, summary="Apply a YAML file of checks (idempotent)")
async def apply_yaml(
    dataset_id: uuid.UUID, body: YamlIn, p: Editor, session: SessionDep
) -> BulkResult:
    d = await datasets.get(session, p.project_id, dataset_id)
    return await service.apply_yaml(session, p, d, body.yaml, body.prune)


@router.post(
    "/draft", response_model=DraftOut, summary="Draft a check from plain language (optional AI)"
)
async def draft(
    dataset_id: uuid.UUID,
    body: DraftRequest,
    p: Editor,
    session: SessionDep,
    container: ContainerDep,
) -> DraftOut:
    from dataquality.ai import service as ai

    d = await datasets.get(session, p.project_id, dataset_id)
    return await ai.draft_check(container, session, p, d, body.prompt)


@router.patch("/{check_id}", response_model=CheckOut, summary="Change a check")
async def update_check(
    dataset_id: uuid.UUID, check_id: uuid.UUID, body: CheckUpdate, p: Editor, session: SessionDep
) -> CheckOut:
    d = await datasets.get(session, p.project_id, dataset_id)
    c = await service.get(session, p.project_id, check_id)
    if c.dataset_id != d.id:
        from dataquality.core.errors import NotFoundError

        raise NotFoundError("Check not found")
    return CheckOut.model_validate(await service.update(session, p, c, d, body))


@router.delete("/{check_id}", status_code=204, summary="Delete a check (its past results stay)")
async def delete_check(
    dataset_id: uuid.UUID, check_id: uuid.UUID, p: Editor, session: SessionDep
) -> Response:
    c = await service.get(session, p.project_id, check_id)
    if c.dataset_id != dataset_id:
        from dataquality.core.errors import NotFoundError

        raise NotFoundError("Check not found")
    await service.delete(session, p, c)
    return Response(status_code=204)
