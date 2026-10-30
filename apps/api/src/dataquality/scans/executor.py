"""Run one claimed scan: open the source, run checks and the profile, store the outcome.

The blocking part runs in a thread. Meanwhile a heartbeat renews the lease every third of
its length and watches for a cancel request; either a lost lease or a cancel sets the stop
flag, which the engine checks between queries.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
import time

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from dataquality.checks.models import Check
from dataquality.checks.service import to_spec
from dataquality.connections.service import friendly
from dataquality.core.container import Container
from dataquality.core.errors import AppError
from dataquality.datasets import source
from dataquality.datasets.models import Dataset
from dataquality.engine.profiler import Profiler
from dataquality.engine.runner import (
    CheckRunner,
    DatasetUnreadableError,
    RunOptions,
    ScanStopped,
    error_text,
)
from dataquality.engine.spec import CheckType
from dataquality.observability.metrics import SCAN_SECONDS
from dataquality.projects.models import Project
from dataquality.scans import complete, queue
from dataquality.scans.models import Scan
from dataquality.sources.files import FileFormatError

log = logging.getLogger("dataquality.scans")


async def _heartbeat(
    container: Container, scan: Scan, worker: str, stop: threading.Event, why: list[str]
) -> None:
    every = container.settings.lease_s / 3
    while not stop.is_set():
        await asyncio.sleep(every)
        try:
            async with container.db.sessionmaker() as session:
                ours, cancel = await queue.renew(
                    session, scan.id, scan.attempt, worker, container.settings.lease_s
                )
        except SQLAlchemyError:
            log.warning("lease renewal failed; retrying", extra={"scan": str(scan.id)})
            continue
        if not ours:
            why.append("lost")
            stop.set()
        elif cancel:
            why.append("cancelled")
            stop.set()


async def execute(container: Container, scan: Scan, worker: str) -> str:
    """Run a scan this worker has claimed. Returns its final status."""
    started = time.monotonic()
    stop = threading.Event()
    why: list[str] = []
    async with container.db.sessionmaker() as session:
        dataset = await session.get(Dataset, scan.dataset_id)
        project = await session.get(Project, scan.project_id)
        if dataset is None or project is None:
            await complete.fail(
                session, scan.id, "The dataset was deleted", attempt=scan.attempt, worker=worker
            )
            return "failed"
        checks = list(
            (
                await session.scalars(
                    select(Check)
                    .where(Check.dataset_id == dataset.id, Check.enabled.is_(True))
                    .order_by(Check.created_at)
                )
            ).all()
        )
        specs = [to_spec(c) for c in checks]
        refs = [str(s.params.get("dataset", "")) for s in specs if s.type == CheckType.REFERENTIAL]
        options = RunOptions(
            sample_size=project.sample_size,
            masked=frozenset(dataset.masked_columns or []),
            deadline=started + dataset.scan_timeout_s,
            should_stop=stop.is_set,
            dataset_filter=dataset.filter_sql,
        )
        profile_enabled = scan.profile
        kind = dataset.kind
        max_rows = container.settings.profile_max_rows

        def run(c, dialect, relation, reference):  # type: ignore[no-untyped-def]
            runner = CheckRunner(c, dialect, relation, options, reference)
            outcomes = runner.run(specs)
            profile = None
            if profile_enabled:
                profile = Profiler(
                    c,
                    dialect,
                    relation,
                    max_rows=max_rows,
                    masked=options.masked,
                    dataset_filter=dataset.filter_sql,
                    should_stop=stop.is_set,
                ).run()
            return complete.RunOutput(runner.row_count, outcomes, list(relation.columns), profile)

        beat = asyncio.create_task(_heartbeat(container, scan, worker, stop, why))
        status, error = "failed", ""
        try:
            async with source.prepare(
                container,
                session,
                dataset,
                file_id=scan.file_id,
                references=refs,
                timeout_s=dataset.scan_timeout_s,
            ) as spec:
                # End the read transaction before the long part: no connection sits idle in
                # a transaction while the source is scanned. (Commit, not rollback: the
                # session keeps its loaded objects; a rollback would expire them.)
                await session.commit()
                out = await asyncio.to_thread(source.with_relation, spec, run)
                out.file_id = spec.file_id
            done = await complete.complete(session, scan.id, scan.attempt, worker, out, checks)
            status = done.status if done else "lost"
        except ScanStopped as exc:
            status = "cancelled" if "cancelled" in why else ("lost" if "lost" in why else "failed")
            error = "Cancelled" if status == "cancelled" else str(exc)
        except (AppError, FileFormatError, DatasetUnreadableError) as exc:
            error = exc.message if isinstance(exc, AppError) else str(exc)
        except (
            Exception
        ) as exc:  # a driver error from the source: report it, do not crash the worker
            log.exception("scan failed", extra={"scan": str(scan.id)})
            error = friendly(error_text(exc))
        finally:
            stop.set()
            beat.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await beat
        if status in ("failed", "cancelled") and error:
            await session.commit()
            await complete.fail(
                session, scan.id, error, attempt=scan.attempt, worker=worker, status=status
            )
    SCAN_SECONDS.labels(kind).observe(time.monotonic() - started)
    log.info(
        "scan finished",
        extra={
            "scan": str(scan.id),
            "status": status,
            "ms": round((time.monotonic() - started) * 1000),
        },
    )
    return status
