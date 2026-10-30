"""Integration harness: the real API served over HTTP from a background thread and the real
scan worker running in another, against real Postgres, Redis and source databases.

    make test-integration      (starts Postgres, Redis and the source databases if needed)

Isolation: every run uses its own database (``TEST_DATABASE_URL``) and Redis DB index
(``TEST_REDIS_URL``). The suite drops and recreates the database, so it refuses any
database whose name does not contain "test" and any non-local host unless
ALLOW_REMOTE_TEST_DB=true. Source databases get a ``dq_source_test`` database with the
golden data and a read-only login, rebuilt once per session.
"""

from __future__ import annotations

import asyncio
import os
import socket
import threading
import time
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
import pytest
import redis.asyncio as aioredis
import uvicorn
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from dataquality.core.config import Settings
from tests import sources

TEST_DB = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://dataquality:dataquality@localhost:4942/dataquality_test",
)
TEST_REDIS = os.environ.get("TEST_REDIS_URL", "redis://localhost:4979/15")
ADMIN = {"email": "admin@example.test", "password": "Admin-Pass-123"}
CSRF = {"x-dq-csrf": "1"}


def _guard(url: str) -> None:
    parsed = urlparse(url.replace("+asyncpg", ""))
    if "test" not in (parsed.path or ""):
        raise RuntimeError(f"refusing {parsed.path!r}: the test database name must contain 'test'")
    if (
        parsed.hostname not in ("localhost", "127.0.0.1", "postgres")
        and os.environ.get("ALLOW_REMOTE_TEST_DB") != "true"
    ):
        raise RuntimeError("refusing a non-local test database (set ALLOW_REMOTE_TEST_DB=true)")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class Served:
    """An ASGI app (or import string) served by uvicorn on a thread, with its own loop."""

    def __init__(self, app: Any, port: int | None = None) -> None:
        self.port = port or free_port()
        self.url = f"http://127.0.0.1:{self.port}"
        config = uvicorn.Config(app, host="127.0.0.1", port=self.port, log_level="warning")
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def start(self, health: str = "/healthz") -> Served:
        self.thread.start()
        deadline = time.time() + 60
        while time.time() < deadline:
            try:
                if httpx.get(self.url + health, timeout=1).status_code < 500:
                    return self
            except httpx.HTTPError:
                pass
            time.sleep(0.1)
        raise RuntimeError(f"server on {self.url} did not start")

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=15)


