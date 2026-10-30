"""The engine's pure parts: SQL guard, patterns, specs, dialect SQL, scoring, anomalies,
suggestions and profiling."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
import sqlalchemy as sa
from pydantic import ValidationError
from sqlalchemy.dialects import mssql, mysql, postgresql, sqlite

from dataquality.engine.anomaly import detect
from dataquality.engine.dialects import Exact, Shape, StrLen, blank, full_match, supports_regex
from dataquality.engine.patterns import PRESETS, TYPE_PATTERNS, anchored, shape, validate_regex
from dataquality.engine.profiler import Profiler
from dataquality.engine.relation import duckdb_logical, logical_of, logical_of_value
from dataquality.engine.scoring import ScoredResult, score
from dataquality.engine.spec import CheckSpec, CheckType, Dimension, Tolerance, parse_params
from dataquality.engine.sqlguard import UnsafeSqlError, check_predicate, check_read_only
from dataquality.engine.suggest import suggest
from dataquality.sources.files import FileTable, open_files
from tests import sources

# SQL guard ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM t WHERE a > 1",
        "WITH x AS (SELECT a FROM t) SELECT * FROM x",
        "SELECT a FROM t UNION ALL SELECT a FROM u",
        "SELECT count(*) FROM t GROUP BY a HAVING count(*) > 1",
    ],
)
def test_read_only_sql_passes(sql: str) -> None:
    for dialect in ("postgresql", "mysql", "sqlite", "mssql", "duckdb"):
        check_read_only(sql, dialect)


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM t",
        "UPDATE t SET a = 1",
        "INSERT INTO t VALUES (1)",
        "DROP TABLE t",
        "SELECT 1; SELECT 2",
        "SELECT * INTO x FROM t",
        "SELECT pg_sleep(10)",
        "SELECT sleep(10)",
        "SELECT * FROM t FOR UPDATE",
        "SELECT load_file('/etc/passwd')",
        "SELECT * FROM read_parquet('s3://x')",
        "WITH d AS (DELETE FROM t RETURNING *) SELECT * FROM d",
        "SELEC broken",
    ],
)
def test_writes_and_tricks_are_refused(sql: str) -> None:
    with pytest.raises(UnsafeSqlError):
        check_read_only(sql, "postgresql")


def test_filters_are_plain_conditions() -> None:
    assert check_predicate("status = 'active' AND amount > 0", "postgresql")
    for bad in ("1=1; DROP TABLE t", "a IN (SELECT a FROM secrets)"):
        with pytest.raises(UnsafeSqlError):
            check_predicate(bad, "postgresql")


# Patterns and specs ------------------------------------------------------------------


def test_presets_match_their_examples() -> None:
    import re

    for name, p in PRESETS.items():
        assert re.fullmatch(p.regex, p.example), name
    assert re.fullmatch(TYPE_PATTERNS["datetime"], "2026-10-30T10:15:00Z")
    assert not re.fullmatch(TYPE_PATTERNS["date"], "2026-13-01")
    assert anchored("a|b") == "^(?:a|b)$"
    assert shape("KA-01 ab 99") == "AA-99 aa 99"


@pytest.mark.parametrize("bad", ["\\d+", "(?=x)", "(a)\\1", "(?i)abc", "[[:alpha:]]", "(", " "])
def test_non_portable_regex_is_refused(bad: str) -> None:
    with pytest.raises(ValueError):
        validate_regex(bad)


def test_params_are_validated_per_type() -> None:
    assert parse_params(CheckType.RANGE, {"min": 0}).min == 0  # type: ignore[attr-defined]
    for t, params in [
        (CheckType.RANGE, {}),
        (CheckType.RANGE, {"min": 5, "max": 1}),
        (CheckType.PATTERN, {"preset": "email", "regex": "a"}),
        (CheckType.LENGTH, {"min": 3, "max": 1}),
        (CheckType.ROW_COUNT, {}),
        (CheckType.NOT_NULL, {"surprise": True}),
    ]:
        with pytest.raises(ValidationError):
            parse_params(t, params)
    with pytest.raises(ValidationError):
        CheckSpec(key="x", type="not_null")
    spec = CheckSpec(key="x", type="unique", column="id")
    assert spec.effective_dimension == Dimension.UNIQUENESS


def test_tolerance() -> None:
    assert Tolerance().allows(0, 10) and not Tolerance().allows(1, 10)
    assert Tolerance(max_count=2).allows(2, 10) and not Tolerance(max_count=2).allows(3, 10)
    assert Tolerance(max_percent=10).allows(1, 10) and not Tolerance(max_percent=10).allows(2, 10)
    assert not Tolerance(max_count=5, max_percent=1).allows(2, 10)
    assert not Tolerance(max_percent=50).allows(1, 0)


# Dialect SQL -------------------------------------------------------------------------


def compiled(expr: object, dialect: object) -> str:
    return str(sa.select(expr).compile(dialect=dialect, compile_kwargs={"literal_binds": True}))  # type: ignore[call-overload]


def test_each_dialect_spells_the_helpers_its_way() -> None:
    col = sa.column("v")
    assert "~" in compiled(full_match(col, "[0-9]+"), postgresql.dialect())
    assert "REGEXP_LIKE" in compiled(full_match(col, "[0-9]+"), mysql.dialect())
    assert "REGEXP" in compiled(full_match(col, "[0-9]+"), sqlite.dialect())
    with pytest.raises(NotImplementedError):
        compiled(full_match(col, "[0-9]+"), mssql.dialect())
    assert not supports_regex("mssql") and supports_regex("mysql")
    assert "char_length" in compiled(StrLen(col), postgresql.dialect())
    assert "LEN(" in compiled(StrLen(col), mssql.dialect())
    assert "length(" in compiled(StrLen(col), sqlite.dialect())
    assert "translate" in compiled(Shape(col), postgresql.dialect())
    assert "TRANSLATE" in compiled(Shape(col), mssql.dialect())
    assert "REGEXP_REPLACE" in compiled(Shape(col), mysql.dialect())
    assert "dq_shape" in compiled(Shape(col), sqlite.dialect())
    assert "BINARY" in compiled(Exact(col), mysql.dialect())
    assert "Latin1_General_BIN2" in compiled(Exact(col), mssql.dialect())
    assert "ltrim(rtrim" in compiled(blank(col), mssql.dialect()).lower()


def test_logical_types() -> None:
    assert logical_of(sa.Integer()) == "integer"
    assert logical_of(sa.Numeric(10, 0)) == "integer"
    assert logical_of(sa.Numeric(10, 2)) == "decimal"
    assert logical_of(sa.DateTime()) == "datetime"
    assert logical_of(sa.Date()) == "date"
    assert logical_of(sa.String()) == "text"
    assert logical_of(sa.Boolean()) == "boolean"
    assert logical_of(sa.LargeBinary()) == "other"
    assert duckdb_logical("DECIMAL(10,2)") == "decimal" and duckdb_logical("BIGINT") == "integer"
    assert (
        duckdb_logical("TIMESTAMP WITH TIME ZONE") == "datetime"
        and duckdb_logical("STRUCT(a INT)") == "other"
    )
    assert logical_of_value(True) == "boolean" and logical_of_value(dt.date.today()) == "date"


# Scoring and anomalies ---------------------------------------------------------------


def test_score_is_the_mean_of_dimension_means() -> None:
    s = score(
        [
            ScoredResult(CheckType.NOT_NULL, Dimension.COMPLETENESS, "fail", 100, 10),
            ScoredResult(CheckType.NOT_NULL, Dimension.COMPLETENESS, "pass", 100, 0),
            ScoredResult(CheckType.FRESHNESS, Dimension.FRESHNESS, "fail", 1, 1),
            ScoredResult(CheckType.PATTERN, Dimension.VALIDITY, "error", 0, 0),
            ScoredResult(CheckType.RANGE, Dimension.VALIDITY, "pass", 0, 0),
        ]
    )
    assert s.dimensions == {"completeness": 95.0, "freshness": 0.0}
    assert s.overall == 47.5
    assert score([]).overall is None


def test_anomalies_flag_drops_not_noise() -> None:
    normal = [1000, 1010, 990, 1005, 995, 1002, 998, 1001]
    assert not detect(1008, normal, label="Row count").anomalous
    drop = detect(120, normal, label="Row count")
    assert drop.anomalous and drop.direction == "down" and "88% below" in drop.explanation
    assert not detect(5, [1, 2, 3], label="x").anomalous  # too little history
    flat = [100.0] * 10
    assert not detect(101, flat, label="x").anomalous  # 1% change on a flat line
    assert detect(150, flat, label="x").anomalous
    assert detect(0, [0.0] * 8, label="x").anomalous is False


# Suggestions and profiling -----------------------------------------------------------


def test_suggestions_from_a_profile(tmp_path: Path) -> None:
    files = sources.write_files(tmp_path)
    with open_files([FileTable("customers", files["parquet"], "parquet", {})]) as c:
        from dataquality.engine.relation import reflect_table

        rel = reflect_table(c, "customers")
        prof = Profiler(c, "duckdb", rel, max_rows=150).run()
    assert prof.sampled and prof.rows_profiled == 150
    keys = {s.key: s for s in suggest(prof, dt.datetime(2026, 10, 30, tzinfo=dt.UTC))}
    assert "pattern:email" in keys and keys["pattern:email"].params == {"preset": "email"}
    assert "unique:customer_id" in keys and "range:price" not in keys  # negatives seen
    assert keys["row_count:*"].params == {"min": 101}
    # Suggestions keep the data as it is: the planted bad countries are in the list.
    assert len(keys["accepted_values:country"].params["values"]) == 9


def test_a_score_of_100_means_nothing_failed() -> None:
    s = score([ScoredResult(CheckType.NOT_NULL, Dimension.COMPLETENESS, "fail", 50_000, 2)])
    assert s.overall == 99.9 and s.dimensions == {"completeness": 99.9}
    perfect = score([ScoredResult(CheckType.NOT_NULL, Dimension.COMPLETENESS, "pass", 50_000, 0)])
    assert perfect.overall == 100.0
