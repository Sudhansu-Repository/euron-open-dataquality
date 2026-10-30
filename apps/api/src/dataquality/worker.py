"""The scan worker: runs queued scans and the periodic tasks (scheduler, lease reaper,
alert delivery, retention, queue gauges).

Stateless and safe to run as several replicas: scans are claimed with ``FOR UPDATE SKIP
LOCKED`` and leased (``scans/queue.py``), tasks claim their rows the same way. Up to
``WORKER_CONCURRENCY`` scans run at once, each in its own thread for the source drivers.
SIGTERM stops claiming, lets running scans finish (their leases keep them safe if the
process is killed instead), then exits. Prometheus metrics on WORKER_METRICS_PORT.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import signal
import socket
import time

from prometheus_client import start_http_server

from dataquality.core.config import Settings, get_settings
from dataquality.core.container import Container
from dataquality.core.db import import_all_models
from dataquality.core.logs import configure_logging
from dataquality.core.tasks import tasks
from dataquality.dashboard.router import version_key
from dataquality.scans import executor, queue

log = logging.getLogger("dataquality.worker")


def import_task_modules() -> None:
    """Every module that registers a periodic task."""
    from dataquality.scans import tasks as _scans  # noqa: F401


def worker_name() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


async def tick(container: Container) -> bool:
    """One pass over every periodic task. True when any of them did work."""
    busy = False
    for name, task in tasks().items():
        try:
            handled = await task(container)
        except Exception:
            log.exception("task %s failed", name)
            continue
        if handled:
            log.info("task done", extra={"task": name, "items": handled})
            busy = True
    return busy


async def run_one(container: Container, name: str) -> bool:
    """Claim and run one scan. False when the queue had nothing for this worker."""
    async with container.db.sessionmaker() as session:
        scan = await queue.claim(session, name, container.settings.lease_s)
    if scan is None:
        return False
    try:
        await executor.execute(container, scan, name)
    finally:
        with contextlib.suppress(Exception):
            await container.kv.incr(version_key(scan.project_id))
    return True


async def serve(container: Container, stop: asyncio.Event, settings: Settings) -> None:
    name = worker_name()
    wake = asyncio.Event()

    async def scanner(slot: int) -> None:
        while not stop.is_set():
            try:
                worked = await run_one(container, f"{name}#{slot}")
            except Exception:
                log.exception("scan loop failed")
                worked = False
            if not worked:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(wake.wait(), timeout=settings.worker_poll_interval_s)
                wake.clear()

    async def periodic() -> None:
        while not stop.is_set():
            started = time.monotonic()
            busy = await tick(container)
            if busy:
                wake.set()  # the scheduler may have queued scans
            delay = (
                0.5 if busy else max(settings.task_interval_s - (time.monotonic() - started), 0.5)
            )
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=delay)

    workers = [asyncio.create_task(scanner(i)) for i in range(settings.worker_concurrency)]
    background = asyncio.create_task(periodic())
    await stop.wait()
    log.info("stopping: finishing running scans")
    background.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await background
    await asyncio.gather(*workers, return_exceptions=True)


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    import_all_models()
    import_task_modules()
    if settings.worker_metrics_port:
        start_http_server(settings.worker_metrics_port)
    container = Container.build(settings)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    log.info("worker started", extra={"concurrency": settings.worker_concurrency})
    try:
        await serve(container, stop, settings)
    finally:
        await container.close()
        log.info("worker stopped")
