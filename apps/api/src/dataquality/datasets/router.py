from __future__ import annotations

import uuid

from fastapi import APIRouter, File, Form, Query, Response, UploadFile

from dataquality.core.deps import ContainerDep, SessionDep
from dataquality.core.errors import NotFoundError
from dataquality.datasets import service
from dataquality.datasets.schemas import (
    DatasetCreate,
    DatasetOut,
    DatasetUpdate,
    FileOut,
    MetricSeries,
    PreviewOut,
    ProfileOut,
    PushRequest,
    SuggestionOut,
)
from dataquality.projects.access import Editor, Pusher, Viewer
from dataquality.scans import service as scans
from dataquality.scans.router import detail
from dataquality.scans.schemas import PushResult, ScanColumn

router = APIRouter(prefix="/api/v1/projects/{project_id}/datasets", tags=["datasets"])


@router.get("", response_model=list[DatasetOut], summary="Datasets with their latest score")
async def list_datasets(p: Viewer, session: SessionDep) -> list[DatasetOut]:
    return await service.list_datasets(session, p.project_id)


@router.post(
    "",
    response_model=DatasetOut,
    status_code=201,
    summary="Add a table, query, REST or push dataset",
)
async def create_dataset(
    body: DatasetCreate, p: Editor, session: SessionDep, container: ContainerDep
) -> DatasetOut:
    return await service.to_out(session, await service.create(container, session, p, body))


@router.post(
    "/upload", response_model=DatasetOut, status_code=201, summary="Add a dataset from a file"
)
async def upload_dataset(
    p: Editor,
    session: SessionDep,
    container: ContainerDep,
    file: UploadFile = File(..., description="CSV, TSV, JSON, NDJSON, Parquet or Excel (.xlsx)"),
    name: str | None = Form(None, max_length=120),
    sheet: str | None = Form(None, max_length=120),
    delimiter: str | None = Form(None, max_length=4),
) -> DatasetOut:
    d = await service.upload_file(
        container, session, p, file, name=name, options={"sheet": sheet, "delimiter": delimiter}
    )
    return await service.to_out(session, d)


@router.get("/{dataset_id}", response_model=DatasetOut, summary="One dataset")
async def get_dataset(dataset_id: uuid.UUID, p: Viewer, session: SessionDep) -> DatasetOut:
    return await service.to_out(session, await service.get(session, p.project_id, dataset_id))


@router.patch(
    "/{dataset_id}", response_model=DatasetOut, summary="Change a dataset, its filter or schedule"
)
async def update_dataset(
    dataset_id: uuid.UUID,
    body: DatasetUpdate,
    p: Editor,
    session: SessionDep,
    container: ContainerDep,
) -> DatasetOut:
    d = await service.get(session, p.project_id, dataset_id)
    return await service.to_out(session, await service.update(container, session, p, d, body))


@router.delete("/{dataset_id}", status_code=204, summary="Delete a dataset, its checks and history")
async def delete_dataset(
    dataset_id: uuid.UUID, p: Editor, session: SessionDep, container: ContainerDep
) -> Response:
    d = await service.get(session, p.project_id, dataset_id)
    await service.delete(container, session, p, d)
    return Response(status_code=204)


@router.get(
    "/{dataset_id}/files",
    response_model=list[FileOut],
    summary="Uploaded versions and pushed batches",
)
async def list_files(dataset_id: uuid.UUID, p: Viewer, session: SessionDep) -> list[FileOut]:
    d = await service.get(session, p.project_id, dataset_id)
    return [FileOut.model_validate(f) for f in await service.versions(session, d)]


@router.post(
    "/{dataset_id}/files",
    response_model=DatasetOut,
    status_code=201,
    summary="Upload a new version",
)
async def upload_version(
    dataset_id: uuid.UUID,
    p: Editor,
    session: SessionDep,
    container: ContainerDep,
    file: UploadFile = File(...),
) -> DatasetOut:
    d = await service.get(session, p.project_id, dataset_id)
    return await service.to_out(
        session, await service.upload_file(container, session, p, file, dataset=d)
    )


