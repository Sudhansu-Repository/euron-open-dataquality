"""``make bench``: profile and check a PostgreSQL table of 1,000,000 rows with 15 checks.

Builds ``bench_customers`` (once) in the demo source PostgreSQL, then runs the engine
exactly as a scan does, through the read-only login, and reports the time per phase and
the process's peak memory. It runs the same scan on 100,000 rows first: memory that does
not grow with ten times the rows shows the work stays in the database.

    make up && make bench          (or: uv run python -m tests.bench.bench_million)
"""

from __future__ import annotations

import os
import resource
import sys
import time

import psycopg

from dataquality.engine.profiler import Profiler
from dataquality.engine.relation import reflect_table
from dataquality.engine.runner import CheckRunner, RunOptions
from dataquality.engine.spec import CheckSpec
from dataquality.sources.sql import SqlTarget, open_sql
from tests.sources import PG_PORT, admin_password

DB = "dq_bench"
READER = ("dq_bench_reader", "Bench-Reader-123")

BUILD = """
CREATE TABLE IF NOT EXISTS bench_customers AS
SELECT g AS customer_id,
       CASE WHEN g % 997 = 0 THEN NULL ELSE 'customer' || g || '@example.com' END AS email,
       '+91' || (6000000000::bigint + (g::bigint * 7919) % 3999999999)::text AS phone,
       (ARRAY['IN','US','GB','AE','SG'])[1 + g % 5] AS country,
       round(((g * 37) % 5000)::numeric + 0.99, 2) AS price,
       DATE '2023-01-01' + (g % 1000) AS signup_date,
       TIMESTAMP '2026-10-01' + (g % 720) * interval '1 hour' AS last_seen_at,
       (560001 + g % 900)::text AS pin_code,
       (ARRAY['retail','wholesale','vip'])[1 + g % 3] AS segment
FROM generate_series(1, 1000000) g;
"""

CHECKS = [
    CheckSpec(key="email not null", type="not_null", column="email"),
    CheckSpec(key="id unique", type="unique", column="customer_id"),
    CheckSpec(key="no duplicate rows", type="duplicate_rows"),
    CheckSpec(key="email valid", type="pattern", column="email", params={"preset": "email"}),
    CheckSpec(key="phone e164", type="pattern", column="phone", params={"preset": "phone_e164"}),
    CheckSpec(key="price range", type="range", column="price", params={"min": 0, "max": 10000}),
    CheckSpec(
        key="country known",
        type="accepted_values",
        column="country",
        params={"values": ["IN", "US", "GB", "AE", "SG"]},
    ),
    CheckSpec(key="pin length", type="length", column="pin_code", params={"min": 6, "max": 6}),
    CheckSpec(key="pin format", type="format_consistency", column="pin_code"),
    CheckSpec(key="price outliers", type="outliers", column="price", params={"z": 4}),
    CheckSpec(
        key="seen after signup",
        type="compare",
        column="signup_date",
        params={"op": "<=", "other": "last_seen_at"},
    ),
    CheckSpec(key="fresh", type="freshness", column="last_seen_at", params={"max_age_hours": 8760}),
    CheckSpec(key="volume", type="row_count", params={"min": 1}),
    CheckSpec(
        key="segment known",
        type="accepted_values",
        column="segment",
        params={"values": ["retail", "wholesale", "vip"]},
    ),
    CheckSpec(
        key="schema",
        type="schema",
        params={
            "columns": [
                {"name": "customer_id", "type": "integer"},
                {"name": "email", "type": "text"},
            ]
        },
    ),
]


def build() -> None:
    admin = admin_password()
    with psycopg.connect(
        host="127.0.0.1",
        port=PG_PORT,
        user="warehouse_admin",
        password=admin,
        dbname="warehouse",
        autocommit=True,
    ) as c:
        if not c.execute("SELECT 1 FROM pg_database WHERE datname = %s", (DB,)).fetchone():
            c.execute(f"CREATE DATABASE {DB}")
        if not c.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (READER[0],)).fetchone():
            c.execute(f"CREATE ROLE {READER[0]} LOGIN PASSWORD '{READER[1]}'")
    with psycopg.connect(
        host="127.0.0.1",
        port=PG_PORT,
        user="warehouse_admin",
        password=admin,
        dbname=DB,
        autocommit=True,
    ) as c:
        started = time.perf_counter()
        c.execute(BUILD)
        c.execute(
            "CREATE OR REPLACE VIEW bench_100k AS SELECT * FROM bench_customers WHERE customer_id <= 100000"
        )
        c.execute(f"GRANT SELECT ON ALL TABLES IN SCHEMA public TO {READER[0]}")
        c.execute("ANALYZE bench_customers")
        print(f"table ready ({time.perf_counter() - started:.1f} s)")


def peak_mb() -> float:
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return rss / (1024 * 1024) if sys.platform == "darwin" else rss / 1024


def scan(table: str) -> dict[str, float]:
    target = SqlTarget(
        kind="postgresql",
        host="127.0.0.1",
        port=PG_PORT,
        database=DB,
        username=READER[0],
        password=READER[1],
        ssl_mode="disable",
    )
    with open_sql(target, 600) as c:
        rel = reflect_table(c, table)
        t0 = time.perf_counter()
        runner = CheckRunner(c, "postgresql", rel, RunOptions(sample_size=20))
        outcomes = runner.run(CHECKS)
        t1 = time.perf_counter()
        prof = Profiler(c, "postgresql", rel).run()
        t2 = time.perf_counter()
    errors = [o.key for o in outcomes if o.status == "error"]
    assert not errors, errors
    return {
        "rows": runner.row_count,
        "checks_s": t1 - t0,
        "profile_s": t2 - t1,
        "columns": len(prof.columns),
        "peak_mb": peak_mb(),
    }


def main() -> None:
    os.environ.setdefault("PGCONNECT_TIMEOUT", "10")
    build()
    for table in ("bench_100k", "bench_customers"):
        r = scan(table)
        print(
            f"{table:16} {int(r['rows']):>9,} rows  15 checks {r['checks_s']:6.2f} s  "
            f"profile of {int(r['columns'])} columns {r['profile_s']:6.2f} s  peak memory {r['peak_mb']:.0f} MB"
        )


if __name__ == "__main__":
    main()
