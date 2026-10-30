"""Checks: validated against their type's parameter model before anything is stored, plus
checks as code (YAML import and export, idempotent by name)."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

import yaml
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dataquality.audit.service import audit
from dataquality.checks.models import Check
from dataquality.checks.schemas import BulkResult, CheckIn, CheckOut, CheckUpdate, LastResult
from dataquality.core.errors import AppError, ConflictError, NotFoundError
from dataquality.datasets.models import Dataset
from dataquality.engine.spec import DEFAULT_DIMENSION, CheckSpec, CheckType, Tolerance
from dataquality.engine.sqlguard import UnsafeSqlError, check_predicate
from dataquality.projects.access import Principal

YAML_VERSION = 1


def default_name(t: CheckType, column: str | None, params: dict[str, Any]) -> str:
    label = t.value.replace("_", " ")
    extra = ""
    if t == CheckType.PATTERN and params.get("preset"):
        extra = f" ({params['preset']})"
    elif t == CheckType.TYPE and params.get("type"):
        extra = f" ({params['type']})"
    return f"{column} {label}{extra}" if column else label


def to_spec(c: Check) -> CheckSpec:
    return CheckSpec(
        key=str(c.id),
        type=CheckType(c.type),
        column=c.column,
        params=c.params or {},
        filter=c.filter_sql,
        severity=c.severity,
        tolerance=Tolerance.model_validate(c.tolerance or {}),
        dimension=c.dimension,
    )


def validate(data: CheckIn, dialect: str = "duckdb") -> CheckSpec:
    """The single gate for a check's shape; raises ``AppError`` with the reason."""
    try:
        spec = CheckSpec(
            key="new",
            type=data.type,
            column=data.column,
            params=data.params,
            filter=data.filter_sql,
            severity=data.severity,
            tolerance=data.tolerance,
            dimension=data.dimension,
        )
    except ValidationError as exc:
        first = exc.errors(include_url=False)[0]
        where = ".".join(str(x) for x in first.get("loc", ()) if x not in ("params",))
        raise AppError(
            f"Invalid {data.type.value} check: {first.get('msg', 'invalid')}"
            + (f" ({where})" if where else ""),
            code="invalid_check",
            details={
                "errors": [
                    {"loc": list(e.get("loc", ())), "msg": e.get("msg", "")}
                    for e in exc.errors(include_url=False)
                ]
            },
        ) from exc
    if data.filter_sql and data.type in (
        CheckType.ROW_COUNT,
        CheckType.FRESHNESS,
        CheckType.SCHEMA,
        CheckType.CUSTOM_SQL,
    ):
        raise AppError(
            f"A {data.type.value} check takes no filter: it judges the whole dataset (use the "
            "dataset's filter, or put the condition in the SQL)",
            code="filter_not_supported",
        )
    if data.filter_sql:
        try:
            check_predicate(data.filter_sql, dialect)
        except UnsafeSqlError as exc:
            raise AppError(str(exc), code="unsafe_sql") from exc
    if data.type == CheckType.CUSTOM_SQL:
        from dataquality.engine.sqlguard import check_read_only

        try:
            check_read_only(str(data.params.get("sql", "")).replace("{table}", "t"), dialect)
        except UnsafeSqlError as exc:
            raise AppError(str(exc), code="unsafe_sql") from exc
    return spec


async def get(session: AsyncSession, project_id: uuid.UUID, check_id: uuid.UUID) -> Check:
    c = await session.scalar(
        select(Check).where(Check.id == check_id, Check.project_id == project_id)
    )
    if c is None:
        raise NotFoundError("Check not found")
    return c


async def list_checks(session: AsyncSession, d: Dataset) -> list[CheckOut]:
    """The dataset's checks with each one's latest result, in two queries."""
    from dataquality.scans.models import CheckResult

    rows = (
        await session.scalars(
            select(Check).where(Check.dataset_id == d.id).order_by(Check.created_at, Check.name)
        )
    ).all()
    last: dict[uuid.UUID, LastResult] = {}
    if d.last_scan_id:
        for r in (
            await session.scalars(select(CheckResult).where(CheckResult.scan_id == d.last_scan_id))
        ).all():
            if r.check_id:
                last[r.check_id] = LastResult(
                    scan_id=r.scan_id,
                    status=r.status,
                    evaluated=r.evaluated,
                    failed=r.failed,
                    failed_pct=r.failed_pct,
                    message=r.message,
                )
    return [CheckOut.model_validate(c).model_copy(update={"last": last.get(c.id)}) for c in rows]


