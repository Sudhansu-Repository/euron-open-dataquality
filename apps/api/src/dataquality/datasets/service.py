"""Datasets: create one per kind, upload file versions, preview rows, read the latest
profile and suggestions, accept pushed records, and keep the schedule's next run time."""

from __future__ import annotations

import asyncio
import io
import tempfile
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import orjson
from croniter import croniter
from fastapi import UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from dataquality.audit.service import audit
from dataquality.connections.models import Connection
from dataquality.core.container import Container
from dataquality.core.errors import AppError, ConflictError, NotFoundError
from dataquality.datasets import source
from dataquality.datasets.models import Dataset, DatasetFile
from dataquality.datasets.schemas import DatasetCreate, DatasetOut, DatasetUpdate
from dataquality.engine.runner import error_text
from dataquality.engine.sqlguard import UnsafeSqlError, check_predicate, check_read_only
from dataquality.projects.access import Principal
from dataquality.projects.service import slugify
from dataquality.sources.files import CONTENT_TYPES, FileFormatError, detect_format


def headers_context(d: Dataset) -> str:
    return f"dataset:{d.id}:headers"


def next_run(cron: str, tz: str, after: datetime | None = None) -> datetime:
    """The next time the cron expression fires in the dataset's time zone, in UTC."""
    zone = ZoneInfo(tz)
    start = (after or datetime.now(UTC)).astimezone(zone)
    nxt: datetime = croniter(cron, start).get_next(datetime)
    return nxt.astimezone(UTC)


def _apply_schedule(d: Dataset) -> None:
    if d.schedule_enabled and d.schedule_cron:
        d.next_run_at = next_run(d.schedule_cron, d.schedule_tz)
    else:
        d.next_run_at = None


async def get(session: AsyncSession, project_id: uuid.UUID, dataset_id: uuid.UUID) -> Dataset:
    d = await session.scalar(
        select(Dataset).where(Dataset.id == dataset_id, Dataset.project_id == project_id)
    )
    if d is None:
        raise NotFoundError("Dataset not found")
    return d


async def to_out(session: AsyncSession, d: Dataset) -> DatasetOut:
    return (await to_outs(session, [d]))[0]


async def to_outs(session: AsyncSession, rows: Sequence[Dataset]) -> list[DatasetOut]:
    """One query each for check counts, open incidents and connection names."""
    from dataquality.alerts.models import Incident
    from dataquality.checks.models import Check

    ids = [d.id for d in rows]
    checks: dict[uuid.UUID, int] = {}
    incidents: dict[uuid.UUID, int] = {}
    names: dict[uuid.UUID, str] = {}
    files: dict[uuid.UUID, tuple[str, str]] = {}
    if ids:
        checks = {
            k: int(v)
            for k, v in (
                await session.execute(
                    select(Check.dataset_id, func.count())
                    .where(Check.dataset_id.in_(ids))
                    .group_by(Check.dataset_id)
                )
            ).all()
        }
        incidents = {
            k: int(v)
            for k, v in (
                await session.execute(
                    select(Incident.dataset_id, func.count())
                    .where(Incident.dataset_id.in_(ids), Incident.status != "resolved")
                    .group_by(Incident.dataset_id)
                )
            ).all()
        }
        file_ids = [d.current_file_id for d in rows if d.current_file_id]
        if file_ids:
            files = {
                fid: (name, fmt)
                for fid, name, fmt in (
                    await session.execute(
                        select(DatasetFile.id, DatasetFile.filename, DatasetFile.format).where(
                            DatasetFile.id.in_(file_ids)
                        )
                    )
                ).all()
            }
        conn_ids = {d.connection_id for d in rows if d.connection_id}
        if conn_ids:
            names = dict(
                (
                    await session.execute(
                        select(Connection.id, Connection.name).where(Connection.id.in_(conn_ids))
                    )
                ).all()
            )
    out = []
    for d in rows:
        item = DatasetOut.model_validate(d)
        out.append(
            item.model_copy(
                update={
                    "has_secret": d.secret_sealed is not None,
                    "checks": checks.get(d.id, 0),
                    "open_incidents": incidents.get(d.id, 0),
                    "connection_name": names.get(d.connection_id) if d.connection_id else None,
                    "file_name": files.get(d.current_file_id, (None, None))[0]
                    if d.current_file_id
                    else None,
                    "file_format": files.get(d.current_file_id, (None, None))[1]
                    if d.current_file_id
                    else None,
                }
            )
        )
    return out