class WorkerThread:
    """The real scan worker (``dataquality.worker.serve``) on its own thread and loop."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.loop = asyncio.new_event_loop()
        self.stop_event: asyncio.Event | None = None
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.ready = threading.Event()

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._main())

    async def _main(self) -> None:
        from dataquality.core.container import Container
        from dataquality.worker import import_task_modules, serve

        import_task_modules()
        container = Container.build(self.settings)
        self.stop_event = asyncio.Event()
        self.ready.set()
        try:
            await serve(container, self.stop_event, self.settings)
        finally:
            await container.close()

    def start(self) -> WorkerThread:
        self.thread.start()
        self.ready.wait(10)
        return self

    def stop(self) -> None:
        if self.stop_event is not None:
            self.loop.call_soon_threadsafe(self.stop_event.set)
        self.thread.join(timeout=60)


@pytest.fixture(scope="session")
def mock_ai() -> Iterator[str]:
    served = Served("mockai.app:app").start()
    yield served.url
    served.stop()


@pytest.fixture(scope="session")
async def database() -> AsyncIterator[str]:
    """A fresh database built by the migrations (so they are tested on every run)."""
    _guard(TEST_DB)
    admin_url = TEST_DB.rsplit("/", 1)[0] + "/postgres"
    name = TEST_DB.rsplit("/", 1)[1]
    engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    async with engine.connect() as conn:
        await conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        await conn.execute(text(f'CREATE DATABASE "{name}"'))
    await engine.dispose()
    from dataquality.migrations.runner import upgrade

    await asyncio.to_thread(upgrade, TEST_DB)
    yield TEST_DB


@dataclass(frozen=True)
class Sources:
    postgres: sources.DbSource
    mysql: sources.DbSource
    mssql: sources.DbSource | None
    sqlite: Path
    files: dict[str, Path]
    order_files: dict[str, Path]


@pytest.fixture(scope="session")
def golden_sources(tmp_path_factory: pytest.TempPathFactory) -> Sources:
    """The golden data in every source kind, built once per session."""
    base = tmp_path_factory.mktemp("golden")
    mssql = sources.load_mssql() if sources.mssql_available() else None
    orders_dir = base / "orders"
    orders_dir.mkdir()
    return Sources(
        postgres=sources.load_postgres(),
        mysql=sources.load_mysql(),
        mssql=mssql,
        sqlite=sources.sqlite_file(base / "golden.sqlite"),
        files=sources.write_files(base),
        order_files=sources.write_files(orders_dir, "orders"),
    )


def make_settings(database: str, tmp_path: Path, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "environment": "test",
        "database_url": database,
        "redis_url": TEST_REDIS,
        "session_secret": "test-only-session-secret-with-32-plus-bytes",
        "api_key_pepper": "test-only-api-key-pepper-with-32-plus-bytes",
        "local_master_key": "test-only-master-key-with-32-plus-bytes-ok",
        "local_storage_dir": str(tmp_path / "objects"),
        "work_dir": str(tmp_path / "work"),
        "public_url": "http://localhost:4910",
        "mail_backend": "log",
        "scan_rpm": 10_000,
        "lease_s": 15.0,
        "worker_poll_interval_s": 0.2,
        "task_interval_s": 0.5,
        "worker_metrics_port": 0,
        "worker_concurrency": 3,
        "outbound_allow_private": True,
        # The option matrix (make test-matrix) reruns the suite against Floci S3 and KMS.
        "key_mode": os.environ.get("TEST_KEY_MODE", "local"),
        "storage": os.environ.get("TEST_STORAGE", "local"),
        "aws_endpoint_url": os.environ.get("TEST_AWS_ENDPOINT"),
        "s3_force_path_style": True,
        "kms_key_id": os.environ.get("TEST_KMS_KEY_ID", "alias/dataquality-local"),
        "objects_bucket": os.environ.get("TEST_OBJECTS_BUCKET", "dataquality-local-objects"),
    }
    values.update(overrides)
    return Settings(**values)


async def reset(database: str) -> None:
    """Empty every table and the Redis DB between tests."""
    engine = create_async_engine(database)
    async with engine.begin() as conn:
        tables = (
            await conn.execute(
                text(
                    "SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
                    "AND tablename NOT IN ('alembic_version', 'audit_log')"
                )
            )
        ).scalars()
        names = ", ".join(f'"{t}"' for t in tables)
        if names:
            await conn.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))
    await engine.dispose()
    r = aioredis.Redis.from_url(TEST_REDIS)
    await r.flushdb()
    await r.aclose()


async def bootstrap_admin(database: str) -> None:
    from dataquality.core.db import Database
    from dataquality.core.security import hash_password
    from dataquality.users.models import User

    db = Database(database, pool_size=1, max_overflow=0)
    async with db.sessionmaker() as session:
        session.add(
            User(
                email=ADMIN["email"],
                name="Admin",
                role="admin",
                password_hash=hash_password(ADMIN["password"]),
            )
        )
        await session.commit()
    await db.dispose()


@dataclass
class Stack:
    """The running API and worker, a signed-in admin, and helpers."""

    api_url: str
    settings: Settings
    client: httpx.AsyncClient
    mock_ai_url: str
    worker: WorkerThread | None

    async def ok(
        self,
        method: str,
        path: str,
        json: Any = None,
        status: int | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> Any:
        c = client or self.client
        resp = await c.request(method, path, json=json)
        expected = status or (201 if method == "POST" and resp.status_code == 201 else 200)
        assert resp.status_code == expected, f"{method} {path}: {resp.status_code} {resp.text}"
        if not resp.content:
            return None
        if "json" not in resp.headers.get("content-type", ""):
            return resp.content
        return resp.json()

    async def user(
        self, role: str = "user", email: str | None = None, name: str = "Test User"
    ) -> httpx.AsyncClient:
        """Create a user with the admin client and return a client signed in as them."""
        email = email or f"{role}-{time.monotonic_ns()}@example.test"
        password = "User-Pass-123"
        await self.ok(
            "POST",
            "/api/v1/users",
            {"email": email, "name": name, "role": role, "password": password},
            status=201,
        )
        client = await login(self.api_url, {"email": email, "password": password})
        client.headers["x-test-email"] = email
        return client

    async def project(self, name: str = "Acme Data") -> dict[str, Any]:
        return dict(await self.ok("POST", "/api/v1/projects", {"name": name}, status=201))

    async def connection(
        self, project_id: str, src: sources.DbSource, name: str | None = None
    ) -> dict[str, Any]:
        body = {
            "name": name or f"{src.kind} source",
            "kind": src.kind,
            "host": src.host,
            "port": src.port,
            "database": src.database,
            "username": src.username,
            "password": src.password,
            "ssl_mode": "disable" if src.kind == "postgresql" else "prefer",
        }
        return dict(
            await self.ok("POST", f"/api/v1/projects/{project_id}/connections", body, status=201)
        )

    async def table_dataset(
        self, project_id: str, connection_id: str, table: str, name: str | None = None
    ) -> dict[str, Any]:
        body = {
            "name": name or table,
            "kind": "table",
            "connection_id": connection_id,
            "table_name": table,
        }
        return dict(
            await self.ok("POST", f"/api/v1/projects/{project_id}/datasets", body, status=201)
        )

    async def upload(
        self,
        project_id: str,
        path: Path,
        name: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> dict[str, Any]:
        c = client or self.client
        with path.open("rb") as f:
            resp = await c.post(
                f"/api/v1/projects/{project_id}/datasets/upload",
                files={"file": (path.name, f)},
                data={"name": name or path.stem},
            )
        assert resp.status_code == 201, resp.text
        return dict(resp.json())

    async def add_checks(
        self, project_id: str, dataset_id: str, checks: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        out = await self.ok(
            "POST",
            f"/api/v1/projects/{project_id}/datasets/{dataset_id}/checks/bulk",
            {"checks": checks},
            status=201,
        )
        return list(out["checks"])

    async def scan(
        self,
        project_id: str,
        dataset_id: str,
        *,
        wait: float = 120,
        client: httpx.AsyncClient | None = None,
        **body: Any,
    ) -> dict[str, Any]:
        c = client or self.client
        resp = await c.post(
            f"/api/v1/projects/{project_id}/datasets/{dataset_id}/scans",
            params={"wait": wait},
            json=body or None,
        )
        assert resp.status_code in (200, 202), resp.text
        data: dict[str, Any] = resp.json()
        if data["status"] in ("queued", "running") and wait:
            raise AssertionError(f"scan did not finish in {wait}s: {data['status']}")
        return data


async def login(base_url: str, creds: dict[str, str] = ADMIN) -> httpx.AsyncClient:
    client = httpx.AsyncClient(base_url=base_url, timeout=180, headers=CSRF)
    resp = await client.post("/api/v1/auth/login", json=creds)
    assert resp.status_code == 200, resp.text
    client.headers["authorization"] = f"Bearer {resp.json()['session_token']}"
    return client


@pytest.fixture
def settings_overrides() -> dict[str, Any]:
    """Tests override this to change the API's and the worker's settings."""
    return {}


@pytest.fixture
def run_worker() -> bool:
    """Tests that drive the queue by hand override this to False."""
    return True


@pytest.fixture
async def stack(
    database: str,
    tmp_path: Path,
    mock_ai: str,
    settings_overrides: dict[str, Any],
    run_worker: bool,
) -> AsyncIterator[Stack]:
    from dataquality.main import create_app

    await reset(database)
    await bootstrap_admin(database)
    settings = make_settings(database, tmp_path, **settings_overrides)
    served = Served(create_app(settings)).start()
    worker = WorkerThread(settings).start() if run_worker else None
    client = await login(served.url)
    try:
        yield Stack(served.url, settings, client, mock_ai, worker)
    finally:
        await client.aclose()
        if worker is not None:
            worker.stop()
        served.stop()


def by_name(scan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {r["check_name"]: r for r in scan["results"]}
