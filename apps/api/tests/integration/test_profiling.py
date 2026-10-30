"""AC5 and AC6: profiles describe the data; suggestions come from it without AI and work."""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from tests import golden
from tests.integration.conftest import Sources, Stack, by_name

pytestmark = pytest.mark.asyncio


async def test_profile_matches_the_data(stack: Stack, golden_sources: Sources) -> None:
    p = await stack.project()
    conn = await stack.connection(p["id"], golden_sources.postgres)
    d = await stack.table_dataset(p["id"], conn["id"], "customers")
    await stack.scan(p["id"], d["id"])
    prof = await stack.ok("GET", f"/api/v1/projects/{p['id']}/datasets/{d['id']}/profile")
    assert prof["row_count"] == golden.TOTAL and prof["sampled"] is False
    cols = {c["name"]: c for c in prof["columns"]}
    email = cols["email"]
    assert email["logical"] == "text" and email["nulls"] == 5 and email["blanks"] == 3
    assert email["semantic"]["email"] > 0.95
    cid = cols["customer_id"]
    assert (
        cid["distinct"] == golden.BASE_ROWS and cid["min"] == 1 and cid["max"] == golden.BASE_ROWS
    )
    price = cols["price"]
    assert (
        len(price["histogram"]) == 10
        and sum(b["count"] for b in price["histogram"]) == golden.TOTAL
    )
    assert set(price["quantiles"]) == {"p5", "p25", "p50", "p75", "p95"}
    country = cols["country"]
    assert country["top_values"][0]["value"] in ("IN", "US", "GB", "AE")
    assert cols["zip_code"]["shapes"][0]["shape"] == "999999"
    preview = await stack.ok(
        "GET", f"/api/v1/projects/{p['id']}/datasets/{d['id']}/preview?limit=5"
    )
    assert len(preview["rows"]) == 5 and {c["name"] for c in preview["columns"]} == set(cols)


async def test_suggestions_from_clean_data_catch_the_defects(
    stack: Stack, tmp_path: Path, golden_sources: Sources
) -> None:
    clean = [r for r in golden.rows()[: golden.BASE_ROWS] if r["customer_id"] > 100]
    path = tmp_path / "clean_customers.csv"
    pl.DataFrame(clean).write_csv(path)
    p = await stack.project()
    d = await stack.upload(p["id"], path, "customers")
    await stack.scan(p["id"], d["id"])
    suggestions = await stack.ok(
        "GET", f"/api/v1/projects/{p['id']}/datasets/{d['id']}/suggestions"
    )
    keys = {s["key"] for s in suggestions}
    for expected in (
        "not_null:email",
        "unique:customer_id",
        "pattern:email",
        "range:price",
        "accepted_values:country",
        "schema:*",
        "duplicate_rows:*",
    ):
        assert expected in keys, (expected, sorted(keys))
    picked = [
        {k: s[k] for k in ("type", "column", "params", "severity")}
        for s in suggestions
        if s["type"] not in ("row_count", "outliers", "freshness")
    ]
    await stack.ok(
        "POST",
        f"/api/v1/projects/{p['id']}/datasets/{d['id']}/checks/bulk",
        {"checks": picked, "origin": "suggested"},
        status=201,
    )
    clean_scan = await stack.scan(p["id"], d["id"])
    failing = [r for r in clean_scan["results"] if r["status"] != "pass"]
    assert not failing, failing
    assert clean_scan["score"] == 100.0
    # The same checks against the golden data catch its defects.
    v2 = golden_sources.files["csv"]
    with v2.open("rb") as f:
        resp = await stack.client.post(
            f"/api/v1/projects/{p['id']}/datasets/{d['id']}/files",
            files={"file": ("customers.csv", f)},
        )
    assert resp.status_code == 201, resp.text
    bad = await stack.scan(p["id"], d["id"])
    results = by_name(bad)
    assert results["email not null"]["failed"] == 8
    assert results["customer_id unique"]["failed"] == 3
    assert results["email pattern (email)"]["failed"] == 4
    assert results["price range"]["failed"] == 4
    assert bad["score"] < 100.0
    versions = await stack.ok("GET", f"/api/v1/projects/{p['id']}/datasets/{d['id']}/files")
    assert [v["version"] for v in versions] == [2, 1]