async def _dialect(session: AsyncSession, d: Dataset) -> str:
    from dataquality.connections.models import Connection

    if d.connection_id is None:
        return "duckdb"
    conn = await session.get(Connection, d.connection_id)
    return conn.kind if conn else "postgresql"


def _row(
    d: Dataset, data: CheckIn, spec: CheckSpec, name: str, origin: str, user: uuid.UUID | None
) -> Check:
    return Check(
        project_id=d.project_id,
        dataset_id=d.id,
        name=name,
        description=data.description,
        type=spec.type.value,
        column=spec.column,
        params=spec.params,
        filter_sql=data.filter_sql or None,
        severity=spec.severity.value,
        tolerance=spec.tolerance.model_dump(exclude_none=True),
        dimension=(data.dimension or DEFAULT_DIMENSION[spec.type]).value,
        enabled=data.enabled,
        origin=origin,
        created_by=user,
    )


async def create(
    session: AsyncSession, p: Principal, d: Dataset, data: CheckIn, origin: str = "manual"
) -> Check:
    spec = validate(data, await _dialect(session, d))
    name = (data.name or default_name(spec.type, spec.column, spec.params)).strip()
    if await session.scalar(select(Check.id).where(Check.dataset_id == d.id, Check.name == name)):
        raise ConflictError(f"A check named {name!r} exists on this dataset", code="name_taken")
    c = _row(d, data, spec, name, origin, p.user_id)
    session.add(c)
    await session.flush()
    audit(
        session, p.actor, "check.created", "check", c.id, dataset=d.slug, type=c.type, name=c.name
    )
    await session.commit()
    return c


async def bulk_create(
    session: AsyncSession, p: Principal, d: Dataset, items: list[CheckIn], origin: str
) -> BulkResult:
    """Create many (suggestions accepted at once); names already taken are skipped."""
    dialect = await _dialect(session, d)
    existing = set(
        (await session.scalars(select(Check.name).where(Check.dataset_id == d.id))).all()
    )
    created: list[Check] = []
    skipped: list[str] = []
    for data in items:
        spec = validate(data, dialect)
        name = (data.name or default_name(spec.type, spec.column, spec.params)).strip()
        if name in existing:
            skipped.append(name)
            continue
        existing.add(name)
        c = _row(d, data, spec, name, origin, p.user_id)
        session.add(c)
        created.append(c)
    await session.flush()
    audit(
        session, p.actor, "check.bulk_created", "dataset", d.id, created=len(created), origin=origin
    )
    await session.commit()
    return BulkResult(
        created=len(created), skipped=skipped, checks=[CheckOut.model_validate(c) for c in created]
    )


async def update(
    session: AsyncSession, p: Principal, c: Check, d: Dataset, data: CheckUpdate
) -> Check:
    changes = data.model_dump(exclude_unset=True)
    merged = CheckIn(
        name=changes.get("name") or c.name,
        description=changes["description"]
        if changes.get("description") is not None
        else c.description,
        type=CheckType(c.type),
        column=changes.get("column", c.column),
        params=changes["params"] if changes.get("params") is not None else c.params,
        filter_sql=changes.get("filter_sql", c.filter_sql),
        severity=changes.get("severity") or c.severity,
        tolerance=data.tolerance
        if data.tolerance is not None
        else Tolerance.model_validate(c.tolerance or {}),
        dimension=changes.get("dimension") or c.dimension,
        enabled=c.enabled if changes.get("enabled") is None else bool(changes["enabled"]),
    )
    spec = validate(merged, await _dialect(session, d))
    if merged.name != c.name and await session.scalar(
        select(Check.id).where(
            Check.dataset_id == c.dataset_id, Check.name == merged.name, Check.id != c.id
        )
    ):
        raise ConflictError(
            f"A check named {merged.name!r} exists on this dataset", code="name_taken"
        )
    c.name = str(merged.name)
    c.description = merged.description
    c.column = spec.column
    c.params = spec.params
    c.filter_sql = merged.filter_sql or None
    c.severity = spec.severity.value
    c.tolerance = spec.tolerance.model_dump(exclude_none=True)
    c.dimension = spec.effective_dimension.value
    c.enabled = merged.enabled
    audit(session, p.actor, "check.updated", "check", c.id, fields=sorted(changes))
    await session.commit()
    await session.refresh(c)
    return c


