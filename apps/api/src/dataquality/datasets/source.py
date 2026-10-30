"""From a stored dataset to an open, read-only relation, in two steps:

1. ``prepare`` (async, in the event loop): open sealed secrets, download files to a private
   temp directory, fetch REST records. The result is a plain ``SourceSpec``.
2. ``with_relation`` (sync, in a worker thread): open the database or DuckDB, describe the
   relation and the referenced datasets, and call the given function with them.

The split keeps every blocking driver call off the event loop, and every network call and
secret out of the thread.
"""

from __future__ import annotations

import asyncio
import contextlib
import tempfile
import uuid
from collections.abc import AsyncIterator, Callable, Iterable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import orjson
from sqlalchemy import or_, select
from sqlalchemy.engine import Connection as SqlConnection
from sqlalchemy.ext.asyncio import AsyncSession

from dataquality.connections import service as connections
from dataquality.connections.models import Connection
from dataquality.core.container import Container
from dataquality.core.errors import AppError
from dataquality.datasets.models import Dataset, DatasetFile
from dataquality.engine.relation import Relation, query_relation, reflect_table
from dataquality.sources import rest
from dataquality.sources.files import FileTable, open_files, table_name
from dataquality.sources.sql import SqlTarget, open_sql

FILE_KINDS = ("file", "rest", "push")


@dataclass
class RelationSpec:
    dataset_id: uuid.UUID
    names: tuple[str, ...]  # how checks may refer to it: id, slug, name
    kind: str
    schema: str | None = None
    table: str | None = None
    query: str | None = None
    file_table: FileTable | None = None


@dataclass
class SourceSpec:
    dialect: str
    main: RelationSpec
    refs: list[RelationSpec] = field(default_factory=list)
    sql: SqlTarget | None = None
    files: list[FileTable] = field(default_factory=list)
    timeout_s: int = 300
    # The whole scan: DuckDB and SQLite have no per-statement timeout, so for them this
    # is the deadline at which whatever runs is interrupted.
    scan_timeout_s: int = 1800
    memory_limit: str = "2GB"
    temp_dir: Path | None = None
    file_id: uuid.UUID | None = None


class SourceUnavailableError(AppError):
    code = "source_unavailable"


async def _file_version(
    session: AsyncSession, dataset: Dataset, file_id: uuid.UUID | None
) -> DatasetFile | None:
    wanted = file_id or dataset.current_file_id
    if wanted is None:
        return None
    return await session.scalar(
        select(DatasetFile).where(DatasetFile.id == wanted, DatasetFile.dataset_id == dataset.id)
    )


async def _materialise(
    container: Container,
    session: AsyncSession,
    dataset: Dataset,
    tmp: Path,
    file_id: uuid.UUID | None,
) -> tuple[FileTable, uuid.UUID | None]:
    """A file, REST or push dataset as a local file DuckDB can read."""
    name = table_name(dataset.slug)
    if dataset.kind == "rest":
        headers: dict[str, str] = {}
        if dataset.secret_sealed:
            opened = await container.sealer.open(
                dataset.secret_sealed, f"dataset:{dataset.id}:headers"
            )
            headers = {str(k): str(v) for k, v in orjson.loads(opened).items()}
        opts = dataset.options or {}
        try:
            records = await rest.fetch_records(
                container.http,
                str(opts.get("url", "")),
                headers=headers,
                records_path=opts.get("records_path"),
                max_bytes=container.settings.rest_max_bytes,
                allow_private=container.settings.outbound_allow_private,
            )
        except rest.RestSourceError as exc:
            raise SourceUnavailableError(f"The REST endpoint could not be read: {exc}") from exc
        if not records:
            raise SourceUnavailableError("The REST endpoint returned no records")
        path = tmp / f"{name}.ndjson"
        await asyncio.to_thread(rest.write_ndjson, records, path)
        return FileTable(name, path, "ndjson", {}), None
    version = await _file_version(session, dataset, file_id)
    if version is None:
        what = (
            "no records have been pushed" if dataset.kind == "push" else "no file has been uploaded"
        )
        raise SourceUnavailableError(f"Nothing to scan yet: {what} for {dataset.name}")
    path = tmp / f"{name}.{version.format}"
    await container.storage.get_file(version.storage_key, path)
    return FileTable(name, path, version.format, dict(dataset.options or {})), version.id


def _names(d: Dataset) -> tuple[str, ...]:
    return (str(d.id), d.slug, d.name)


async def referenced(session: AsyncSession, dataset: Dataset, refs: Iterable[str]) -> list[Dataset]:
    """Datasets named by referential checks, in the same project and the same source."""
    wanted = {r for r in refs if r}
    if not wanted:
        return []
    ids = []
    for r in wanted:
        with contextlib.suppress(ValueError):
            ids.append(uuid.UUID(r))
    rows = (
        await session.scalars(
            select(Dataset).where(
                Dataset.project_id == dataset.project_id,
                Dataset.id != dataset.id,
                or_(Dataset.slug.in_(wanted), Dataset.name.in_(wanted), Dataset.id.in_(ids)),
            )
        )
    ).all()
    same: list[Dataset] = []
    for d in rows:
        if (dataset.kind in FILE_KINDS and d.kind in FILE_KINDS) or (
            dataset.kind not in FILE_KINDS and d.connection_id == dataset.connection_id
        ):
            same.append(d)
    return same


