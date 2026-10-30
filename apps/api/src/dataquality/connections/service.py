"""Connections to source databases: stored with a sealed password, tested and browsed.

Every query against a source runs in a worker thread through ``sources.sql.open_sql``
(read-only, statement timeout). The host is checked twice: as typed (no metadata address)
and as it resolves at connect time, so a DNS name pointing at instance metadata is refused.
"""

from __future__ import annotations

import asyncio
import hashlib
import tempfile
import time
import uuid
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from dataquality.audit.service import audit
from dataquality.connections.models import Connection
from dataquality.connections.schemas import (
    ConnectionOut,
    ConnectionUpdate,
    ServerConnection,
    TestResult,
)
from dataquality.core.container import Container
from dataquality.core.errors import AppError, ConflictError, NotFoundError
from dataquality.core.net import resolves_safely
from dataquality.engine.runner import error_text
from dataquality.projects.access import Principal
from dataquality.sources.sql import (
    DEFAULT_PORTS,
    SqlTarget,
    TableRef,
    list_tables,
    open_sql,
    server_version,
)

SQLITE_MAGIC = b"SQLite format 3\x00"


def secret_context(conn: Connection) -> str:
    return f"connection:{conn.id}:password"


def to_out(c: Connection, datasets: int = 0) -> ConnectionOut:
    cfg = c.config or {}
    return ConnectionOut(
        id=c.id,
        name=c.name,
        kind=c.kind,
        host=cfg.get("host"),
        port=cfg.get("port"),
        database=cfg.get("database"),
        username=cfg.get("username"),
        ssl_mode=cfg.get("ssl_mode"),
        default_schema=cfg.get("default_schema"),
        has_password=c.secret_sealed is not None,
        file_name=c.file_name,
        file_size=c.file_size,
        max_concurrent_scans=c.max_concurrent_scans,
        last_tested_at=c.last_tested_at,
        last_test_ok=c.last_test_ok,
        last_test_message=c.last_test_message,
        server_version=c.server_version,
        datasets=datasets,
        created_at=c.created_at,
    )


async def get(session: AsyncSession, project_id: uuid.UUID, connection_id: uuid.UUID) -> Connection:
    conn = await session.scalar(
        select(Connection).where(
            Connection.id == connection_id, Connection.project_id == project_id
        )
    )
    if conn is None:
        raise NotFoundError("Connection not found")
    return conn


async def list_connections(session: AsyncSession, project_id: uuid.UUID) -> list[ConnectionOut]:
    from dataquality.datasets.models import Dataset

    counts = dict(
        (
            await session.execute(
                select(Dataset.connection_id, func.count())
                .where(Dataset.project_id == project_id, Dataset.connection_id.is_not(None))
                .group_by(Dataset.connection_id)
            )
        ).all()
    )
    rows: Sequence[Connection] = (
        await session.scalars(
            select(Connection).where(Connection.project_id == project_id).order_by(Connection.name)
        )
    ).all()
    return [to_out(c, int(counts.get(c.id, 0))) for c in rows]


async def _unique_name(
    session: AsyncSession, project_id: uuid.UUID, name: str, exclude: uuid.UUID | None = None
) -> None:
    stmt = select(Connection.id).where(Connection.project_id == project_id, Connection.name == name)
    if exclude:
        stmt = stmt.where(Connection.id != exclude)
    if await session.scalar(stmt):
        raise ConflictError("A connection with this name exists in the project", code="name_taken")


async def create_server(
    container: Container, session: AsyncSession, p: Principal, data: ServerConnection
) -> Connection:
    await _unique_name(session, p.project_id, data.name)
    conn = Connection(
        id=uuid.uuid4(),
        project_id=p.project_id,
        name=data.name.strip(),
        kind=data.kind,
        config={
            "host": data.host,
            "port": data.port or DEFAULT_PORTS[data.kind],
            "database": data.database,
            "username": data.username,
            "ssl_mode": data.ssl_mode,
            "default_schema": data.default_schema,
        },
        max_concurrent_scans=data.max_concurrent_scans,
        created_by=p.user_id,
    )
    if data.password:
        conn.secret_sealed = await container.sealer.seal(data.password, secret_context(conn))
    session.add(conn)
    audit(
        session,
        p.actor,
        "connection.created",
        "connection",
        conn.id,
        name=conn.name,
        kind=conn.kind,
    )
    await session.commit()
    return conn