@router.get(
    "/{dataset_id}/preview",
    response_model=PreviewOut,
    summary="The first rows, read live from the source",
)
async def preview(
    dataset_id: uuid.UUID,
    p: Viewer,
    session: SessionDep,
    container: ContainerDep,
    limit: int = Query(50, ge=1, le=200),
) -> PreviewOut:
    d = await service.get(session, p.project_id, dataset_id)
    return PreviewOut(**await service.preview(container, session, d, limit))


@router.get("/{dataset_id}/profile", response_model=ProfileOut, summary="The latest column profile")
async def profile(dataset_id: uuid.UUID, p: Viewer, session: SessionDep) -> ProfileOut:
    d = await service.get(session, p.project_id, dataset_id)
    row = await scans.latest_profile(session, d)
    if row is None:
        raise NotFoundError("No profile yet. Run a scan with profiling on", code="no_profile")
    return ProfileOut.model_validate(row)


@router.get(
    "/{dataset_id}/suggestions",
    response_model=list[SuggestionOut],
    summary="Checks suggested from the profile",
)
async def suggestions(dataset_id: uuid.UUID, p: Viewer, session: SessionDep) -> list[SuggestionOut]:
    d = await service.get(session, p.project_id, dataset_id)
    found = await scans.suggestions(session, d)
    if found is None:
        raise NotFoundError(
            "No profile yet. Run a scan first, then suggestions appear", code="no_profile"
        )
    return [SuggestionOut(**s) for s in found]


@router.get(
    "/{dataset_id}/columns",
    response_model=list[ScanColumn],
    summary="The dataset's columns as its latest scan saw them",
)
async def columns(dataset_id: uuid.UUID, p: Viewer, session: SessionDep) -> list[ScanColumn]:
    d = await service.get(session, p.project_id, dataset_id)
    if d.last_scan_id is None:
        return []
    from dataquality.scans.models import Scan

    scan = await session.get(Scan, d.last_scan_id)
    return [ScanColumn.model_validate(c) for c in (scan.columns if scan else [])]


@router.get(
    "/{dataset_id}/metrics", response_model=list[MetricSeries], summary="A metric's history"
)
async def metrics(
    dataset_id: uuid.UUID,
    p: Viewer,
    session: SessionDep,
    metric: str = Query(
        "score", pattern=r"^(row_count|score|dimension|check_failed_pct|null_rate|distinct|mean)$"
    ),
    key: str | None = None,
    days: int = Query(30, ge=1, le=3650),
) -> list[MetricSeries]:
    d = await service.get(session, p.project_id, dataset_id)
    return [
        MetricSeries(metric=metric, key=k, points=pts)
        for k, pts in await scans.series(session, d, metric, key, days)
    ]


@router.post(
    "/{dataset_id}/records",
    response_model=PushResult,
    summary="Push records and get them validated",
    description="Stores the batch as the push dataset's newest version, scans it and waits up to "
    "`wait` seconds for the result (0 returns at once with the queued scan).",
)
async def push_records(
    dataset_id: uuid.UUID,
    body: PushRequest,
    p: Pusher,
    session: SessionDep,
    container: ContainerDep,
    response: Response,
    wait: float = Query(30, ge=0, le=120),
) -> PushResult:
    d = await service.get(session, p.project_id, dataset_id)
    version = await service.push_records(container, session, p, d, body.records)
    scan, _ = await scans.request_scan(
        container, session, p, d, trigger="push", file_id=version.id, profile=False
    )
    if wait:
        await scans.wait(container, p.project_id, scan.id, wait)
        await session.refresh(scan)
    full = await detail(session, scan)
    if scan.status not in ("succeeded", "failed", "cancelled"):
        response.status_code = 202
    passed = scan.status == "succeeded" and not any(
        r.status == "fail" and r.severity == "error" for r in full.results
    )
    return PushResult(scan=full, records=len(body.records), passed=passed)
