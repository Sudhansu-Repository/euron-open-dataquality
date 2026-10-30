/**
 * Labels, tones and descriptions for check types, dimensions and outcomes, so the same
 * thing reads the same way on every screen.
 */
import type { CheckType, Dimension } from "./api/types";

export const CHECK_TYPES: Record<CheckType, { label: string; description: string; needsColumn: boolean }> = {
  not_null: { label: "Not null", description: "Every row has a value (blank text counts as missing).", needsColumn: true },
  unique: { label: "Unique", description: "No two rows share the value (or the combination of key columns).", needsColumn: true },
  duplicate_rows: { label: "No duplicate rows", description: "No row is an exact copy of another.", needsColumn: false },
  schema: { label: "Schema", description: "Expected columns exist with the expected types.", needsColumn: false },
  type: { label: "Type", description: "Text values parse as integers, decimals, dates, booleans or UUIDs.", needsColumn: true },
  range: { label: "Range", description: "Values sit between a minimum and a maximum.", needsColumn: true },
  pattern: { label: "Pattern", description: "Values match a format: email, phone, PIN code, or your own regex.", needsColumn: true },
  accepted_values: { label: "Allowed values", description: "Values come from a fixed list.", needsColumn: true },
  length: { label: "Length", description: "Text length stays between limits.", needsColumn: true },
  freshness: { label: "Freshness", description: "The newest timestamp is recent enough.", needsColumn: true },
  row_count: { label: "Row count", description: "The number of rows is within limits.", needsColumn: false },
  referential: { label: "Reference exists", description: "Every value exists in another dataset of the same source.", needsColumn: true },
  compare: { label: "Column comparison", description: "One column relates to another, like end date after start date.", needsColumn: true },
  format_consistency: { label: "Consistent format", description: "Values share one shape (like 999999 for a PIN code).", needsColumn: true },
  outliers: { label: "Outliers", description: "Values stay within a number of standard deviations of the mean.", needsColumn: true },
  custom_sql: { label: "Custom SQL", description: "A read-only SELECT that returns the failing rows.", needsColumn: false },
};

export const DIMENSIONS: Dimension[] = ["completeness", "validity", "consistency", "uniqueness", "freshness", "volume"];

export function dimensionLabel(d: string): string {
  return d.charAt(0).toUpperCase() + d.slice(1);
}

export function checkTypeLabel(t: string): string {
  return CHECK_TYPES[t as CheckType]?.label ?? t;
}

export type Tone = "success" | "warning" | "danger" | "neutral" | "info" | "primary";

/** A check result's tone: a failed warning check is amber, a failed error check red. */
export function resultTone(status: string, severity: string): Tone {
  if (status === "pass") return "success";
  if (status === "error") return "neutral";
  return severity === "warn" ? "warning" : "danger";
}

export function resultLabel(status: string, severity: string): string {
  if (status === "pass") return "Passed";
  if (status === "error") return "Could not run";
  return severity === "warn" ? "Warning" : "Failed";
}

export function scanStatusTone(status: string): Tone {
  return ({ succeeded: "success", failed: "danger", cancelled: "neutral", running: "info", queued: "neutral" } as const)[status as "succeeded"] ?? "neutral";
}

/** A score's tone: 98% and up is healthy, 90% and up needs attention, below is poor. */
export function scoreTone(score: number | null | undefined): Tone {
  if (score == null) return "neutral";
  if (score >= 98) return "success";
  if (score >= 90) return "warning";
  return "danger";
}

export function scoreLabel(score: number | null | undefined): string {
  if (score == null) return "Not scanned";
  if (score >= 98) return "Healthy";
  if (score >= 90) return "Needs attention";
  return "Poor";
}

export const DATASET_KINDS: Record<string, { label: string; description: string }> = {
  table: { label: "Table", description: "A table or view in a connected database" },
  query: { label: "Query", description: "A read-only SQL query on a connected database" },
  file: { label: "File", description: "An uploaded CSV, Excel, JSON or Parquet file" },
  rest: { label: "REST API", description: "Records fetched from a JSON endpoint" },
  push: { label: "Push", description: "Records your application sends through the API" },
};

export const CONNECTION_KINDS: Record<string, string> = {
  postgresql: "PostgreSQL",
  mysql: "MySQL / MariaDB",
  mssql: "SQL Server",
  sqlite: "SQLite",
};

export type RuleKind = "check_failed" | "score_below" | "anomaly" | "schema_change" | "scan_failed";

/** Alert rule kinds in plain words, in the order they are offered. */
export const RULE_KINDS: Record<RuleKind, { label: string; description: string }> = {
  check_failed: { label: "A check fails", description: "Any check at or above the chosen severity fails." },
  score_below: { label: "Score drops below", description: "A dataset's quality score falls under a threshold." },
  anomaly: { label: "Unusual change", description: "A metric moves far from its own history, like a row count that suddenly drops." },
  schema_change: { label: "Schema changes", description: "Columns are added, removed or change type." },
  scan_failed: { label: "A scan fails", description: "A scan cannot run, for example because the source is unreachable." },
};

export function ruleKindLabel(kind: string | null | undefined): string {
  return (kind && RULE_KINDS[kind as RuleKind]?.label) || kind || "Rule";
}

/** An incident's severity: error is red, warn amber, anything else informational. */
export function severityTone(severity: string): Tone {
  if (severity === "error") return "danger";
  if (severity === "warn" || severity === "warning") return "warning";
  return "info";
}

export function severityLabel(severity: string): string {
  if (severity === "error") return "Error";
  if (severity === "warn" || severity === "warning") return "Warning";
  return "Info";
}

export function incidentStatusTone(status: string): Tone {
  return ({ open: "danger", acknowledged: "warning", resolved: "success" } as const)[status as "open"] ?? "neutral";
}

export function incidentStatusLabel(status: string): string {
  return ({ open: "Open", acknowledged: "Acknowledged", resolved: "Resolved" } as const)[status as "open"] ?? status;
}

export function notificationTone(status: string): Tone {
  return ({ sent: "success", pending: "neutral", failed: "danger" } as const)[status as "sent"] ?? "neutral";
}

export const CHANNEL_KINDS: Record<string, string> = { email: "Email", slack: "Slack", webhook: "Webhook" };
