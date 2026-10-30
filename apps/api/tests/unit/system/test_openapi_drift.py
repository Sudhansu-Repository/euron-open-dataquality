"""The committed API document matches the app: regenerate it with `make openapi` after any
change to a route or a schema, or this test fails."""

from __future__ import annotations

from pathlib import Path

from dataquality.openapi import spec, to_yaml

DOC = Path(__file__).resolve().parents[5] / "docs/api/openapi.yaml"


def test_the_committed_openapi_document_matches_the_app() -> None:
    assert DOC.read_text(encoding="utf-8") == to_yaml(spec()), "run `make openapi` and commit it"
