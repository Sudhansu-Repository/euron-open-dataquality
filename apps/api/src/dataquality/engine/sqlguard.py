"""Custom SQL is read-only or it is refused.

A custom check's SQL and a dataset's query are parsed with sqlglot in the source's
dialect and accepted only when they are exactly one ``SELECT`` (unions and CTEs of
selects included) that does not lock rows, write into a table, or call a function known
to have side effects or to reach outside the database. This is the first of two locks:
scans also run in a read-only transaction or session wherever the database supports one.
"""

from __future__ import annotations

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

_SQLGLOT_DIALECT = {
    "postgresql": "postgres",
    "mysql": "mysql",
    "sqlite": "sqlite",
    "mssql": "tsql",
    "duckdb": "duckdb",
}

# Functions with side effects, sleeping or file and network access, in any of the dialects.
DENIED_FUNCTIONS = frozenset(
    {
        # PostgreSQL
        "pg_sleep",
        "pg_sleep_for",
        "pg_sleep_until",
        "pg_read_file",
        "pg_read_binary_file",
        "pg_ls_dir",
        "pg_stat_file",
        "pg_terminate_backend",
        "pg_cancel_backend",
        "pg_reload_conf",
        "pg_rotate_logfile",
        "lo_import",
        "lo_export",
        "lo_unlink",
        "dblink",
        "dblink_exec",
        "set_config",
        "nextval",
        "setval",
        "pg_advisory_lock",
        "pg_notify",
        "txid_current",
        "pg_logical_emit_message",
        # MySQL
        "sleep",
        "benchmark",
        "load_file",
        "get_lock",
        "release_lock",
        "sys_exec",
        "sys_eval",
        # SQL Server
        "xp_cmdshell",
        "openrowset",
        "opendatasource",
        "openquery",
        "waitfor",
        # SQLite
        "load_extension",
        "writefile",
        "readfile",
        "edit",
        # DuckDB
        "read_csv",
        "read_csv_auto",
        "read_json",
        "read_json_auto",
        "read_parquet",
        "read_text",
        "read_blob",
        "glob",
        "read_xlsx",
        "parquet_scan",
        "httpfs",
    }
)
_ALLOWED_ROOTS = (exp.Select, exp.Union, exp.Intersect, exp.Except, exp.Subquery)


class UnsafeSqlError(ValueError):
    """The SQL is not a single read-only SELECT."""


def check_read_only(sql: str, dialect: str) -> exp.Expression:
    """Parse ``sql`` and return its tree if it is one read-only query; raise otherwise."""
    name = _SQLGLOT_DIALECT.get(dialect, dialect)
    try:
        statements = [s for s in sqlglot.parse(sql, read=name) if s is not None]
    except ParseError as exc:
        raise UnsafeSqlError(f"the SQL does not parse: {str(exc).splitlines()[0]}") from exc
    if len(statements) != 1:
        raise UnsafeSqlError("use exactly one SELECT statement")
    tree = statements[0]
    if not isinstance(tree, _ALLOWED_ROOTS):
        raise UnsafeSqlError(f"only SELECT is allowed, not {tree.key.upper()}")
    for node in tree.walk():
        if isinstance(
            node,
            exp.Insert
            | exp.Update
            | exp.Delete
            | exp.Merge
            | exp.Create
            | exp.Drop
            | exp.Alter
            | exp.Command
            | exp.Into
            | exp.Lock
            | exp.Set
            | exp.Pragma
            | exp.Copy
            | exp.Use
            | exp.Transaction
            | exp.Commit
            | exp.Rollback,
        ):
            raise UnsafeSqlError(f"{node.key.upper()} is not allowed in a read-only check")
        if isinstance(node, exp.Func):
            fname = (node.sql_name() if not isinstance(node, exp.Anonymous) else node.name).lower()
            if fname in DENIED_FUNCTIONS:
                raise UnsafeSqlError(f"the function {fname} is not allowed")
        if isinstance(node, exp.Table) and isinstance(node.this, exp.Func | exp.Literal):
            raise UnsafeSqlError("table functions and file paths are not allowed")
    return tree


def check_predicate(sql: str, dialect: str) -> str:
    """A filter: a boolean expression over the dataset's columns, nothing else."""
    # Parsed, never executed: the condition is checked inside a dummy query.
    tree = check_read_only(f"SELECT 1 FROM t WHERE {sql}", dialect)  # noqa: S608
    where = tree.find(exp.Where)
    if where is None or tree.find(exp.Subquery) is not None:
        raise UnsafeSqlError("a filter is a plain condition such as status = 'active'")
    return sql
