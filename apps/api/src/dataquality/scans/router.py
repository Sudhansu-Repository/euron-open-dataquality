from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Query, Response

from dataquality.core.deps import ContainerDep, SessionDep
from dataquality.core.schemas import Page, decode_cursor, encode_cursor
from dataquality.datasets import service as datasets
from dataquality.datasets.models import Dataset
from dataquality.projects.access import Scanner, Viewer
from dataquality.scans import reports, service
from dataquality.scans.models import Scan
from dataquality.scans.schemas import AnomalyOut, ResultOut, ScanDetail, ScanOut, ScanRequest

router = APIRouter(prefix="/api/v1/projects/{project_id}", tags=["scans"])


def scan_out(scan: Scan, dataset_name: str | None = None) -> ScanOut:
    return ScanOut.model_validate(scan).model_copy(update={"dataset_name": dataset_name})


async def detail(session: SessionDep, scan: Scan) -> ScanDetail:
    d = await session.get(Dataset, scan.dataset_id)
    rows = await service.results(session, scan)
    return ScanDetail.model_validate(scan).model_copy(
        update={
            "dataset_name": d.name if d else None,
            "results": [ResultOut.model_validate(r) for r in rows],
        }
    )


@router.post(
    "/datasets/{dataset_id}/scans",
    response_model=ScanDetail,
    status_code=202,
    summary="Scan a dataset now",
    description="Queues a scan. With `wait` (seconds, up to 300) the response comes when it "
    "finishes "
    "or the wait runs out, so a CI job can trigger and read the result in one call.",
)
async def create_scan(
    dataset_id: uuid.UUID,
    p: Scanner,
    session: SessionDep,
    container: ContainerDep,
    response: Response,
    body: ScanRequest | None = None,
    wait: float = Query(0, ge=0, le=300),
) -> ScanDetail:
    d = await datasets.get(session, p.project_id, dataset_id)
    body = body or ScanRequest()
    trigger = "api" if p.key else "manual"
    scan, _new = await service.request_scan(
        container,
        session,
        p,
        d,
        trigger=trigger,
        idempotency_key=body.idempotency_key,
        profile=body.profile,
    )
    if wait:
        await service.wait(container, p.project_id, scan.id, wait)
        await session.refresh(scan)
    if scan.status in ("succeeded", "failed", "cancelled"):
        response.status_code = 200
    return await detail(session, scan)


@router.get("/scans", response_model=Page[ScanOut], summary="Scans, newest first")
async def list_scans(
    p: Viewer,
    session: SessionDep,
    dataset_id: uuid.UUID | None = None,
    status: str | None = Query(None, pattern=r"^(queued|running|succeeded|failed|cancelled)$"),
    cursor: str | None = None,
    limit: int = Query(50, ge=1, le=200),
) -> Page[ScanOut]:
    raw = decode_cursor(cursor)
    before = datetime.fromisoformat(raw) if raw else None
    rows = await service.list_scans(
        session, p.project_id, dataset_id=dataset_id, status=status, before=before, limit=limit
    )
    names = {}
    ids = {r.dataset_id for r in rows}
    if ids:
        from sqlalchemy import select

        names = dict(
            (
                await session.execute(select(Dataset.id, Dataset.name).where(Dataset.id.in_(ids)))
            ).all()
        )
    page = rows[:limit]
    return Page[ScanOut](
        items=[scan_out(s, names.get(s.dataset_id)) for s in page],
        next_cursor=encode_cursor(page[-1].created_at.isoformat()) if len(rows) > limit else None,
    )


@router.get("/scans/{scan_id}", response_model=ScanDetail, summary="A scan with every check result")
async def get_scan(scan_id: uuid.UUID, p: Viewer, session: SessionDep) -> ScanDetail:
    return await detail(session, await service.get(session, p.project_id, scan_id))


@router.post(
    "/scans/{scan_id}/cancel", response_model=ScanOut, summary="Cancel a queued or running scan"
)
async def cancel_scan(scan_id: uuid.UUID, p: Scanner, session: SessionDep) -> ScanOut:
    scan = await service.get(session, p.project_id, scan_id)
    return scan_out(await service.cancel(session, p, scan))


