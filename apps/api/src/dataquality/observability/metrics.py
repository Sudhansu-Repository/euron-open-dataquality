"""Prometheus metrics. The API and the worker each expose their own registry."""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

SCANS = Counter("dataquality_scans_total", "Scans finished", ["status", "trigger"])
SCAN_SECONDS = Histogram(
    "dataquality_scan_seconds",
    "Scan duration from claim to result",
    ["source"],
    buckets=(0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300, 900, 1800),
)
ROWS_SCANNED = Counter(
    "dataquality_rows_scanned_total", "Rows covered by finished scans", ["source"]
)
CHECK_RESULTS = Counter("dataquality_check_results_total", "Check results", ["type", "status"])
QUEUE_DEPTH = Gauge("dataquality_queue_depth", "Scans waiting or running", ["status"])
NOTIFICATIONS = Counter(
    "dataquality_notifications_total", "Alert notifications", ["channel", "result"]
)
ANOMALIES = Counter("dataquality_anomalies_total", "Anomalies found", ["kind"])
DEPENDENCY_ERRORS = Counter(
    "dataquality_dependency_errors_total",
    "Failed calls to a dependency",
    ["dependency", "operation"],
)