async def list_datasets(session: AsyncSession, project_id: uuid.UUID) -> list[DatasetOut]:
    rows = (
        await session.scalars(
            select(Dataset).where(Dataset.project_id == project_id).order_by(Dataset.name)
        )
    ).all()
    return await to_outs(session, rows)


async def _slug(session: AsyncSession, project_id: uuid.UUID, name: str) -> str:
    base = slugify(name, "dataset")
    slug, n = base, 2
    while await session.scalar(
        select(Dataset.id).where(Dataset.project_id == project_id, Dataset.slug == slug)
    ):
        slug = f"{base[:56]}-{n}"
        n += 1
    return slug


async def _check_name(
    session: AsyncSession, project_id: uuid.UUID, name: str, exclude: uuid.UUID | None = None
) -> None:
    stmt = select(Dataset.id).where(
        Dataset.project_id == project_id, func.lower(Dataset.name) == name.lower()
    )
    if exclude:
        stmt = stmt.where(Dataset.id != exclude)
    if await session.scalar(stmt):
        raise ConflictError("A dataset with this name exists in the project", code="name_taken")


def _guard_sql(kind: str, query: str | None, filter_sql: str | None) -> None:
    try:
        if query:
            check_read_only(query, kind)
        if filter_sql:
            check_predicate(filter_sql, kind)
    except UnsafeSqlError as exc:
        raise AppError(str(exc), code="unsafe_sql") from exc


async def create(
    container: Container, session: AsyncSession, p: Principal, data: DatasetCreate
) -> Dataset:
    await _check_name(session, p.project_id, data.name)
    dialect = "duckdb"
    if data.kind in ("table", "query"):
        conn = await session.scalar(
            select(Connection).where(
                Connection.id == data.connection_id, Connection.project_id == p.project_id
            )
        )
        if conn is None:
            raise NotFoundError("Connection not found")
        dialect = conn.kind
    _guard_sql(dialect, data.query_sql if data.kind == "query" else None, data.filter_sql)
    d = Dataset(
        id=uuid.uuid4(),
        project_id=p.project_id,
        name=data.name.strip(),
        slug=await _slug(session, p.project_id, data.name),
        description=data.description or "",
        kind=data.kind,
        connection_id=data.connection_id if data.kind in ("table", "query") else None,
        schema_name=data.schema_name if data.kind == "table" else None,
        table_name=data.table_name if data.kind == "table" else None,
        query_sql=data.query_sql.strip() if data.kind == "query" and data.query_sql else None,
        options=data.rest.model_dump() if data.kind == "rest" and data.rest else {},
        filter_sql=data.filter_sql or None,
        masked_columns=data.masked_columns or [],
        tags=data.tags or [],
        profile_enabled=True if data.profile_enabled is None else data.profile_enabled,
        scan_timeout_s=data.scan_timeout_s or 1800,
        schedule_cron=data.schedule_cron,
        schedule_tz=data.schedule_tz or "UTC",
        schedule_enabled=bool(data.schedule_enabled and data.schedule_cron),
        created_by=p.user_id,
    )
    if data.kind == "rest" and data.rest_headers:
        d.secret_sealed = await container.sealer.seal(
            orjson.dumps(data.rest_headers).decode(), headers_context(d)
        )
    _apply_schedule(d)
    session.add(d)
    audit(session, p.actor, "dataset.created", "dataset", d.id, name=d.name, kind=d.kind)
    await session.commit()
    return d


async def _dialect(session: AsyncSession, d: Dataset) -> str:
    if d.connection_id is None:
        return "duckdb"
    conn = await session.get(Connection, d.connection_id)
    return conn.kind if conn else "postgresql"