@router.get("/scans/{scan_id}/wait", response_model=ScanDetail, summary="Wait for a scan to finish")
async def wait_scan(
    scan_id: uuid.UUID,
    p: Viewer,
    session: SessionDep,
    container: ContainerDep,
    wait_s: float = Query(30, ge=1, le=300, alias="timeout"),
) -> ScanDetail:
    await service.get(session, p.project_id, scan_id)
    scan = await service.wait(container, p.project_id, scan_id, wait_s)
    return await detail(session, scan)


def _filename(dataset: Dataset, scan: Scan, ext: str) -> str:
    when = (scan.finished_at or scan.created_at).strftime("%Y%m%d-%H%M")
    return f"dataquality-{dataset.slug}-{when}.{ext}"


@router.get("/scans/{scan_id}/report.csv", summary="The scan as CSV", response_class=Response)
async def scan_csv(scan_id: uuid.UUID, p: Viewer, session: SessionDep) -> Response:
    scan = await service.get(session, p.project_id, scan_id)
    d = await datasets.get(session, p.project_id, scan.dataset_id)
    body = reports.scan_csv(d, scan, await service.results(session, scan))
    return Response(
        body,
        media_type="text/csv; charset=utf-8",
        headers={
            "cache-control": "no-store",
            "content-disposition": f'attachment; filename="{_filename(d, scan, "csv")}"',
        },
    )


@router.get("/scans/{scan_id}/report.pdf", summary="The scan as PDF", response_class=Response)
async def scan_pdf(scan_id: uuid.UUID, p: Viewer, session: SessionDep) -> Response:
    import asyncio

    scan = await service.get(session, p.project_id, scan_id)
    d = await datasets.get(session, p.project_id, scan.dataset_id)
    results = await service.results(session, scan)
    body = await asyncio.to_thread(reports.scan_pdf, p.project.name, d, scan, results)
    return Response(
        body,
        media_type="application/pdf",
        headers={
            "cache-control": "no-store",
            "content-disposition": f'attachment; filename="{_filename(d, scan, "pdf")}"',
        },
    )


@router.get(
    "/datasets/{dataset_id}/history.csv",
    summary="Every scan of a dataset as CSV",
    response_class=Response,
)
async def history_csv(dataset_id: uuid.UUID, p: Viewer, session: SessionDep) -> Response:
    d = await datasets.get(session, p.project_id, dataset_id)
    scans = await service.list_scans(
        session, p.project_id, dataset_id=d.id, status=None, before=None, limit=5000
    )
    body = reports.history_csv(d, scans)
    return Response(
        body,
        media_type="text/csv; charset=utf-8",
        headers={
            "cache-control": "no-store",
            "content-disposition": f'attachment; filename="dataquality-{d.slug}-history.csv"',
        },
    )


@router.get("/report.pdf", summary="Project summary as PDF", response_class=Response)
async def project_pdf(p: Viewer, session: SessionDep) -> Response:
    import asyncio

    from sqlalchemy import select

    rows = (await session.scalars(select(Dataset).where(Dataset.project_id == p.project_id))).all()
    body = await asyncio.to_thread(reports.project_pdf, p.project.name, rows, datetime.now(UTC))
    return Response(
        body,
        media_type="application/pdf",
        headers={
            "cache-control": "no-store",
            "content-disposition": (
                f'attachment; filename="dataquality-{p.project.slug}-summary.pdf"'
            ),
        },
    )


@router.get(
    "/anomalies",
    response_model=list[AnomalyOut],
    summary="Anomalies and schema changes, newest first",
)
async def list_anomalies(
    p: Viewer,
    session: SessionDep,
    dataset_id: uuid.UUID | None = None,
    limit: int = Query(100, ge=1, le=500),
) -> list[AnomalyOut]:
    return [
        AnomalyOut.model_validate(a)
        for a in await service.anomalies(session, p.project_id, dataset_id, limit)
    ]
