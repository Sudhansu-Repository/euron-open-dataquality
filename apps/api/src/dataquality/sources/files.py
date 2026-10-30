"""Files become DuckDB tables, so they are checked by the same SQL compiler as databases.

The worker opens an in-memory DuckDB per scan, loads the dataset's file (and any file
dataset a referential check points at) as tables, then locks DuckDB down: no file or
network access and no configuration changes, so a custom SQL check cannot read anything
but the loaded tables.

CSV, TSV, JSON (an array or one object per line) and Parquet are read by DuckDB itself.
Excel goes through Polars (the calamine reader) into Arrow and then DuckDB.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import Connection
from sqlalchemy.pool import StaticPool

EXTENSIONS = {
    ".csv": "csv",
    ".tsv": "tsv",
    ".tab": "tsv",
    ".txt": "csv",
    ".json": "json",
    ".jsonl": "ndjson",
    ".ndjson": "ndjson",
    ".parquet": "parquet",
    ".pq": "parquet",
    ".xlsx": "xlsx",
    ".xlsm": "xlsx",
}
CONTENT_TYPES = {
    "csv": "text/csv",
    "tsv": "text/tab-separated-values",
    "json": "application/json",
    "ndjson": "application/x-ndjson",
    "parquet": "application/vnd.apache.parquet",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


class FileFormatError(ValueError):
    """The file cannot be read as the format it claims."""


def detect_format(filename: str, head: bytes) -> str:
    """The format from the extension, confirmed by the first bytes where they can tell."""
    ext = Path(filename).suffix.lower()
    fmt = EXTENSIONS.get(ext)
    if head.startswith(b"PAR1"):
        return "parquet"
    if head.startswith(b"PK\x03\x04") and fmt == "xlsx":
        return "xlsx"
    if fmt in ("parquet", "xlsx"):
        raise FileFormatError(f"the file does not look like {fmt}")
    if fmt is None:
        stripped = head.lstrip()
        if stripped.startswith((b"[", b"{")):
            return "json"
        raise FileFormatError(
            "unknown file type; upload CSV, TSV, JSON, NDJSON, Parquet or Excel (.xlsx)"
        )
    return fmt


def table_name(name: str) -> str:
    """A safe DuckDB identifier for a dataset (its slug)."""
    ident = re.sub(r"[^a-z0-9_]", "_", name.lower()).strip("_") or "data"
    return ident if not ident[0].isdigit() else f"t_{ident}"


@dataclass(frozen=True)
class FileTable:
    name: str
    path: Path
    format: str
    options: dict[str, Any]


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _load(conn: Connection, t: FileTable) -> None:
    raw = conn.connection.dbapi_connection
    assert raw is not None
    quoted = '"' + t.name.replace('"', '""') + '"'
    path = _sql_literal(t.path.as_posix())
    opts = t.options
    if t.format in ("csv", "tsv"):
        delim = opts.get("delimiter") or ("\t" if t.format == "tsv" else None)
        args = ["header = true", "sample_size = -1"]
        if delim:
            args.append(f"delim = {_sql_literal(str(delim)[:4])}")
        reader = f"read_csv({path}, {', '.join(args)})"
    elif t.format in ("json", "ndjson"):
        fmt = "newline_delimited" if t.format == "ndjson" else "auto"
        reader = f"read_json({path}, format = '{fmt}', sample_size = -1)"
    elif t.format == "parquet":
        reader = f"read_parquet({path})"
    elif t.format == "xlsx":
        import polars as pl

        sheet = opts.get("sheet")
        try:
            frame = pl.read_excel(
                t.path, sheet_name=str(sheet) if sheet else None, engine="calamine"
            )
        except Exception as exc:  # calamine raises its own error types
            raise FileFormatError(f"the Excel file could not be read: {exc}") from exc
        arrow = frame.to_arrow()
        raw.register("_xlsx", arrow)
        raw.execute(f"CREATE TABLE {quoted} AS SELECT * FROM _xlsx")  # noqa: S608 quoted identifier
        raw.unregister("_xlsx")
        return
    else:
        raise FileFormatError(f"unsupported format {t.format}")
    try:
        raw.execute(f"CREATE TABLE {quoted} AS SELECT * FROM {reader}")  # noqa: S608 quoted identifier and literals
    except Exception as exc:  # duckdb raises its own error types
        message = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
        raise FileFormatError(f"the {t.format.upper()} file could not be read: {message}") from exc


@contextmanager
def open_files(
    tables: list[FileTable],
    *,
    memory_limit: str = "2GB",
    temp_dir: Path | None = None,
    timeout_s: int = 300,
) -> Iterator[Connection]:
    """An in-memory DuckDB with the files loaded and every outside access switched off."""
    engine = sa.create_engine("duckdb:///:memory:", poolclass=StaticPool)
    timer: threading.Timer | None = None
    try:
        with engine.connect() as conn:
            raw = conn.connection.dbapi_connection
            assert raw is not None
            raw.execute(f"SET memory_limit = {_sql_literal(memory_limit)}")
            raw.execute("SET threads = 4")
            if temp_dir is not None:
                raw.execute(f"SET temp_directory = {_sql_literal(temp_dir.as_posix())}")
            for t in tables:
                _load(conn, t)
            raw.execute("SET enable_external_access = false")
            raw.execute("SET autoload_known_extensions = false")
            raw.execute("SET lock_configuration = true")
            # DuckDB has no statement timeout: interrupt whatever runs at the deadline.
            timer = threading.Timer(timeout_s, raw.interrupt)
            timer.daemon = True
            timer.start()
            yield conn
    finally:
        if timer is not None:
            timer.cancel()
        engine.dispose()
