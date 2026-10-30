"""API application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from dataquality import __version__
from dataquality.alerts.router import router as alerts_router
from dataquality.audit.router import router as audit_router
from dataquality.auth.router import router as auth_router
from dataquality.checks.router import router as checks_router
from dataquality.connections.router import router as connections_router
from dataquality.core.config import Settings, get_settings
from dataquality.core.container import Container
from dataquality.core.db import import_all_models
from dataquality.core.errors import install_error_handlers
from dataquality.core.logs import configure_logging
from dataquality.core.middleware import BodySizeLimitMiddleware, RequestContextMiddleware
from dataquality.core.tracing import configure_tracing
from dataquality.dashboard.router import router as dashboard_router
from dataquality.datasets.router import router as datasets_router
from dataquality.org.router import router as org_router
from dataquality.projects.router import router as projects_router
from dataquality.scans.router import router as scans_router
from dataquality.system.router import router as system_router
from dataquality.users.router import router as users_router

DESCRIPTION = """
API of a self-hosted data quality platform: connect databases, upload files, point at REST
endpoints or push records; profile them, run checks inside the source, score the result,
keep the history, detect anomalies and alert.

* People sign in with `POST /api/v1/auth/login` and send the session token as
  `Authorization: Bearer <token>` (the dashboard uses an HttpOnly cookie instead).
* Applications and CI use a project API key: `Authorization: Bearer dq_...` or
  `X-API-Key: dq_...`. Scopes: `read`, `scan`, `push`, `manage`.
* `POST /api/v1/projects/{project_id}/datasets/{dataset_id}/scans?wait=60` scans a dataset
  and returns the result; `POST .../records` validates a batch of records.
"""


def create_app(settings: Settings | None = None, container: Container | None = None) -> FastAPI:
    settings = settings or get_settings()
    import_all_models()
    configure_logging(settings.log_level)
    configure_tracing(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.container = container or Container.build(settings)
        try:
            yield
        finally:
            if container is None:
                await app.state.container.close()

    app = FastAPI(
        title="Euron Open DataQuality",
        version=__version__,
        description=DESCRIPTION,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url=None,
        openapi_url="/openapi.json",
        separate_input_output_schemas=False,
    )
    install_error_handlers(app)
    for router in (
        auth_router,
        users_router,
        org_router,
        projects_router,
        connections_router,
        datasets_router,
        checks_router,
        scans_router,
        alerts_router,
        dashboard_router,
        audit_router,
        system_router,
    ):
        app.include_router(router)

    app.add_middleware(GZipMiddleware, minimum_size=2048)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "authorization",
            "content-type",
            "x-dq-csrf",
            "x-api-key",
            "x-request-id",
        ],
        expose_headers=["x-request-id", "retry-after", "content-disposition"],
        max_age=600,
    )
    app.add_middleware(BodySizeLimitMiddleware, settings=settings)
    app.add_middleware(RequestContextMiddleware)
    return app
