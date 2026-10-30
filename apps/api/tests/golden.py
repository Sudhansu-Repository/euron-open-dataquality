"""The golden dataset: customers and orders with defects planted at known counts.

Every number in ``EXPECTED`` follows from how the rows are built below, not from running
the engine, so the parity tests prove the engine finds exactly what was planted, on every
backend. Keep the two in step when changing either.
"""

from __future__ import annotations

import datetime as dt
import random
from typing import Any

BASE_ROWS = 200
# Recent, so "fresh logins" (a year) passes and "stale logins" (an hour) fails, whenever
# the suite runs.
LOGIN_BASE = (dt.datetime.now() - dt.timedelta(days=20)).replace(minute=30, second=0, microsecond=0)
COLUMNS = [
    ("customer_id", "integer"),
    ("email", "text"),
    ("phone", "text"),
    ("country", "text"),
    ("price", "decimal"),
    ("signup_date", "date"),
    ("last_login", "datetime"),
    ("zip_code", "text"),
    ("age_text", "text"),
    ("code", "text"),
]

BAD_EMAILS = ["bad", "a@b", "x@y.", "no-at.example.com"]
BAD_PHONES = ["12345", "+0123456789", "phone", "98765-43210", "+91 98765 43210", "++14155550134"]
BAD_COUNTRIES = ["XX", "India", "in", "us", "ZZ"]
BAD_ZIPS = ["5600 01", "ABC123", "56001", "560-001", "5600011"]
BAD_AGES = ["twenty", "3.5", "4O"]
LONG_CODES = ["C-123456", "C-1"]


def rows() -> list[dict[str, Any]]:
    rng = random.Random(20261030)
    out: list[dict[str, Any]] = []
    start = dt.date(2025, 1, 1)
    for i in range(1, BASE_ROWS + 1):
        signup = start + dt.timedelta(days=i)
        out.append(
            {
                "customer_id": i,
                "email": f"user{i}@example.com",
                "phone": f"+9198765{i:05d}",
                "country": ["IN", "US", "GB", "AE"][i % 4],
                "price": round(10 + rng.random() * 490, 2),
                "signup_date": signup,
                "last_login": LOGIN_BASE + dt.timedelta(hours=i),
                "zip_code": f"{560000 + i}",
                "age_text": str(18 + i % 60),
                "code": f"C-{1000 + i}",
            }
        )
    # Missing emails: 5 NULL, 3 blank (completeness 8, never "invalid").
    for i in range(0, 5):
        out[i]["email"] = None
    for i, blank in zip(range(5, 8), ["", " ", "   "], strict=True):
        out[i]["email"] = blank
    for i, bad in zip(range(10, 14), BAD_EMAILS, strict=True):
        out[i]["email"] = bad
    for i, bad in zip(range(20, 26), BAD_PHONES, strict=True):
        out[i]["phone"] = bad
    for i, bad in zip(range(30, 35), BAD_COUNTRIES, strict=True):
        out[i]["country"] = bad
    for i in range(40, 44):
        out[i]["price"] = -round(1 + i / 10, 2)  # 4 negative prices
    for i in (50, 51):
        out[i]["price"] = 99999.99  # 2 outliers
    for i in range(60, 63):
        out[i]["last_login"] = dt.datetime.combine(out[i]["signup_date"], dt.time()) - dt.timedelta(
            days=2
        )
    for i, bad in zip(range(70, 75), BAD_ZIPS, strict=True):
        out[i]["zip_code"] = bad
    for i, bad in zip(range(80, 83), BAD_AGES, strict=True):
        out[i]["age_text"] = bad
    out[83]["age_text"] = ""  # blank: missing, not an invalid integer
    for i, bad in zip(range(90, 92), LONG_CODES, strict=True):
        out[i]["code"] = bad
    # Duplicates of clean rows: ids 101 and 121 appear again as exact copies; id 151 appears
    # again with different values. unique(customer_id) fails 3, duplicate rows fails 2.
    out.append(dict(out[100]))
    out.append(dict(out[120]))
    copy = dict(out[150])
    copy["email"] = "other151@example.com"
    copy["code"] = "C-9099"
    out.append(copy)
    return out


