"""Downloadable reports: a scan as CSV or PDF, a dataset's history as CSV, a project
summary as PDF. Every number comes from the same rows the API returns.

CSV cells that a spreadsheet would run as a formula (starting with = + - @, tab or CR) are
prefixed with a quote, so a value planted in the data cannot execute when the report is
opened in Excel.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Sequence
from datetime import datetime
from typing import Any

import orjson
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from dataquality.datasets.models import Dataset
from dataquality.scans.models import CheckResult, Scan

_FORMULA = ("=", "+", "-", "@", "\t", "\r")
INK = colors.HexColor("#0F172A")
MUTED = colors.HexColor("#64748B")
ACCENT = colors.HexColor("#1D64C8")
FAIL = colors.HexColor("#DC2626")
WARN = colors.HexColor("#D97706")
OK = colors.HexColor("#059669")
FILL = colors.HexColor("#F1F5F9")


def safe_cell(value: object) -> str:
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(_FORMULA) else text


def _csv(rows: list[list[object]]) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf)
    for row in rows:
        writer.writerow([safe_cell(v) for v in row])
    return ("﻿" + buf.getvalue()).encode()  # BOM: Excel opens UTF-8 correctly


def scan_csv(dataset: Dataset, scan: Scan, results: Sequence[CheckResult]) -> bytes:
    rows: list[list[object]] = [
        [
            "dataset",
            "scan_id",
            "finished_at",
            "check",
            "type",
            "column",
            "dimension",
            "severity",
            "status",
            "evaluated",
            "failed",
            "failed_pct",
            "message",
            "sample",
        ],
    ]
    for r in results:
        rows.append(
            [
                dataset.name,
                str(scan.id),
                scan.finished_at.isoformat() if scan.finished_at else "",
                r.check_name,
                r.type,
                r.column or "",
                r.dimension,
                r.severity,
                r.status,
                r.evaluated,
                r.failed,
                f"{r.failed_pct:.4f}",
                r.error or r.message,
                orjson.dumps(r.sample[:5]).decode() if r.sample else "",
            ]
        )
    return _csv(rows)


def history_csv(dataset: Dataset, scans: Sequence[Scan]) -> bytes:
    rows: list[list[object]] = [
        [
            "dataset",
            "scan_id",
            "started_at",
            "status",
            "trigger",
            "rows",
            "score",
            "completeness",
            "validity",
            "consistency",
            "uniqueness",
            "freshness",
            "volume",
            "checks",
            "passed",
            "failed",
            "warned",
            "errors",
        ],
    ]
    for s in scans:
        d = s.dimension_scores or {}
        rows.append(
            [
                dataset.name,
                str(s.id),
                s.started_at.isoformat() if s.started_at else "",
                s.status,
                s.trigger,
                s.row_count,
                s.score,
                d.get("completeness"),
                d.get("validity"),
                d.get("consistency"),
                d.get("uniqueness"),
                d.get("freshness"),
                d.get("volume"),
                s.checks_total,
                s.checks_passed,
                s.checks_failed,
                s.checks_warned,
                s.checks_errored,
            ]
        )
    return _csv(rows)


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "t", parent=base["Title"], fontSize=18, textColor=INK, alignment=0, spaceAfter=2
        ),
        "sub": ParagraphStyle(
            "s", parent=base["Normal"], fontSize=9, textColor=MUTED, spaceAfter=10
        ),
        "h": ParagraphStyle(
            "h", parent=base["Heading3"], fontSize=11, textColor=INK, spaceBefore=10, spaceAfter=6
        ),
        "cell": ParagraphStyle("c", parent=base["Normal"], fontSize=8, leading=10, textColor=INK),
        "small": ParagraphStyle(
            "m", parent=base["Normal"], fontSize=7.5, leading=9, textColor=MUTED
        ),
    }


def _esc(text: object) -> str:
    return (
        str(text if text is not None else "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _table(data: list[list[Any]], widths: list[float]) -> Table:
    t = Table(data, colWidths=widths, repeatRows=1)
    style: list[Any] = [
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8),
        ("TEXTCOLOR", (0, 0), (-1, 0), MUTED),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.HexColor("#E2E8F0")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    for i in range(1, len(data)):
        if i % 2 == 0:
            style.append(("BACKGROUND", (0, i), (-1, i), FILL))
    t.setStyle(TableStyle(style))
    return t


def _status(status: str, severity: str, s: dict[str, ParagraphStyle]) -> Paragraph:
    color = OK if status == "pass" else (WARN if status == "error" or severity == "warn" else FAIL)
    label = {
        "pass": "Pass",
        "fail": "Fail" if severity == "error" else "Warn",
        "error": "Error",
    }.get(status, status)
    return Paragraph(f'<font color="{color.hexval()}"><b>{label}</b></font>', s["cell"])


def scan_pdf(
    project_name: str, dataset: Dataset, scan: Scan, results: Sequence[CheckResult]
) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        title=f"Quality report: {dataset.name}",
        author="Euron Open DataQuality",
    )
    s = _styles()
    when = scan.finished_at or scan.created_at
    story: list[Any] = [
        Paragraph(f"Data quality report: {_esc(dataset.name)}", s["title"]),
        Paragraph(
            f"{_esc(project_name)} &middot; scan {str(scan.id)[:8]} &middot; "
            f"{when:%d %b %Y %H:%M} UTC &middot; "
            f"{scan.row_count or 0:,} rows &middot; {scan.trigger}",
            s["sub"],
        ),
    ]
    score = "n/a" if scan.score is None else f"{scan.score:.1f}%"
    summary: list[list[Any]] = [
        ["Quality score", "Checks", "Passed", "Failed", "Warnings", "Errors"],
        [
            score,
            scan.checks_total,
            scan.checks_passed,
            scan.checks_failed,
            scan.checks_warned,
            scan.checks_errored,
        ],
    ]
    t = Table(summary, colWidths=[30 * mm] * 6)
    t.setStyle(
        TableStyle(
            [
                ("FONT", (0, 0), (-1, 0), "Helvetica", 8),
                ("TEXTCOLOR", (0, 0), (-1, 0), MUTED),
                ("FONT", (0, 1), (-1, 1), "Helvetica-Bold", 16),
                ("TEXTCOLOR", (0, 1), (0, 1), ACCENT),
                ("BACKGROUND", (0, 0), (-1, -1), FILL),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story += [t, Paragraph("Score by dimension", s["h"])]
    dims = scan.dimension_scores or {}
    if dims:
        story.append(
            _table(
                [["Dimension", "Score"]] + [[k.title(), f"{v:.1f}%"] for k, v in dims.items()],
                [60 * mm, 30 * mm],
            )
        )
    else:
        story.append(Paragraph("No checks ran, so there is no score yet.", s["small"]))
    story.append(Paragraph("Check results", s["h"]))
    data: list[list[Any]] = [["Status", "Check", "Column", "Failed", "Of", "Details"]]
    for r in results:
        data.append(
            [
                _status(r.status, r.severity, s),
                Paragraph(_esc(r.check_name), s["cell"]),
                Paragraph(_esc(r.column or ""), s["cell"]),
                f"{r.failed:,}",
                f"{r.evaluated:,}",
                Paragraph(_esc(r.error or r.message), s["cell"]),
            ]
        )
    story.append(_table(data, [14 * mm, 42 * mm, 26 * mm, 18 * mm, 18 * mm, 60 * mm]))
    failing = [r for r in results if r.status == "fail" and r.sample]
    if failing:
        story.append(Paragraph("Failing rows (samples)", s["h"]))
        for r in failing[:15]:
            story.append(Paragraph(f"<b>{_esc(r.check_name)}</b>", s["cell"]))
            for row in r.sample[:5]:
                text = ", ".join(f"{k}={v}" for k, v in list(row.items())[:8])
                story.append(Paragraph(_esc(text[:300]), s["small"]))
            story.append(Spacer(1, 4))
    story.append(Spacer(1, 8))
    story.append(
        Paragraph(
            "Generated by Euron Open DataQuality. Scores are the mean pass rate per dimension.",
            s["small"],
        )
    )
    doc.build(story)
    return buf.getvalue()


def project_pdf(project_name: str, datasets: Sequence[Dataset], generated: datetime) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        title=f"Quality summary: {project_name}",
        author="Euron Open DataQuality",
    )
    s = _styles()
    scored = [d.last_score for d in datasets if d.last_score is not None]
    overall = f"{sum(scored) / len(scored):.1f}%" if scored else "n/a"
    story: list[Any] = [
        Paragraph(f"Data quality summary: {_esc(project_name)}", s["title"]),
        Paragraph(
            f"{generated:%d %b %Y %H:%M} UTC &middot; {len(datasets)} datasets &middot; "
            f"overall score {overall}",
            s["sub"],
        ),
    ]
    data: list[list[Any]] = [["Dataset", "Kind", "Score", "Rows", "Failing checks", "Last scan"]]
    for d in sorted(datasets, key=lambda x: (x.last_score is None, x.last_score or 0)):
        data.append(
            [
                Paragraph(_esc(d.name), s["cell"]),
                d.kind,
                "n/a" if d.last_score is None else f"{d.last_score:.1f}%",
                f"{d.last_row_count:,}" if d.last_row_count is not None else "",
                d.last_failed_checks or 0,
                d.last_scan_at.strftime("%d %b %H:%M") if d.last_scan_at else "never",
            ]
        )
    story.append(_table(data, [56 * mm, 18 * mm, 18 * mm, 26 * mm, 26 * mm, 30 * mm]))
    doc.build(story)
    return buf.getvalue()