async def create_sqlite(
    container: Container, session: AsyncSession, p: Principal, name: str, upload: UploadFile
) -> Connection:
    """A SQLite database file, kept in object storage and opened read-only by scans."""
    await _unique_name(session, p.project_id, name)
    conn_id = uuid.uuid4()
    key = f"projects/{p.project_id}/connections/{conn_id}.sqlite"
    size, _ = await store_upload(
        container, upload, key, "application/vnd.sqlite3", magic=SQLITE_MAGIC
    )
    conn = Connection(
        id=conn_id,
        project_id=p.project_id,
        name=name.strip(),
        kind="sqlite",
        config={},
        file_key=key,
        file_name=(upload.filename or "database.sqlite")[:300],
        file_size=size,
        max_concurrent_scans=4,
        created_by=p.user_id,
    )
    session.add(conn)
    audit(
        session, p.actor, "connection.created", "connection", conn.id, name=conn.name, kind="sqlite"
    )
    await session.commit()
    return conn


async def store_upload(
    container: Container,
    upload: UploadFile,
    key: str,
    content_type: str,
    *,
    magic: bytes | None = None,
) -> tuple[int, str]:
    """Stream an upload to a temp file (hashing it), check its size and magic, store it."""
    limit = container.settings.max_upload_bytes
    digest = hashlib.sha256()
    size = 0
    work = Path(container.settings.work_dir)
    await asyncio.to_thread(work.mkdir, parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=work, delete=True) as tmp:
        head = b""
        while chunk := await upload.read(1024 * 1024):
            if not head:
                head = chunk[:64]
            size += len(chunk)
            if size > limit:
                raise AppError(f"The file is larger than {limit:,} bytes", code="file_too_large")
            digest.update(chunk)
            tmp.write(chunk)
        tmp.flush()
        if size == 0:
            raise AppError("The file is empty", code="file_empty")
        if magic is not None and not head.startswith(magic):
            raise AppError("This is not a SQLite database file", code="not_sqlite")
        await container.storage.put_file(key, Path(tmp.name), content_type)
    return size, digest.hexdigest()


async def update(
    container: Container,
    session: AsyncSession,
    p: Principal,
    conn: Connection,
    data: ConnectionUpdate,
) -> Connection:
    changes = data.model_dump(exclude_unset=True)
    password = changes.pop("password", None)
    if changes.get("name"):
        await _unique_name(session, p.project_id, changes["name"], exclude=conn.id)
        conn.name = changes.pop("name").strip()
    if changes.get("max_concurrent_scans"):
        conn.max_concurrent_scans = changes.pop("max_concurrent_scans")
    if conn.kind != "sqlite":
        cfg = dict(conn.config or {})
        for field in ("host", "port", "database", "username", "ssl_mode", "default_schema"):
            if field in changes and (changes[field] is not None or field == "default_schema"):
                cfg[field] = changes[field]
        conn.config = cfg
    if password is not None:
        conn.secret_sealed = (
            await container.sealer.seal(password, secret_context(conn)) if password else None
        )
    audit(
        session,
        p.actor,
        "connection.updated",
        "connection",
        conn.id,
        fields=sorted(data.model_dump(exclude_unset=True)),
    )
    await session.commit()
    await session.refresh(conn)
    return conn


async def delete(
    container: Container, session: AsyncSession, p: Principal, conn: Connection
) -> None:
    from dataquality.datasets.models import Dataset

    used = await session.scalar(
        select(func.count()).select_from(Dataset).where(Dataset.connection_id == conn.id)
    )
    if used:
        raise ConflictError(
            f"{used} dataset{'s use' if used != 1 else ' uses'} this connection. Delete or "
            f"move them first",
            code="connection_in_use",
        )
    audit(session, p.actor, "connection.deleted", "connection", conn.id, name=conn.name)
    await session.delete(conn)
    await session.commit()
    if conn.file_key:
        await container.storage.delete(conn.file_key)


