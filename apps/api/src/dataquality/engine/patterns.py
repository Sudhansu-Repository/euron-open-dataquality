"""Regular expressions every source understands, and value shapes.

Each database has its own regex engine (PostgreSQL ARE, MySQL ICU, DuckDB RE2, Python
``re`` for SQLite and SQL Server). Patterns here use only the subset they all agree on:
character classes with explicit ranges (``[0-9]``, not ``\\d``), quantifiers, alternation,
groups and anchors. User patterns are checked against the same rules, so a check means the
same thing on every backend.

A pattern always has to match the *whole* value: the engine wraps it as ``^(?:...)$``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Preset:
    label: str
    regex: str
    example: str


PRESETS: dict[str, Preset] = {
    "email": Preset(
        "Email address",
        r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+([.][A-Za-z0-9-]+)*[.][A-Za-z]{2,}",
        "asha@example.com",
    ),
    "phone_e164": Preset("Phone (E.164)", r"[+][1-9][0-9]{7,14}", "+14155550134"),
    "phone_in": Preset("Indian mobile number", r"([+]91[ -]?|0)?[6-9][0-9]{9}", "+91 9876543210"),
    "phone_us": Preset(
        "US phone number",
        r"([+]1[ -]?)?[(]?[2-9][0-9]{2}[)]?[ .-]?[0-9]{3}[ .-]?[0-9]{4}",
        "(415) 555-0134",
    ),
    "url": Preset("URL", r"https?://[A-Za-z0-9.-]+(:[0-9]+)?(/[^ ]*)?", "https://example.com/a"),
    "uuid": Preset(
        "UUID",
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
        "0f8fad5b-d9cb-469f-a165-70867728950e",
    ),
    "ipv4": Preset(
        "IPv4 address",
        r"((25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])[.]){3}(25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])",
        "10.0.0.1",
    ),
    "pin_in": Preset("Indian PIN code", r"[1-9][0-9]{5}", "560001"),
    "zip_us": Preset("US ZIP code", r"[0-9]{5}(-[0-9]{4})?", "94105"),
    "pan_in": Preset("Indian PAN", r"[A-Z]{5}[0-9]{4}[A-Z]", "ABCDE1234F"),
    "iso_date": Preset(
        "Date (YYYY-MM-DD)", r"[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])", "2026-10-30"
    ),
    "slug": Preset("Slug", r"[a-z0-9]+(-[a-z0-9]+)*", "summer-sale"),
}

_DATE = r"[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])"
TYPE_PATTERNS: dict[str, str] = {
    "integer": r"[+-]?[0-9]+",
    "decimal": r"[+-]?([0-9]+([.][0-9]*)?|[.][0-9]+)([eE][+-]?[0-9]+)?",
    "boolean": r"(true|false|TRUE|FALSE|True|False|t|f|T|F|yes|no|YES|NO|Yes|No|y|n|Y|N|0|1)",
    "date": _DATE,
    "datetime": _DATE + r"[T ]([01][0-9]|2[0-3]):[0-5][0-9](:[0-5][0-9]([.][0-9]{1,9})?)?"
    r"(Z|[+-][0-9]{2}:?[0-9]{2})?",
    "uuid": PRESETS["uuid"].regex,
}

# Escapes and constructs whose meaning differs between the engines (or that one lacks).
_NON_PORTABLE = [
    (re.compile(r"\\[dDwWsSbB]"), "use explicit classes such as [0-9] instead of \\d, \\w or \\s"),
    (re.compile(r"\(\?[=!<]"), "lookahead and lookbehind are not supported by every database"),
    (re.compile(r"\\[1-9]"), "back references are not supported by every database"),
    (re.compile(r"\(\?[a-zA-Z]"), "inline flags are not supported by every database"),
    (re.compile(r"\[\[:"), "POSIX classes such as [[:alpha:]] are not portable"),
]


def validate_regex(pattern: str) -> str:
    """A pattern every source evaluates the same way; raises ValueError otherwise."""
    if not pattern.strip():
        raise ValueError("the regex is empty")
    # The portability rules first: they also catch what Python only warns about ("[[:").
    for rule, message in _NON_PORTABLE:
        if rule.search(pattern):
            raise ValueError(message)
    try:
        re.compile(pattern)
    except re.error as exc:
        raise ValueError(f"invalid regex: {exc}") from exc
    return pattern


def anchored(pattern: str) -> str:
    return f"^(?:{pattern})$"


def shape(value: object) -> str:
    """A value's shape: letters become ``A`` or ``a``, digits ``9``, everything else stays.
    ``"KA-01 AB 1234"`` has the shape ``"AA-99 AA 9999"``. The SQL versions in
    ``engine.dialects`` compute exactly this, so shapes agree on every backend."""
    out = []
    for ch in str(value):
        if "a" <= ch <= "z":
            out.append("a")
        elif "A" <= ch <= "Z":
            out.append("A")
        elif "0" <= ch <= "9":
            out.append("9")
        else:
            out.append(ch)
    return "".join(out)