async def update(
    container: Container, session: AsyncSession, p: Principal, d: Dataset, data: DatasetUpdate
) -> Dataset:
    changes = data.model_dump(exclude_unset=True)
    if changes.get("name"):
        await _check_name(session, p.project_id, changes["name"], exclude=d.id)
        d.name = changes["name"].strip()
    _guard_sql(
        await _dialect(session, d),
        changes.get("query_sql") if d.kind == "query" else None,
        changes.get("filter_sql"),
    )
    for field in ("description", "masked_columns", "tags", "profile_enabled", "scan_timeout_s"):
        if field in changes and changes[field] is not None:
            setattr(d, field, changes[field])
    if "filter_sql" in changes:
        d.filter_sql = changes["filter_sql"] or None
    if d.kind == "table":
        for field in ("schema_name", "table_name"):
            if changes.get(field):
                setattr(d, field, changes[field])
    if d.kind == "query" and changes.get("query_sql"):
        d.query_sql = changes["query_sql"].strip()
    if d.kind == "rest" and data.rest is not None:
        d.options = {**(d.options or {}), **data.rest.model_dump()}
    if d.kind == "file" and data.options is not None:
        allowed = {k: v for k, v in data.options.items() if k in ("sheet", "delimiter")}
        d.options = {**(d.options or {}), **allowed}
    if d.kind == "rest" and "rest_headers" in changes:
        headers = changes["rest_headers"]
        d.secret_sealed = (
            await container.sealer.seal(orjson.dumps(headers).decode(), headers_context(d))
            if headers
            else None
        )
    if "schedule_cron" in changes:
        d.schedule_cron = changes["schedule_cron"]
    if changes.get("schedule_tz"):
        d.schedule_tz = changes["schedule_tz"]
    if "schedule_enabled" in changes and changes["schedule_enabled"] is not None:
        d.schedule_enabled = bool(changes["schedule_enabled"])
    if d.schedule_enabled and not d.schedule_cron:
        raise AppError(
            "Set a cron expression before turning the schedule on", code="schedule_needs_cron"
        )
    _apply_schedule(d)
    audit(session, p.actor, "dataset.updated", "dataset", d.id, fields=sorted(changes))
    await session.commit()
    await session.refresh(d)
    return d


async def delete(container: Container, session: AsyncSession, p: Principal, d: Dataset) -> None:
    keys = (
        await session.scalars(select(DatasetFile.storage_key).where(DatasetFile.dataset_id == d.id))
    ).all()
    audit(session, p.actor, "dataset.deleted", "dataset", d.id, name=d.name)
    await session.delete(d)
    await session.commit()
    for key in keys:
        try:
            await container.storage.delete(key)
        except Exception:  # noqa: S112 a leftover object is harmless; the row is gone
            continue


async def _store_version(
    container: Container,
    session: AsyncSession,
    d: Dataset,
    path: Path,
    filename: str,
    fmt: str,
    size: int,
    sha256: str,
    uploaded_by: uuid.UUID | None,
    records: int | None = None,
) -> DatasetFile:
    version = (
        int(
            await session.scalar(
                select(func.coalesce(func.max(DatasetFile.version), 0)).where(
                    DatasetFile.dataset_id == d.id
                )
            )
            or 0
        )
        + 1
    )
    file_id = uuid.uuid4()
    key = f"projects/{d.project_id}/datasets/{d.id}/{file_id}.{fmt}"
    await container.storage.put_file(key, path, CONTENT_TYPES.get(fmt, "application/octet-stream"))
    row = DatasetFile(
        id=file_id,
        dataset_id=d.id,
        version=version,
        filename=filename[:300],
        format=fmt,
        size=size,
        sha256=sha256,
        storage_key=key,
        records=records,
        uploaded_by=uploaded_by,
    )
    session.add(row)
    d.current_file_id = file_id
    return row


async def _spool(
    container: Container, upload: UploadFile, tmp: Path
) -> tuple[Path, int, str, bytes]:
    import hashlib

    limit = container.settings.max_upload_bytes
    path = tmp / "upload"
    digest = hashlib.sha256()
    size = 0
    head = b""
    with path.open("wb") as out:
        while chunk := await upload.read(1024 * 1024):
            if not head:
                head = chunk[:64]
            size += len(chunk)
            if size > limit:
                raise AppError(f"The file is larger than {limit:,} bytes", code="file_too_large")
            digest.update(chunk)
            out.write(chunk)
    if size == 0:
        raise AppError("The file is empty", code="file_empty")
    return path, size, digest.hexdigest(), head


