from __future__ import annotations

import uuid

from fastapi import APIRouter, File, Form, Response, UploadFile

from dataquality.connections import service
from dataquality.connections.schemas import (
    ConnectionOut,
    ConnectionUpdate,
    ServerConnection,
    TableOut,
    TestResult,
)
from dataquality.core.deps import ContainerDep, SessionDep
from dataquality.projects.access import Editor, Viewer

router = APIRouter(prefix="/api/v1/projects/{project_id}/connections", tags=["connections"])


@router.get("", response_model=list[ConnectionOut], summary="Database connections")
async def list_connections(p: Viewer, session: SessionDep) -> list[ConnectionOut]:
    return await service.list_connections(session, p.project_id)


@router.post("", response_model=ConnectionOut, status_code=201, summary="Add a database server")
async def create_connection(
    body: ServerConnection, p: Editor, session: SessionDep, container: ContainerDep
) -> ConnectionOut:
    return service.to_out(await service.create_server(container, session, p, body))


@router.post(
    "/sqlite", response_model=ConnectionOut, status_code=201, summary="Add a SQLite database file"
)
async def create_sqlite(
    p: Editor,
    session: SessionDep,
    container: ContainerDep,
    name: str = Form(min_length=1, max_length=120),
    file: UploadFile = File(...),
) -> ConnectionOut:
    return service.to_out(await service.create_sqlite(container, session, p, name, file))


@router.post("/test", response_model=TestResult, summary="Test a connection before saving it")
async def test_unsaved(body: ServerConnection, p: Editor, container: ContainerDep) -> TestResult:
    return await service.test(
        container, service.unsaved(p.project_id, body), password=body.password or ""
    )


@router.get("/{connection_id}", response_model=ConnectionOut, summary="One connection")
async def get_connection(connection_id: uuid.UUID, p: Viewer, session: SessionDep) -> ConnectionOut:
    return service.to_out(await service.get(session, p.project_id, connection_id))


@router.patch("/{connection_id}", response_model=ConnectionOut, summary="Change a connection")
async def update_connection(
    connection_id: uuid.UUID,
    body: ConnectionUpdate,
    p: Editor,
    session: SessionDep,
    container: ContainerDep,
) -> ConnectionOut:
    conn = await service.get(session, p.project_id, connection_id)
    return service.to_out(await service.update(container, session, p, conn, body))


@router.delete(
    "/{connection_id}", status_code=204, summary="Delete a connection (no datasets may use it)"
)
async def delete_connection(
    connection_id: uuid.UUID, p: Editor, session: SessionDep, container: ContainerDep
) -> Response:
    conn = await service.get(session, p.project_id, connection_id)
    await service.delete(container, session, p, conn)
    return Response(status_code=204)


@router.post("/{connection_id}/test", response_model=TestResult, summary="Test a saved connection")
async def test_connection(
    connection_id: uuid.UUID, p: Editor, session: SessionDep, container: ContainerDep
) -> TestResult:
    conn = await service.get(session, p.project_id, connection_id)
    result = await service.test(container, conn)
    await service.record_test(session, conn, result)
    return result


@router.get("/{connection_id}/tables", response_model=list[TableOut], summary="Tables and views")
async def list_tables(
    connection_id: uuid.UUID,
    p: Viewer,
    session: SessionDep,
    container: ContainerDep,
    schema: str | None = None,
) -> list[TableOut]:
    conn = await service.get(session, p.project_id, connection_id)
    return [
        TableOut(schema_name=t.schema, name=t.name, kind=t.kind)
        for t in await service.tables(container, conn, schema)
    ]
