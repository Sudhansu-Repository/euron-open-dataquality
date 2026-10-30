"""``dataquality seed-demo``: a living demo install, built through the real API.

1. Fills the demo sources: a "warehouse" PostgreSQL (customers, orders, products) and a
   "shop" MySQL (inventory, suppliers), with realistic defects, and gives DataQuality a
   read-only login to each.
2. Creates users, two projects, connections, datasets of every kind (tables, a query, an
   Excel upload, a Parquet upload, a REST feed, a push dataset), checks (accepted
   suggestions plus hand-written ones), alert channels and rules, and an API key.
3. Replays 30 days: each day it changes the source data the way real loads would (quality
   slowly improves, one day a broken load drops most orders, another brings a burst of
   missing emails), runs real scans through the API and the worker, and moves that day's
   scans, metrics and incidents to the day they stand for. Everything on the dashboards
   was computed by the engine; only the timestamps are shifted.

Idempotent: if the demo project exists it prints the logins and stops.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import io
import os
import random
import sys
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

API = os.environ.get("DQ_DEMO_API_URL", "http://api:8080")
MOCK = os.environ.get("DQ_DEMO_MOCK_URL", "http://mock-ai:4950")
PASSWORD = os.environ.get("DQ_DEMO_PASSWORD", "")
READER_PASSWORD = os.environ.get("DQ_DEMO_READER_PASSWORD", "")
PG_ADMIN = os.environ.get("DQ_DEMO_SOURCE_PG_ADMIN", "")
MYSQL_ADMIN = os.environ.get("DQ_DEMO_SOURCE_MYSQL_ADMIN", "")
DAYS = int(os.environ.get("DQ_DEMO_DAYS", "30"))
USERS = [
    ("admin@dataquality.demo", "Priya Raman", "admin"),
    ("maya@dataquality.demo", "Maya Fernandes", "user"),
    ("arjun@dataquality.demo", "Arjun Mehta", "user"),
]
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


def say(msg: str) -> None:
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()


# Sources ---------------------------------------------------------------------------------

WAREHOUSE_DDL = """
DROP TABLE IF EXISTS orders, customers, products CASCADE;
CREATE TABLE customers (
  customer_id INTEGER, full_name TEXT, email TEXT, phone TEXT, country CHAR(2), city TEXT,
  pin_code TEXT, signup_date DATE, last_seen_at TIMESTAMP, lifetime_value NUMERIC(12,2), segment TEXT
);
CREATE TABLE products (sku TEXT, title TEXT, category TEXT, price NUMERIC(10,2), active BOOLEAN);
CREATE TABLE orders (
  order_id BIGINT, customer_id INTEGER, sku TEXT, quantity INTEGER, unit_price NUMERIC(10,2),
  total NUMERIC(12,2), status TEXT, ordered_at TIMESTAMP, shipped_at TIMESTAMP
);
INSERT INTO products
SELECT 'SKU-' || lpad(g::text, 5, '0'),
       (ARRAY['Cotton kurta','Steel bottle','Desk lamp','Yoga mat','Spice box','Running shoes','Backpack','Tea sampler'])[1 + g % 8] || ' ' || g,
       (ARRAY['apparel','home','home','fitness','grocery','footwear','travel','grocery'])[1 + g % 8],
       round((199 + (g * 37) % 4800)::numeric, 2), g % 17 <> 0
FROM generate_series(1, 800) g;
INSERT INTO customers
SELECT g,
       (ARRAY['Aarav','Diya','Kabir','Ananya','Vihaan','Isha','Reyansh','Meera','Arjun','Saanvi','Rohan','Kavya'])[1 + g % 12]
         || ' ' || (ARRAY['Sharma','Iyer','Khan','Patel','Reddy','Das','Nair','Gupta','Singh','Bose'])[1 + (g / 12) % 10],
       'customer' || g || '@' || (ARRAY['gmail.com','outlook.com','yahoo.in','rediffmail.com'])[1 + g % 4],
       '+91' || (6000000000 + (g * 7919) % 3999999999)::text,
       (ARRAY['IN','IN','IN','IN','AE','US','GB','SG'])[1 + g % 8],
       (ARRAY['Bengaluru','Mumbai','Delhi','Pune','Chennai','Hyderabad','Kolkata','Dubai'])[1 + g % 8],
       (560001 + g % 900)::text,
       DATE '2023-01-01' + (g % 1000),
       TIMESTAMP '2026-01-01' + (g % 280) * interval '1 day',
       round((g * 13 % 90000 + 500)::numeric, 2),
       (ARRAY['retail','retail','wholesale','vip'])[1 + g % 4]