async def delete(session: AsyncSession, p: Principal, c: Check) -> None:
    audit(session, p.actor, "check.deleted", "check", c.id, name=c.name)
    await session.delete(c)
    await session.commit()


# Checks as code -------------------------------------------------------------------------


def export_yaml(d: Dataset, checks: Sequence[Check]) -> str:
    items = []
    for c in checks:
        item: dict[str, Any] = {"name": c.name, "type": c.type}
        if c.column:
            item["column"] = c.column
        if c.params:
            item["params"] = c.params
        if c.filter_sql:
            item["filter"] = c.filter_sql
        if c.severity != "error":
            item["severity"] = c.severity
        if c.tolerance:
            item["tolerance"] = c.tolerance
        if c.dimension != DEFAULT_DIMENSION[CheckType(c.type)].value:
            item["dimension"] = c.dimension
        if not c.enabled:
            item["enabled"] = False
        if c.description:
            item["description"] = c.description
        items.append(item)
    doc = {"version": YAML_VERSION, "dataset": d.slug, "checks": items}
    return yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=100)


def parse_yaml(text: str) -> list[CheckIn]:
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise AppError(
            f"The YAML does not parse: {str(exc).splitlines()[0]}", code="invalid_yaml"
        ) from exc
    if not isinstance(doc, dict) or not isinstance(doc.get("checks"), list):
        raise AppError("The YAML needs a top-level 'checks' list", code="invalid_yaml")
    if doc.get("version", YAML_VERSION) != YAML_VERSION:
        raise AppError(
            f"Unsupported version {doc.get('version')!r}; this server reads version {YAML_VERSION}",
            code="invalid_yaml",
        )
    out = []
    for i, raw in enumerate(doc["checks"]):
        if not isinstance(raw, dict) or "type" not in raw:
            raise AppError(f"Check {i + 1} needs a type", code="invalid_yaml")
        try:
            out.append(
                CheckIn(
                    name=raw.get("name"),
                    description=raw.get("description", ""),
                    type=raw["type"],
                    column=raw.get("column"),
                    params=raw.get("params") or {},
                    filter_sql=raw.get("filter"),
                    severity=raw.get("severity", "error"),
                    tolerance=raw.get("tolerance") or {},
                    dimension=raw.get("dimension"),
                    enabled=raw.get("enabled", True),
                )
            )
        except ValidationError as exc:
            msg = exc.errors(include_url=False)[0].get("msg", "invalid")
            raise AppError(
                f"Check {i + 1} ({raw.get('name') or raw.get('type')}): {msg}", code="invalid_yaml"
            ) from exc
    return out


async def apply_yaml(
    session: AsyncSession, p: Principal, d: Dataset, text: str, prune: bool
) -> BulkResult:
    """Upsert by name: new names are created, existing ones replaced, and with ``prune``
    checks missing from the file are deleted. Applying the same file twice changes nothing."""
    items = parse_yaml(text)
    dialect = await _dialect(session, d)
    existing = {
        c.name: c
        for c in (await session.scalars(select(Check).where(Check.dataset_id == d.id))).all()
    }
    created = updated = 0
    seen: set[str] = set()
    for data in items:
        spec = validate(data, dialect)
        name = (data.name or default_name(spec.type, spec.column, spec.params)).strip()
        if name in seen:
            raise AppError(f"The file names the check {name!r} twice", code="invalid_yaml")
        seen.add(name)
        row = _row(d, data, spec, name, "yaml", p.user_id)
        current = existing.get(name)
        if current is None:
            session.add(row)
            created += 1
            continue
        fields = (
            "type",
            "column",
            "params",
            "filter_sql",
            "severity",
            "tolerance",
            "dimension",
            "enabled",
            "description",
        )
        if any(getattr(current, f) != getattr(row, f) for f in fields):
            for f in fields:
                setattr(current, f, getattr(row, f))
            updated += 1
    removed = [c for n, c in existing.items() if n not in seen] if prune else []
    for c in removed:
        await session.delete(c)
    audit(
        session,
        p.actor,
        "check.yaml_applied",
        "dataset",
        d.id,
        created=created,
        updated=updated,
        removed=len(removed),
    )
    await session.commit()
    return BulkResult(created=created, updated=updated, removed=[c.name for c in removed])