@asynccontextmanager
async def prepare(
    container: Container,
    session: AsyncSession,
    dataset: Dataset,
    *,
    file_id: uuid.UUID | None = None,
    references: Iterable[str] = (),
    timeout_s: int | None = None,
) -> AsyncIterator[SourceSpec]:
    settings = container.settings
    timeout = min(timeout_s or settings.statement_timeout_s, settings.statement_timeout_s)
    scan_timeout = timeout_s or dataset.scan_timeout_s
    work = Path(settings.work_dir)
    await asyncio.to_thread(work.mkdir, parents=True, exist_ok=True)
    refs = await referenced(session, dataset, references)
    with tempfile.TemporaryDirectory(dir=work, prefix="scan-") as tmp_name:
        tmp = Path(tmp_name)
        if dataset.kind in FILE_KINDS:
            main_file, used = await _materialise(container, session, dataset, tmp, file_id)
            main = RelationSpec(dataset.id, _names(dataset), dataset.kind, file_table=main_file)
            ref_specs = []
            files = [main_file]
            for r in refs:
                try:
                    ft, _ = await _materialise(container, session, r, tmp, None)
                except SourceUnavailableError:
                    continue
                files.append(ft)
                ref_specs.append(RelationSpec(r.id, _names(r), r.kind, file_table=ft))
            yield SourceSpec(
                dialect="duckdb",
                main=main,
                refs=ref_specs,
                files=files,
                timeout_s=timeout,
                scan_timeout_s=scan_timeout,
                memory_limit=settings.duckdb_memory_limit,
                temp_dir=tmp,
                file_id=used,
            )
            return
        conn = await session.get(Connection, dataset.connection_id)
        if conn is None or conn.project_id != dataset.project_id:
            raise SourceUnavailableError("The dataset's connection no longer exists")
        main = RelationSpec(
            dataset.id,
            _names(dataset),
            dataset.kind,
            schema=dataset.schema_name,
            table=dataset.table_name,
            query=dataset.query_sql,
        )
        ref_specs = [
            RelationSpec(
                r.id, _names(r), r.kind, schema=r.schema_name, table=r.table_name, query=r.query_sql
            )
            for r in refs
        ]
        async with connections.target(container, conn) as target:
            yield SourceSpec(
                dialect=conn.kind,
                main=main,
                refs=ref_specs,
                sql=target,
                timeout_s=timeout,
                scan_timeout_s=scan_timeout,
            )


def _relation(c: SqlConnection, dialect: str, spec: RelationSpec) -> Relation:
    if spec.file_table is not None:
        return reflect_table(c, spec.file_table.name)
    if spec.kind == "query" and spec.query:
        return query_relation(c, spec.query, dialect)
    if spec.table:
        return reflect_table(c, spec.table, spec.schema)
    raise SourceUnavailableError("The dataset names no table or query")


def with_relation[T](
    spec: SourceSpec,
    fn: Callable[[SqlConnection, str, Relation, Callable[[str], Relation | None]], T],
) -> T:
    """Open the source, describe the relation, run ``fn``. Call it in a worker thread."""

    def run(c: SqlConnection) -> T:
        try:
            relation = _relation(c, spec.dialect, spec.main)
        except LookupError as exc:
            raise SourceUnavailableError(str(exc)) from exc
        cache: dict[str, Relation | None] = {}

        def reference(name: str) -> Relation | None:
            if name not in cache:
                match = next((r for r in spec.refs if name in r.names), None)
                try:
                    cache[name] = _relation(c, spec.dialect, match) if match else None
                except (LookupError, SourceUnavailableError):
                    cache[name] = None
            return cache[name]

        return fn(c, spec.dialect, relation, reference)

    if spec.dialect == "duckdb":
        with open_files(
            spec.files,
            memory_limit=spec.memory_limit,
            temp_dir=spec.temp_dir,
            timeout_s=spec.scan_timeout_s,
        ) as c:
            return run(c)
    assert spec.sql is not None
    timeout = spec.scan_timeout_s if spec.sql.kind == "sqlite" else spec.timeout_s
    with open_sql(spec.sql, timeout) as c:
        return run(c)


def preview(c: SqlConnection, relation: Relation, limit: int = 50) -> dict[str, Any]:
    import sqlalchemy as sa

    from dataquality.engine.runner import jsonable

    cols = [relation.c(col.name) for col in relation.columns]
    result = c.execute(sa.select(*cols).select_from(relation.from_).limit(limit))
    names = list(result.keys())
    return {
        "columns": [
            {"name": col.name, "type": col.logical, "native": col.native}
            for col in relation.columns
        ],
        "rows": [
            dict(zip(names, [jsonable(v) for v in r], strict=True)) for r in result.fetchall()
        ],
    }