FROM generate_series(1, 50000) g;
-- Standing defects: a few invalid emails and phones, PIN codes typed with a space, duplicates.
UPDATE customers SET email = 'customer' || customer_id || '.gmail.com' WHERE customer_id % 409 = 7;
UPDATE customers SET phone = '0' || customer_id WHERE customer_id % 523 = 11;
UPDATE customers SET pin_code = left(pin_code, 3) || ' ' || right(pin_code, 3) WHERE customer_id % 997 = 5;
UPDATE customers SET country = 'XX' WHERE customer_id % 4999 = 1;
INSERT INTO customers SELECT * FROM customers WHERE customer_id % 1250 = 3;
INSERT INTO orders
SELECT g, 1 + (g * 31) % 50000, 'SKU-' || lpad((1 + g % 800)::text, 5, '0'), 1 + g % 4,
       round((199 + (g * 37) % 4800)::numeric, 2), round(((1 + g % 4) * (199 + (g * 37) % 4800))::numeric, 2),
       (ARRAY['placed','paid','shipped','delivered','delivered','delivered','returned'])[1 + g % 7],
       TIMESTAMP '2026-08-01' + (g % 88) * interval '1 day' + (g % 1440) * interval '1 minute',
       NULL
FROM generate_series(1, 120000) g;
UPDATE orders SET shipped_at = ordered_at + interval '2 days' WHERE status IN ('shipped', 'delivered');
UPDATE orders SET shipped_at = ordered_at - interval '1 day' WHERE order_id % 3001 = 17;
UPDATE orders SET total = -total WHERE order_id % 7919 = 3;
UPDATE orders SET customer_id = 90000 + order_id % 50 WHERE order_id % 6007 = 9;
"""

SHOP_DDL = [
    "DROP TABLE IF EXISTS inventory",
    "DROP TABLE IF EXISTS suppliers",
    """CREATE TABLE suppliers (supplier_id INT PRIMARY KEY, name VARCHAR(120), gstin VARCHAR(20),
       contact_email VARCHAR(160), city VARCHAR(60), rating DECIMAL(3,1))""",
    """CREATE TABLE inventory (sku VARCHAR(12), warehouse VARCHAR(20), supplier_id INT, on_hand INT,
       reorder_level INT, unit_cost DECIMAL(10,2), updated_at DATETIME)""",
]


def seed_warehouse() -> None:
    import psycopg

    u = urlparse(PG_ADMIN)
    with psycopg.connect(
        host=u.hostname,
        port=u.port or 5432,
        user=u.username,
        password=u.password,
        dbname=u.path.lstrip("/"),
        autocommit=True,
    ) as c:
        c.execute(WAREHOUSE_DDL)
        exists = c.execute("SELECT 1 FROM pg_roles WHERE rolname = 'dq_reader'").fetchone()
        verb = "ALTER" if exists else "CREATE"
        c.execute(f"{verb} ROLE dq_reader LOGIN PASSWORD '{READER_PASSWORD}'")
        c.execute("GRANT USAGE ON SCHEMA public TO dq_reader")
        c.execute("GRANT SELECT ON ALL TABLES IN SCHEMA public TO dq_reader")


def warehouse_day(day: int, total_days: int) -> None:
    """Reset the drifting defects, then apply this day's: missing emails fade out as the
    team fixes the signup form; one day a load brings a burst of them; one day the orders
    load breaks and most rows are missing."""
    import psycopg

    u = urlparse(PG_ADMIN)
    missing = max(0, (18 - day) * 40)
    with psycopg.connect(
        host=u.hostname,
        port=u.port or 5432,
        user=u.username,
        password=u.password,
        dbname=u.path.lstrip("/"),
        autocommit=True,
    ) as c:
        c.execute(
            "UPDATE customers SET email = 'customer' || customer_id || '@' || (ARRAY['gmail.com','outlook.com','yahoo.in','rediffmail.com'])[1 + customer_id % 4] WHERE email IS NULL OR email = ''"
        )
        if missing:
            c.execute(
                f"UPDATE customers SET email = NULL WHERE customer_id < {missing * 3} AND customer_id % 3 = 0"
            )
        if day == total_days - 4:
            c.execute("UPDATE customers SET email = '' WHERE customer_id > 46000")
        c.execute("CREATE TABLE IF NOT EXISTS orders_backup AS SELECT * FROM orders WITH NO DATA")
        if day == total_days - 6:
            c.execute("TRUNCATE orders_backup")
            c.execute("INSERT INTO orders_backup SELECT * FROM orders")
            c.execute("DELETE FROM orders WHERE order_id % 10 <> 0")
        elif day == total_days - 5:
            c.execute("TRUNCATE orders")
            c.execute("INSERT INTO orders SELECT * FROM orders_backup")
        c.execute(
            f"UPDATE orders SET ordered_at = ordered_at + interval '{1 if day else 0} day' WHERE order_id % 50 = {day % 50}"
        )


def seed_shop(now: dt.datetime) -> None:
    import pymysql

    u = urlparse(MYSQL_ADMIN)
    c = pymysql.connect(
        host=u.hostname,
        port=u.port or 3306,
        user=u.username,
        password=u.password or "",
        database=u.path.lstrip("/"),
        autocommit=True,
    )
    rng = random.Random(7)
    try:
        with c.cursor() as cur:
            for stmt in SHOP_DDL:
                cur.execute(stmt)
            suppliers = [
                (i, f"{rng.choice(['Shree', 'Vardhman', 'Coastal', 'Himalaya', 'Deccan', 'Ganga'])} {rng.choice(['Traders', 'Textiles', 'Exports', 'Foods', 'Industries'])} {i}",
                 f"{27 + i % 9:02d}AAACS{1000 + i:04d}Q1Z{i % 10}" if i % 23 else "PENDING",
                 f"orders@supplier{i}.in" if i % 31 else None, rng.choice(["Surat", "Ludhiana", "Kochi", "Indore", "Jaipur"]),
                 round(rng.uniform(2.5, 5.0), 1))
                for i in range(1, 121)
            ]  # fmt: skip
            cur.executemany("INSERT INTO suppliers VALUES (%s, %s, %s, %s, %s, %s)", suppliers)
            stale = now - dt.timedelta(hours=40)
            rows = []
            for i in range(1, 5001):
                on_hand = rng.randint(0, 400) if i % 97 else -rng.randint(1, 20)
                rows.append(
                    (f"SKU-{1 + i % 800:05d}", rng.choice(["BLR-1", "BOM-2", "DEL-1", "MAA-3"]), 1 + i % 120 if i % 211 else 999,
                     on_hand, rng.choice([20, 40, 60]), round(rng.uniform(80, 3000), 2), stale - dt.timedelta(minutes=i % 600))
                )  # fmt: skip
            cur.executemany("INSERT INTO inventory VALUES (%s, %s, %s, %s, %s, %s, %s)", rows)
            cur.execute(
                "CREATE USER IF NOT EXISTS 'dq_reader'@'%%' IDENTIFIED BY %s", (READER_PASSWORD,)
            )
            cur.execute("ALTER USER 'dq_reader'@'%%' IDENTIFIED BY %s", (READER_PASSWORD,))
            cur.execute(f"GRANT SELECT ON {u.path.lstrip('/')}.* TO 'dq_reader'@'%'")
    finally:
        c.close()


def employees_xlsx() -> bytes:
    import polars as pl

    rng = random.Random(11)
    first = [
        "Ananya",
        "Rahul",
        "Fatima",
        "Joseph",
        "Lakshmi",
        "Vikram",
        "Neha",
        "Siddharth",
        "Zoya",
        "Harpreet",
    ]
    last = [
        "Kulkarni",
        "Menon",
        "Sheikh",
        "Dsouza",
        "Pillai",
        "Chauhan",
        "Joshi",
        "Rao",
        "Ali",
        "Kaur",
    ]
    rows = []
    for i in range(1, 1201):
        rows.append({
            "employee_code": f"EUR{i:05d}" if i % 211 else f"EUR{i - 1:05d}",
            "full_name": f"{rng.choice(first)} {rng.choice(last)}",
            "work_email": f"emp{i}@kestrel.example" if i % 151 else None,
            "pan": f"{''.join(rng.choice('ABCDEFGHJKLMNPRSTUVWXYZ') for _ in range(5))}{rng.randint(1000, 9999)}{rng.choice('ABCDEFGHJKLMNPRSTUVWXYZ')}" if i % 97 else "NOT GIVEN",
            "department": rng.choice(["Engineering", "Sales", "Operations", "Finance", "People", "Support"]),
            "manager_code": f"EUR{rng.randint(1, 60):05d}" if i % 67 else None,
            "joined_on": dt.date(2018, 1, 1) + dt.timedelta(days=(i * 37) % 3000),
            "monthly_ctc": rng.randint(35, 400) * 1000 if i % 389 else -1,
        })  # fmt: skip
    buf = io.BytesIO()
    pl.DataFrame(rows).write_excel(buf, worksheet="employees")
    return buf.getvalue()


def events_parquet() -> bytes:
    import polars as pl

    rng = random.Random(5)
    base = dt.datetime(2026, 10, 29, 0, 0)
    rows = [
        {
            "event_id": f"ev_{i:07d}",
            "session_id": f"s_{i // 8:06d}",
            "event": rng.choice(["page_view", "page_view", "add_to_cart", "checkout", "purchase"]),
            "path": rng.choice(["/", "/kurtas", "/home/lamps", "/cart", "/checkout"]),
            "device": rng.choice(["android", "ios", "web", "web", "web"]),
            "duration_ms": rng.randint(20, 4000) if i % 509 else rng.randint(900_000, 2_000_000),
            "at": base + dt.timedelta(seconds=i * 3),
        }
        for i in range(30_000)
    ]
    buf = io.BytesIO()
    pl.DataFrame(rows).write_parquet(buf)
    return buf.getvalue()


# The API ---------------------------------------------------------------------------------


class Api:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self.c = client

    async def __call__(self, method: str, path: str, **kw: Any) -> Any:
        resp = await self.c.request(method, path, **kw)
        while resp.status_code == 429:  # the API's scan rate limit: wait as it says
            await asyncio.sleep(int(resp.headers.get("retry-after", "5")))
            resp = await self.c.request(method, path, **kw)
        if resp.status_code >= 400:
            raise RuntimeError(f"{method} {path}: {resp.status_code} {resp.text[:400]}")
        return (
            resp.json()
            if resp.content and "json" in resp.headers.get("content-type", "")
            else resp.content
        )


async def login(email: str) -> Api:
    c = httpx.AsyncClient(base_url=API, timeout=300, headers={"x-dq-csrf": "1"})
    resp = await c.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    if resp.status_code != 200:
        raise RuntimeError(f"cannot sign in as {email}: {resp.text[:200]}")
    c.headers["authorization"] = f"Bearer {resp.json()['session_token']}"
    return Api(c)


async def accounts() -> Api:
    anon = httpx.AsyncClient(base_url=API, timeout=60, headers={"x-dq-csrf": "1"})
    public = (await anon.get("/api/v1/org/public")).json()
    if public.get("needs_setup"):
        email, name, _ = USERS[0]
        resp = await anon.post(
            "/api/v1/auth/signup", json={"email": email, "name": name, "password": PASSWORD}
        )
        if resp.status_code != 201:
            raise RuntimeError(f"first sign-up failed: {resp.text[:300]}")
    await anon.aclose()
    admin = await login(USERS[0][0])
    existing = {u["email"] for u in await admin("GET", "/api/v1/users")}
    for email, name, role in USERS[1:]:
        if email not in existing:
            await admin(
                "POST",
                "/api/v1/users",
                json={"email": email, "name": name, "role": role, "password": PASSWORD},
            )
    return admin


async def accept_suggestions(api: Api, pid: str, did: str, skip: set[str] = frozenset()) -> None:  # type: ignore[assignment]
    found = await api("GET", f"/api/v1/projects/{pid}/datasets/{did}/suggestions")
    picked = [
        {k: s[k] for k in ("type", "column", "params", "severity")}
        for s in found
        if not s["exists"] and s["type"] not in skip
    ]
    if picked:
        await api(
            "POST",
            f"/api/v1/projects/{pid}/datasets/{did}/checks/bulk",
            json={"checks": picked, "origin": "suggested"},
        )


async def scan(api: Api, pid: str, did: str, profile: bool | None = None) -> dict[str, Any]:
    body = {"profile": profile} if profile is not None else None
    out: dict[str, Any] = await api(
        "POST", f"/api/v1/projects/{pid}/datasets/{did}/scans", params={"wait": 240}, json=body
    )
    return out


async def backdate(db: Any, scan_ids: list[str], when: dt.datetime) -> None:
    if not scan_ids:
        return
    async with db.begin() as conn:
        for sid in scan_ids:
            row = (
                await conn.execute(
                    text("SELECT started_at, finished_at FROM scans WHERE id = :i"), {"i": sid}
                )
            ).first()
            if row is None or row[0] is None:
                continue
            took = (row[1] - row[0]) if row[1] else dt.timedelta(seconds=2)
            await conn.execute(
                text(
                    "UPDATE scans SET created_at = :t, queued_at = :t, started_at = :t, finished_at = :f WHERE id = :i"
                ),
                {"t": when, "f": when + took, "i": sid},
            )
            await conn.execute(
                text("UPDATE metric_points SET at = :t WHERE scan_id = :i"), {"t": when, "i": sid}
            )
            await conn.execute(
                text("UPDATE anomalies SET created_at = :t WHERE scan_id = :i"),
                {"t": when, "i": sid},
            )
            await conn.execute(
                text("UPDATE scan_profiles SET created_at = :t WHERE scan_id = :i"),
                {"t": when, "i": sid},
            )
            await conn.execute(
                text(
                    "UPDATE incidents SET opened_at = :t, last_seen_at = :t WHERE first_scan_id = :i"
                ),
                {"t": when, "i": sid},
            )
            await conn.execute(
                text(
                    "UPDATE incidents SET last_seen_at = :t WHERE last_scan_id = :i AND first_scan_id <> :i"
                ),
                {"t": when, "i": sid},
            )
            await conn.execute(
                text(
                    "UPDATE incidents SET resolved_at = :t WHERE last_scan_id = :i AND status = 'resolved'"
                ),
                {"t": when, "i": sid},
            )
            await conn.execute(
                text(
                    "UPDATE notifications SET created_at = :t, sent_at = CASE WHEN sent_at IS NULL THEN NULL ELSE CAST(:t AS timestamptz) END WHERE incident_id IN (SELECT id FROM incidents WHERE first_scan_id = :i)"
                ),
                {"t": when, "i": sid},
            )


async def finish_history(db: Any) -> None:
    """Rebuild the daily rollups and each dataset's latest state from the backdated scans."""
    async with db.begin() as conn:
        await conn.execute(text("DELETE FROM daily_scores"))
        await conn.execute(
            text(
                """
                INSERT INTO daily_scores (dataset_id, day, project_id, scans, score_sum, last_score, failed_checks, rows_scanned)
                SELECT dataset_id, (started_at AT TIME ZONE 'UTC')::date, project_id, count(*), sum(score),
                       (array_agg(score ORDER BY started_at DESC))[1],
                       (array_agg(checks_failed + checks_warned ORDER BY started_at DESC))[1],
                       (array_agg(row_count ORDER BY started_at DESC))[1]
                FROM scans WHERE status = 'succeeded' AND score IS NOT NULL
                GROUP BY dataset_id, (started_at AT TIME ZONE 'UTC')::date, project_id
                """
            )
        )
        await conn.execute(
            text(
                """
                UPDATE datasets d SET last_scan_at = s.finished_at
                FROM scans s WHERE s.id = d.last_scan_id
                """
            )
        )