TOTAL = BASE_ROWS + 3


def orders() -> list[dict[str, Any]]:
    """Orders referencing customers; 4 point at customers that do not exist."""
    out = [
        {"order_id": i, "customer_id": (i % BASE_ROWS) + 1, "amount": 10.0 + i}
        for i in range(1, 61)
    ]
    for n, missing in enumerate((900, 901, 902, 903)):
        out[n]["customer_id"] = missing
    return out


# The checks the parity tests create, and exactly what each must report.
CHECKS: list[dict[str, Any]] = [
    {"name": "email present", "type": "not_null", "column": "email"},
    {"name": "id unique", "type": "unique", "column": "customer_id"},
    {"name": "no duplicate rows", "type": "duplicate_rows"},
    {"name": "email valid", "type": "pattern", "column": "email", "params": {"preset": "email"}},
    {
        "name": "phone e164",
        "type": "pattern",
        "column": "phone",
        "params": {"preset": "phone_e164"},
    },
    {"name": "price not negative", "type": "range", "column": "price", "params": {"min": 0}},
    {
        "name": "known country",
        "type": "accepted_values",
        "column": "country",
        "params": {"values": ["IN", "US", "GB", "AE"]},
    },
    {"name": "code length", "type": "length", "column": "code", "params": {"min": 6, "max": 6}},
    {
        "name": "login after signup",
        "type": "compare",
        "column": "signup_date",
        "params": {"op": "<=", "other": "last_login"},
    },
    {
        "name": "zip format",
        "type": "format_consistency",
        "column": "zip_code",
        "params": {"min_share": 0.99},
    },
    {"name": "price outliers", "type": "outliers", "column": "price", "params": {"z": 3}},
    {"name": "age is integer", "type": "type", "column": "age_text", "params": {"type": "integer"}},
    {"name": "enough rows", "type": "row_count", "params": {"min": 1000}},
    {
        "name": "fresh logins",
        "type": "freshness",
        "column": "last_login",
        "params": {"max_age_hours": 24 * 365},
    },
    {
        "name": "stale logins",
        "type": "freshness",
        "column": "last_login",
        "params": {"max_age_hours": 1},
    },
    {
        "name": "has loyalty tier",
        "type": "schema",
        "params": {
            "columns": [
                {"name": "customer_id", "type": "integer"},
                {"name": "loyalty_tier", "type": "text"},
            ]
        },
    },
    {
        "name": "big prices",
        "type": "custom_sql",
        "params": {"sql": "SELECT * FROM {table} WHERE price > 1000"},
    },
]

# name: (status, evaluated, failed). None for evaluated: not compared (dataset-level).
EXPECTED: dict[str, tuple[str, int | None, int]] = {
    "email present": ("fail", TOTAL, 8),
    "id unique": ("fail", TOTAL, 3),
    "no duplicate rows": ("fail", TOTAL, 2),
    "email valid": ("fail", TOTAL - 8, 4),
    "phone e164": ("fail", TOTAL, 6),
    "price not negative": ("fail", TOTAL, 4),
    "known country": ("fail", TOTAL, 5),
    "code length": ("fail", TOTAL, 2),
    "login after signup": ("fail", TOTAL, 3),
    "zip format": ("fail", TOTAL, 5),
    "price outliers": ("fail", TOTAL, 2),
    "age is integer": ("fail", TOTAL - 1, 3),
    "enough rows": ("fail", 1, 1),
    "fresh logins": ("pass", 1, 0),
    "stale logins": ("fail", 1, 1),
    "has loyalty tier": ("fail", 2, 1),
    "big prices": ("fail", TOTAL, 2),
}

REFERENTIAL = {"name": "customer exists", "type": "referential", "column": "customer_id"}
REFERENTIAL_FAILED = 4
