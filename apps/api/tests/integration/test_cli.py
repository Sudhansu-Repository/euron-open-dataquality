"""The ``dq`` command against the running API: the CI quality gate and checks as code."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import polars as pl
import pytest

from dataquality.client.cli import main
from tests.integration.conftest import Stack

pytestmark = pytest.mark.asyncio


def dq(*argv: str) -> int:
    with pytest.raises(SystemExit) as exit_info:
        main(list(argv))
    return int(exit_info.value.code or 0)


async def test_ci_gate(stack: Stack, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    p = await stack.project()
    path = tmp_path / "orders.csv"
    pl.DataFrame({"id": [1, 2, 2], "total": [1.0, 2.0, 3.0]}).write_csv(path)
    await stack.upload(p["id"], path, "orders")
    key = (
        await stack.ok(
            "POST",
            f"/api/v1/projects/{p['id']}/api-keys",
            {"name": "ci", "scopes": ["read", "scan", "manage", "push"]},
            status=201,
        )
    )["key"]
    common = ["--url", stack.api_url, "--key", key, "--project", p["id"], "--timeout", "60"]
    checks = tmp_path / "orders.yaml"
    checks.write_text(
        "version: 1\nchecks:\n  - name: id unique\n    type: unique\n    column: id\n"
    )
    assert await asyncio.to_thread(dq, *common, "checks", "apply", "orders", str(checks)) == 0
    assert "created 1" in capsys.readouterr().out
    assert await asyncio.to_thread(dq, *common, "scan", "orders") == 1
    out = capsys.readouterr().out
    assert "FAIL id unique" in out
    assert await asyncio.to_thread(dq, *common, "scan", "orders", "--fail-on", "none") == 0
    assert await asyncio.to_thread(dq, *common, "checks", "export", "orders") == 0
    assert "id unique" in capsys.readouterr().out
    assert await asyncio.to_thread(dq, *common, "scan", "missing") == 2
    assert (
        await asyncio.to_thread(
            dq,
            "--url",
            stack.api_url,
            "--key",
            "dq_000000000000_bad",
            "--project",
            p["id"],
            "scan",
            "orders",
        )
        == 2
    )
    d = await stack.ok(
        "POST",
        f"/api/v1/projects/{p['id']}/datasets",
        {"name": "events", "kind": "push"},
        status=201,
    )
    await stack.add_checks(p["id"], d["id"], [{"type": "not_null", "column": "user"}])
    batch = tmp_path / "events.ndjson"
    batch.write_text("\n".join(json.dumps({"user": u}) for u in ["a", None, "c"]))
    assert await asyncio.to_thread(dq, *common, "push", "events", str(batch)) == 1
