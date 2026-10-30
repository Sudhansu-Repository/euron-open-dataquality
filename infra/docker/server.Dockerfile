# syntax=docker/dockerfile:1.7
# ─────────────────────────────────────────────────────────────────────────────
# The API, the scan worker, the CLI and the mock AI (one image):
#   docker build -f infra/docker/server.Dockerfile --target api -t dataquality-api apps/api
# Dependencies come from apps/api/uv.lock. The engines and drivers (duckdb, polars,
# pyarrow, psycopg[binary], pymysql, pymssql with its bundled FreeTDS, reportlab) ship
# manylinux wheels for x86_64 and aarch64, so no compiler or system library is needed.
# ─────────────────────────────────────────────────────────────────────────────
ARG PYTHON_IMAGE=python:3.12.13-slim-bookworm
# Optional Debian mirror for slow routes to deb.debian.org: an http URL ending in /debian
# that also serves <url>-security (e.g. http://ftp.de.debian.org/debian). Empty keeps the
# default.
ARG APT_MIRROR=

FROM ghcr.io/astral-sh/uv:0.9.17 AS uv

FROM ${PYTHON_IMAGE} AS build
COPY --from=uv /uv /uvx /bin/
# Bytecode is compiled here because the runtime root filesystem is read-only.
# The engine wheels are large (pyarrow, polars, duckdb): allow slow routes time to finish.
# UV_CONCURRENT_DOWNLOADS=1 helps on a congested link (docker build --build-arg ...).
ARG UV_CONCURRENT_DOWNLOADS=8
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv UV_HTTP_TIMEOUT=300 \
    UV_CONCURRENT_DOWNLOADS=${UV_CONCURRENT_DOWNLOADS}
WORKDIR /src
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-dev --no-install-project
COPY pyproject.toml uv.lock README.md ./
COPY src src
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-editable

FROM ${PYTHON_IMAGE} AS api
ARG APT_MIRROR
ENV PATH=/opt/venv/bin:$PATH PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 TZ=UTC PORT=8080
RUN if [ -n "${APT_MIRROR}" ]; then \
      sed -i -e "s#^URIs: http://deb.debian.org/debian\$#URIs: ${APT_MIRROR}#" \
             -e "s#^URIs: http://deb.debian.org/debian-security\$#URIs: ${APT_MIRROR}-security#" \
             /etc/apt/sources.list.d/debian.sources; fi
# tini reaps zombies and forwards SIGTERM, so the api drains and the worker finishes its
# running scans. With a read-only root filesystem, mount /tmp (WORK_DIR=/tmp/work) and
# /data writable.
RUN apt-get update && apt-get install -y --no-install-recommends tini ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --system --gid 10001 dataquality \
 && useradd --system --uid 10001 --gid dataquality --home-dir /app --no-create-home \
      --shell /usr/sbin/nologin dataquality \
 && mkdir -p /data/objects /data/work && chown dataquality:dataquality /data/objects /data/work
COPY --from=build /opt/venv /opt/venv
WORKDIR /app
USER 10001:10001
HEALTHCHECK --interval=15s --timeout=3s --start-period=30s --retries=3 \
  CMD python -c "import os, sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:%s/healthz' % os.environ.get('PORT', '8080'), timeout=2).status == 200 else 1)"
ENTRYPOINT ["/usr/bin/tini", "--", "dataquality"]
# 8080 api, 9464 worker /metrics, 4950 mock AI (local only)
EXPOSE 8080 9464 4950
CMD ["serve", "--host", "0.0.0.0", "--port", "8080"]