async def upload_file(
    container: Container,
    session: AsyncSession,
    p: Principal,
    upload: UploadFile,
    *,
    dataset: Dataset | None = None,
    name: str | None = None,
    options: dict[str, Any] | None = None,
) -> Dataset:
    """A new file dataset (``dataset`` None) or a new version of one."""
    filename = upload.filename or "upload"
    work = Path(container.settings.work_dir)
    await asyncio.to_thread(work.mkdir, parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=work) as tmp:
        path, size, sha, head = await _spool(container, upload, Path(tmp))
        try:
            fmt = detect_format(filename, head)
        except FileFormatError as exc:
            raise AppError(str(exc), code="unsupported_file") from exc
        if dataset is None:
            label = (name or Path(filename).stem or "Uploaded file").strip()[:120]
            await _check_name(session, p.project_id, label)
            dataset = Dataset(
                id=uuid.uuid4(),
                project_id=p.project_id,
                name=label,
                slug=await _slug(session, p.project_id, label),
                kind="file",
                options={
                    k: v for k, v in (options or {}).items() if k in ("sheet", "delimiter") and v
                },
                created_by=p.user_id,
                schedule_tz="UTC",
            )
            session.add(dataset)
            await session.flush()
            action = "dataset.created"
        elif dataset.kind != "file":
            raise AppError("Only file datasets take uploads", code="not_a_file_dataset")
        else:
            action = "dataset.file_uploaded"
        version = await _store_version(
            container, session, dataset, path, filename, fmt, size, sha, p.user_id
        )
        # Read it once now: a broken file is refused here, not at the first scan.
        spec_dataset = dataset
        try:
            async with source.prepare(container, session, spec_dataset, file_id=version.id) as spec:
                await asyncio.to_thread(
                    source.with_relation, spec, lambda c, d, r, refs: len(r.columns)
                )
        except (FileFormatError, source.SourceUnavailableError) as exc:
            await session.rollback()
            await container.storage.delete(version.storage_key)
            raise AppError(
                str(exc.message if isinstance(exc, AppError) else exc), code="unreadable_file"
            ) from exc
        audit(
            session,
            p.actor,
            action,
            "dataset",
            dataset.id,
            filename=filename,
            version=version.version,
            size=size,
        )
        await session.commit()
        await session.refresh(dataset)
        return dataset


async def versions(session: AsyncSession, d: Dataset) -> Sequence[DatasetFile]:
    return (
        await session.scalars(
            select(DatasetFile)
            .where(DatasetFile.dataset_id == d.id)
            .order_by(DatasetFile.version.desc())
            .limit(100)
        )
    ).all()


async def push_records(
    container: Container,
    session: AsyncSession,
    p: Principal,
    d: Dataset,
    records: list[dict[str, Any]],
) -> DatasetFile:
    """Store a batch of records as the push dataset's newest version."""
    if d.kind != "push":
        raise AppError("Records can only be pushed to a push dataset", code="not_a_push_dataset")
    if len(records) > container.settings.max_push_records:
        raise AppError(
            f"At most {container.settings.max_push_records:,} records per request; split the batch",
            code="too_many_records",
        )
    import hashlib

    from dataquality.sources.rest import flatten

    buf = io.BytesIO()
    for r in records:
        buf.write(orjson.dumps(flatten(r), default=str))
        buf.write(b"\n")
    data = buf.getvalue()
    work = Path(container.settings.work_dir)
    await asyncio.to_thread(work.mkdir, parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=work) as tmp:
        path = Path(tmp) / "batch.ndjson"
        path.write_bytes(data)
        version = await _store_version(
            container,
            session,
            d,
            path,
            f"push-{datetime.now(UTC):%Y%m%dT%H%M%S}.ndjson",
            "ndjson",
            len(data),
            hashlib.sha256(data).hexdigest(),
            p.user_id,
            records=len(records),
        )
    return version


async def preview(
    container: Container, session: AsyncSession, d: Dataset, limit: int = 50
) -> dict[str, Any]:
    try:
        async with source.prepare(container, session, d) as spec:
            data = await asyncio.to_thread(
                source.with_relation, spec, lambda c, _d, r, _refs: source.preview(c, r, limit)
            )
    except AppError:
        raise
    except Exception as exc:  # drivers raise many unrelated types
        from dataquality.connections.service import friendly

        raise AppError(friendly(error_text(exc)), code="source_unreachable") from exc
    masked = {m.lower() for m in d.masked_columns or []}
    if masked:
        data["rows"] = [
            {k: ("[masked]" if k.lower() in masked and v is not None else v) for k, v in r.items()}
            for r in data["rows"]
        ]
    return data