async def run() -> None:
    if not PASSWORD:
        raise SystemExit("DQ_DEMO_PASSWORD is not set (run make env, then make up)")
    admin = await accounts()
    projects = {p["slug"]: p for p in await admin("GET", "/api/v1/projects")}
    if "kestrel-retail" in projects:
        say("The demo is already seeded.")
        print_logins()
        return
    now = dt.datetime.now(dt.UTC)
    say("Filling the demo sources (warehouse PostgreSQL, shop MySQL)...")
    await asyncio.to_thread(seed_warehouse)
    await asyncio.to_thread(seed_shop, now)

    ai_url = os.environ.get("DQ_DEMO_AI_URL")
    if ai_url:  # the mock LLM in Compose: shows the optional assistant without any key
        await admin(
            "PATCH",
            "/api/v1/org/settings",
            json={"ai_enabled": True, "ai_base_url": ai_url, "ai_model": "demo-mock"},
        )
    say("Creating projects, connections, datasets and checks...")
    retail = await admin(
        "POST",
        "/api/v1/projects",
        json={
            "name": "Kestrel Retail",
            "slug": "kestrel-retail",
            "description": "Customers, orders and stock for the Kestrel online store.",
        },
    )
    people = await admin(
        "POST",
        "/api/v1/projects",
        json={
            "name": "People Ops",
            "slug": "people-ops",
            "description": "HR master data loaded from the payroll export.",
        },
    )
    r, h = retail["id"], people["id"]
    for email, role in (("maya@dataquality.demo", "editor"), ("arjun@dataquality.demo", "viewer")):
        await admin("POST", f"/api/v1/projects/{r}/members", json={"email": email, "role": role})
    await admin(
        "POST",
        f"/api/v1/projects/{h}/members",
        json={"email": "maya@dataquality.demo", "role": "owner"},
    )
    pg = urlparse(PG_ADMIN)
    my = urlparse(MYSQL_ADMIN)
    warehouse = await admin("POST", f"/api/v1/projects/{r}/connections", json={
        "name": "Warehouse (PostgreSQL)", "kind": "postgresql", "host": pg.hostname, "port": pg.port or 5432,
        "database": pg.path.lstrip("/"), "username": "dq_reader", "password": READER_PASSWORD, "ssl_mode": "disable",
    })  # fmt: skip
    shop = await admin("POST", f"/api/v1/projects/{r}/connections", json={
        "name": "Shop (MySQL)", "kind": "mysql", "host": my.hostname, "port": my.port or 3306,
        "database": my.path.lstrip("/"), "username": "dq_reader", "password": READER_PASSWORD,
    })  # fmt: skip
    for conn in (warehouse, shop):
        await admin("POST", f"/api/v1/projects/{r}/connections/{conn['id']}/test")
    daily = {"schedule_cron": "0 6 * * *", "schedule_tz": "Asia/Kolkata", "schedule_enabled": True}
    customers = await admin(
        "POST",
        f"/api/v1/projects/{r}/datasets",
        json={
            "name": "Customers",
            "kind": "table",
            "connection_id": warehouse["id"],
            "table_name": "customers",
            "description": "One row per customer, from the signup service.",
            "masked_columns": ["phone"],
            "tags": ["core", "pii"],
            **daily,
        },
    )
    orders = await admin(
        "POST",
        f"/api/v1/projects/{r}/datasets",
        json={
            "name": "Orders",
            "kind": "table",
            "connection_id": warehouse["id"],
            "table_name": "orders",
            "description": "Every order since August, loaded nightly.",
            "tags": ["core"],
            **daily,
        },
    )
    products = await admin(
        "POST",
        f"/api/v1/projects/{r}/datasets",
        json={
            "name": "Products",
            "kind": "table",
            "connection_id": warehouse["id"],
            "table_name": "products",
            "tags": ["catalog"],
        },
    )
    vip = await admin(
        "POST",
        f"/api/v1/projects/{r}/datasets",
        json={
            "name": "VIP customers",
            "kind": "query",
            "connection_id": warehouse["id"],
            "query_sql": "SELECT customer_id, email, lifetime_value, last_seen_at FROM customers WHERE segment = 'vip'",
            "tags": ["crm"],
        },
    )
    inventory = await admin(
        "POST",
        f"/api/v1/projects/{r}/datasets",
        json={
            "name": "Inventory",
            "kind": "table",
            "connection_id": shop["id"],
            "table_name": "inventory",
            "description": "Stock per SKU and warehouse, synced from the shop.",
            **daily,
        },
    )
    suppliers = await admin(
        "POST",
        f"/api/v1/projects/{r}/datasets",
        json={
            "name": "Suppliers",
            "kind": "table",
            "connection_id": shop["id"],
            "table_name": "suppliers",
        },
    )
    leads = await admin(
        "POST",
        f"/api/v1/projects/{r}/datasets",
        json={
            "name": "Partner leads",
            "kind": "rest",
            "rest": {"url": f"{MOCK}/feed/leads?bad=4&rows=120", "records_path": "data.items"},
            "rest_headers": {"authorization": "Bearer partner-demo-token"},
            "description": "Leads from the affiliate partner's API.",
        },
    )
    signups = await admin(
        "POST",
        f"/api/v1/projects/{r}/datasets",
        json={
            "name": "Signup events",
            "kind": "push",
            "description": "Batches pushed by the signup service after each import.",
        },
    )
    events = await admin(
        "POST",
        f"/api/v1/projects/{r}/datasets/upload",
        files={"file": ("web_events.parquet", events_parquet())},
        data={"name": "Web events"},
    )
    staff = await admin(
        "POST",
        f"/api/v1/projects/{h}/datasets/upload",
        files={"file": ("employees.xlsx", employees_xlsx())},
        data={"name": "Employees"},
    )

    ds_r = [customers, orders, products, vip, inventory, suppliers, leads, events]
    for d in ds_r:
        await scan(admin, r, d["id"])
    await scan(admin, h, staff["id"])
    for d in ds_r:
        await accept_suggestions(
            admin, r, d["id"], {"outliers", "length"} if d is not events else {"length"}
        )
    await accept_suggestions(admin, h, staff["id"], {"length"})
    custom = {
        customers["id"]: [
            {
                "name": "PIN code is 6 digits",
                "type": "pattern",
                "column": "pin_code",
                "params": {"preset": "pin_in"},
            },
            {
                "name": "Phone is +91 mobile",
                "type": "pattern",
                "column": "phone",
                "params": {"preset": "phone_in"},
                "severity": "warn",
            },
        ],
        orders["id"]: [
            {
                "name": "Shipped after ordered",
                "type": "compare",
                "column": "shipped_at",
                "params": {"op": ">=", "other": "ordered_at"},
            },
            {
                "name": "Order belongs to a customer",
                "type": "referential",
                "column": "customer_id",
                "params": {"dataset": "customers", "column": "customer_id"},
            },
            {
                "name": "Total is not negative",
                "type": "range",
                "column": "total",
                "params": {"min": 0},
            },
            {
                "name": "Orders are fresh",
                "type": "freshness",
                "column": "ordered_at",
                "params": {"max_age_hours": 24 * 90},
                "severity": "warn",
            },
        ],
        inventory["id"]: [
            {
                "name": "Stock never negative",
                "type": "range",
                "column": "on_hand",
                "params": {"min": 0},
            },
            {
                "name": "Synced in the last day",
                "type": "freshness",
                "column": "updated_at",
                "params": {"max_age_hours": 26},
            },
            {
                "name": "Supplier exists",
                "type": "referential",
                "column": "supplier_id",
                "params": {"dataset": "suppliers", "column": "supplier_id"},
            },
        ],
        suppliers["id"]: [
            {
                "name": "GSTIN format",
                "type": "pattern",
                "column": "gstin",
                "params": {"regex": "[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]Z[0-9A-Z]"},
            }
        ],
        signups["id"]: [
            {"name": "Email present", "type": "not_null", "column": "email"},
            {
                "name": "Email valid",
                "type": "pattern",
                "column": "email",
                "params": {"preset": "email"},
            },
            {
                "name": "Plan known",
                "type": "accepted_values",
                "column": "plan",
                "params": {"values": ["free", "pro", "team"]},
            },
        ],
        leads["id"]: [
            {
                "name": "Lead has an email",
                "type": "not_null",
                "column": "email",
                "tolerance": {"max_percent": 1},
            }
        ],
        events["id"]: [
            {
                "name": "Session length outliers",
                "type": "outliers",
                "column": "duration_ms",
                "params": {"z": 4},
                "severity": "warn",
            }
        ],
    }
    for did, checks in custom.items():
        await admin(
            "POST", f"/api/v1/projects/{r}/datasets/{did}/checks/bulk", json={"checks": checks}
        )
    await admin("POST", f"/api/v1/projects/{h}/datasets/{staff['id']}/checks/bulk", json={"checks": [
        {"name": "PAN format", "type": "pattern", "column": "pan", "params": {"preset": "pan_in"}},
        {"name": "Has a manager", "type": "not_null", "column": "manager_code", "severity": "warn", "tolerance": {"max_percent": 5}},
        {"name": "CTC is positive", "type": "range", "column": "monthly_ctc", "params": {"min": 1}},
    ]})  # fmt: skip

    email = await admin(
        "POST",
        f"/api/v1/projects/{r}/alert-channels",
        json={"name": "Data team", "kind": "email", "recipients": ["data-team@kestrel.example"]},
    )
    hook = await admin(
        "POST",
        f"/api/v1/projects/{r}/alert-channels",
        json={"name": "Ops webhook", "kind": "webhook", "url": f"{MOCK}/webhook"},
    )
    await admin(
        "POST",
        f"/api/v1/projects/{r}/alert-rules",
        json={
            "name": "Error checks failing",
            "kind": "check_failed",
            "channel_ids": [email["id"], hook["id"]],
        },
    )
    await admin(
        "POST",
        f"/api/v1/projects/{r}/alert-rules",
        json={"name": "Unusual changes", "kind": "anomaly", "channel_ids": [email["id"]]},
    )
    await admin(
        "POST",
        f"/api/v1/projects/{r}/alert-rules",
        json={"name": "Schema changed", "kind": "schema_change", "channel_ids": [hook["id"]]},
    )
    await admin(
        "POST",
        f"/api/v1/projects/{r}/alert-rules",
        json={"name": "Scan failed", "kind": "scan_failed", "channel_ids": [email["id"]]},
    )
    hr_mail = await admin(
        "POST",
        f"/api/v1/projects/{h}/alert-channels",
        json={"name": "People team", "kind": "email", "recipients": ["people@kestrel.example"]},
    )
    await admin(
        "POST",
        f"/api/v1/projects/{h}/alert-rules",
        json={
            "name": "Score under 95%",
            "kind": "score_below",
            "threshold": 95,
            "channel_ids": [hr_mail["id"]],
        },
    )
    await admin(
        "POST",
        f"/api/v1/projects/{r}/api-keys",
        json={"name": "GitHub Actions", "scopes": ["read", "scan"]},
    )
    await admin(
        "POST",
        f"/api/v1/projects/{r}/api-keys",
        json={"name": "Signup service", "scopes": ["push"]},
    )

    db = create_async_engine(os.environ["DATABASE_URL"])
    async with db.begin() as conn:  # the first scans (before checks) are setup, not history
        await conn.execute(text("DELETE FROM scans"))
        await conn.execute(text("DELETE FROM metric_points"))
    say(f"Replaying {DAYS} days of loads and scans (real scans, two or three minutes)...")
    rng = random.Random(3)
    daily_sets = [(r, d) for d in (customers, orders, inventory, vip, products, suppliers)]
    for day in range(DAYS):
        when = (
            (now - dt.timedelta(days=DAYS - 1 - day))
            .astimezone(IST)
            .replace(hour=6, minute=rng.randint(0, 20), second=0, microsecond=0)
        )
        await asyncio.to_thread(warehouse_day, day, DAYS)
        # Profiles are worth keeping for the latest day only; the scans of a day run in
        # parallel (the worker runs several, two at a time per database connection).
        last = day == DAYS - 1
        todo = list(daily_sets)
        if day % 3 == 0 or last:
            todo += [(r, leads), (h, staff), (r, events)]
        done = await asyncio.gather(*(scan(admin, pid, d["id"], profile=last) for pid, d in todo))
        ids = [s["id"] for s in done]
        batch = [
            {"signup_id": f"su_{day:02d}{i:04d}", "email": None if rng.random() < (0.02 if day < DAYS - 2 else 0.12) else (f"new{day}_{i}@gmail.com" if rng.random() > 0.01 else "not-an-email"),
             "plan": rng.choice(["free", "free", "pro", "team"]) if rng.random() > 0.005 else "trial", "source": rng.choice(["web", "android", "ios"])}
            for i in range(rng.randint(700, 1100))
        ]  # fmt: skip
        pushed = await admin(
            "POST",
            f"/api/v1/projects/{r}/datasets/{signups['id']}/records",
            params={"wait": 120},
            json={"records": batch},
        )
        ids.append(pushed["scan"]["id"])
        await backdate(db, ids, when.astimezone(dt.UTC))
        say(f"  day {day + 1}/{DAYS}: {len(ids)} scans")
    await finish_history(db)
    await db.dispose()
    print_logins()


def print_logins() -> None:
    say("")
    say("Demo logins (password: the DQ_DEMO_PASSWORD in deploy/compose/.env):")
    for email, name, role in USERS:
        what = (
            "instance admin"
            if role == "admin"
            else (
                "editor in Kestrel Retail, owner of People Ops"
                if email.startswith("maya")
                else "viewer in Kestrel Retail"
            )
        )
        say(f"  {email:28} {name:16} {what}")