@asynccontextmanager
async def target(
    container: Container, conn: Connection, password: str | None = None
) -> AsyncIterator[SqlTarget]:
    """Everything needed to open the source: the sealed password opened, the SQLite file
    fetched to a private temp dir (removed afterwards), the host checked as it resolves."""
    cfg: dict[str, Any] = conn.config or {}
    if conn.kind == "sqlite":
        if not conn.file_key:
            raise AppError("This SQLite connection has no database file", code="sqlite_missing")
        work = Path(container.settings.work_dir)
        await asyncio.to_thread(work.mkdir, parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=work) as tmp:
            path = Path(tmp) / "source.sqlite"
            await container.storage.get_file(conn.file_key, path)
            yield SqlTarget(kind="sqlite", sqlite_path=str(path))
        return
    host, port = str(cfg.get("host", "")), int(cfg.get("port") or DEFAULT_PORTS[conn.kind])
    if not await resolves_safely(
        f"tcp://{host}:{port}", allow_private=container.settings.source_allow_private
    ):
        raise AppError(
            "The host resolves to an address this deployment refuses (metadata, or private when "
            "SOURCE_ALLOW_PRIVATE=false)",
            code="host_refused",
        )
    if password is None and conn.secret_sealed:
        password = await container.sealer.open(conn.secret_sealed, secret_context(conn))
    yield SqlTarget(
        kind=conn.kind,
        host=host,
        port=port,
        database=str(cfg.get("database", "")),
        username=str(cfg.get("username", "")),
        password=password,
        ssl_mode=str(cfg.get("ssl_mode") or "prefer"),
    )


def _probe(t: SqlTarget, timeout_s: int, schema: str | None) -> tuple[str, int]:
    with open_sql(t, timeout_s) as c:
        version = server_version(c)
        tables = len(list_tables(c, schema))
    return version, tables


async def test(
    container: Container, conn: Connection, *, password: str | None = None, timeout_s: int = 20
) -> TestResult:
    started = time.perf_counter()
    try:
        async with target(container, conn, password) as t:
            version, tables = await asyncio.wait_for(
                asyncio.to_thread(_probe, t, timeout_s, (conn.config or {}).get("default_schema")),
                timeout=timeout_s + 10,
            )
    except TimeoutError:
        return TestResult(ok=False, message="The database did not answer in time", ms=_ms(started))
    except AppError as exc:
        return TestResult(ok=False, message=exc.message, ms=_ms(started))
    except Exception as exc:  # drivers raise many unrelated types; the message is what matters
        return TestResult(ok=False, message=friendly(error_text(exc)), ms=_ms(started))
    return TestResult(
        ok=True,
        message=f"Connected. {tables} tables and views visible",
        server_version=version,
        tables=tables,
        ms=_ms(started),
    )


def _ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)


def friendly(message: str) -> str:
    """Driver errors, rewritten to say what to check."""
    m = message.lower()
    if "password authentication failed" in m or "access denied" in m or "login failed" in m:
        return "The username or password was refused. Check them, and that the user may log in"
    if ("does not exist" in m and "database" in m) or "unknown database" in m:
        return "The database name was not found on the server"
    if (
        "could not translate host" in m
        or "name or service not known" in m
        or "nodename nor servname" in m
    ):
        return "The host name could not be resolved. Check the spelling, or use an IP address"
    if "connection refused" in m or "can't connect" in m or "unable to connect" in m:
        return (
            "Nothing answered on that host and port. Check the port, firewall and that "
            "the database is running"
        )
    if "timeout" in m or "timed out" in m:
        return "The connection timed out. Check that the database is reachable from this deployment"
    if "ssl" in m:
        return f"The SSL handshake failed ({message[:160]}). Try another SSL mode"
    return message


async def record_test(session: AsyncSession, conn: Connection, result: TestResult) -> None:
    conn.last_tested_at = datetime.now(UTC)
    conn.last_test_ok = result.ok
    conn.last_test_message = result.message
    if result.server_version:
        conn.server_version = result.server_version
    await session.commit()


async def tables(container: Container, conn: Connection, schema: str | None) -> list[TableRef]:
    def run(t: SqlTarget) -> list[TableRef]:
        with open_sql(t, 30) as c:
            return list_tables(c, schema or (conn.config or {}).get("default_schema"))

    try:
        async with target(container, conn) as t:
            return await asyncio.to_thread(run, t)
    except AppError:
        raise
    except Exception as exc:  # drivers raise many unrelated types
        raise AppError(friendly(error_text(exc)), code="source_unreachable") from exc


def unsaved(project_id: uuid.UUID, data: ServerConnection) -> Connection:
    """A connection that is only tested, never stored."""
    return Connection(
        id=uuid.uuid4(),
        project_id=project_id,
        name=data.name,
        kind=data.kind,
        config={
            "host": data.host,
            "port": data.port or DEFAULT_PORTS[data.kind],
            "database": data.database,
            "username": data.username,
            "ssl_mode": data.ssl_mode,
            "default_schema": data.default_schema,
        },
    )
