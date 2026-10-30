/**
 * The check editor's state and its translation to and from the API's CheckIn. Every check
 * type keeps its parameters in one flat record of strings and flags, so switching type in
 * the editor never loses what was typed for another.
 */
import type { CheckIn, CheckType, Dimension, Severity } from "@/lib/api/types";

export interface SchemaColumn {
  name: string;
  type: string;
  required: boolean;
}

export interface ParamState {
  empty_is_null: boolean;
  key_columns: string[];
  schema_columns: SchemaColumn[];
  allow_extra: boolean;
  value_type: string;
  min: string;
  max: string;
  inclusive: boolean;
  pattern_mode: "preset" | "regex";
  preset: string;
  regex: string;
  values: string[];
  case_sensitive: boolean;
  max_age_hours: string;
  ref_dataset: string;
  ref_column: string;
  op: string;
  other: string;
  min_share: string;
  z: string;
  sql: string;
}

export interface CheckForm {
  type: CheckType;
  name: string;
  column: string;
  severity: Severity;
  dimension: Dimension | "";
  filter_sql: string;
  tol_count: string;
  tol_percent: string;
  enabled: boolean;
  p: ParamState;
}

export const EMPTY_PARAMS: ParamState = {
  empty_is_null: true,
  key_columns: [],
  schema_columns: [],
  allow_extra: true,
  value_type: "integer",
  min: "",
  max: "",
  inclusive: true,
  pattern_mode: "preset",
  preset: "email",
  regex: "",
  values: [],
  case_sensitive: true,
  max_age_hours: "24",
  ref_dataset: "",
  ref_column: "",
  op: "<=",
  other: "",
  min_share: "95",
  z: "3",
  sql: "SELECT * FROM {table} WHERE ",
};

export function emptyForm(type: CheckType = "not_null"): CheckForm {
  return { type, name: "", column: "", severity: "error", dimension: "", filter_sql: "", tol_count: "", tol_percent: "", enabled: true, p: { ...EMPTY_PARAMS } };
}

const NUM = /^[+-]?(\d+(\.\d*)?|\.\d+)(e[+-]?\d+)?$/i;

/** A bound as the API wants it: a number when it looks like one, else the text (dates). */
function bound(s: string): number | string | null {
  const t = s.trim();
  if (!t) return null;
  return NUM.test(t) ? Number(t) : t;
}

function intOrNull(s: string): number | null | string {
  const t = s.trim();
  if (!t) return null;
  const n = Number(t);
  return Number.isInteger(n) && n >= 0 ? n : `"${t}" is not a whole number.`;
}

const str = (v: unknown, fallback = ""): string => (v === null || v === undefined ? fallback : String(v));

/** The params object for a type, or an error sentence for an obviously incomplete form. */
export function buildParams(type: CheckType, p: ParamState, columnType?: string): Record<string, unknown> | string {
  switch (type) {
    case "not_null":
      return { empty_is_null: p.empty_is_null };
    case "unique":
      return p.key_columns.length ? { columns: p.key_columns } : {};
    case "duplicate_rows":
      return p.key_columns.length ? { columns: p.key_columns } : {};
    case "schema": {
      const cols = p.schema_columns.filter((c) => c.name.trim());
      if (!cols.length) return "Add at least one expected column.";
      return { columns: cols.map((c) => ({ name: c.name.trim(), type: c.type, required: c.required })), allow_extra: p.allow_extra };
    }
    case "type":
      return { type: p.value_type };
    case "range": {
      const min = bound(p.min);
      const max = bound(p.max);
      if (min === null && max === null) return "Set a minimum, a maximum or both.";
      const out: Record<string, unknown> = { inclusive: p.inclusive };
      if (min !== null) out.min = min;
      if (max !== null) out.max = max;
      return out;
    }
    case "pattern":
      if (p.pattern_mode === "preset") return { preset: p.preset };
      if (!p.regex.trim()) return "Write the regular expression values must match.";
      return { regex: p.regex };
    case "accepted_values": {
      if (!p.values.length) return "Add at least one allowed value.";
      const numeric = columnType === "integer" || columnType === "decimal";
      const values = p.values.map((v) => (numeric && NUM.test(v) ? Number(v) : v));
      return { values, case_sensitive: p.case_sensitive };
    }
    case "length":
    case "row_count": {
      const min = intOrNull(p.min);
      const max = intOrNull(p.max);
      if (typeof min === "string") return min;
      if (typeof max === "string") return max;
      if (min === null && max === null) return "Set a minimum, a maximum or both.";
      const out: Record<string, unknown> = {};
      if (min !== null) out.min = min;
      if (max !== null) out.max = max;
      return out;
    }
    case "freshness": {
      const h = Number(p.max_age_hours);
      if (!p.max_age_hours.trim() || !Number.isFinite(h) || h <= 0) return "Set the maximum age in hours (more than 0).";
      return { max_age_hours: h };
    }
    case "referential":
      if (!p.ref_dataset.trim() || !p.ref_column.trim()) return "Pick the other dataset and the column to look values up in.";
      return { dataset: p.ref_dataset.trim(), column: p.ref_column.trim() };
    case "compare":
      if (!p.other.trim()) return "Pick the column to compare with.";
      return { op: p.op, other: p.other.trim() };
    case "format_consistency": {
      const share = Number(p.min_share);
      if (!Number.isFinite(share) || share <= 0 || share > 100) return "The share is a percent above 0 and at most 100.";
      return { min_share: share / 100 };
    }
    case "outliers": {
      const z = Number(p.z);
      if (!Number.isFinite(z) || z < 1 || z > 20) return "Standard deviations go from 1 to 20.";
      return { z };
    }
    case "custom_sql":
      if (!p.sql.trim()) return "Write the SELECT that returns the failing rows.";
      return { sql: p.sql };
  }
}

/** The CheckIn to send, or an error sentence. */
export function toCheckIn(f: CheckForm, needsColumn: boolean, columnType?: string): CheckIn | string {
  if (needsColumn && !f.column.trim()) return "Pick the column this check reads.";
  const params = buildParams(f.type, f.p, columnType);
  if (typeof params === "string") return params;
  const tolCount = intOrNull(f.tol_count);
  if (typeof tolCount === "string") return `Tolerance: ${tolCount}`;
  const tolPct = f.tol_percent.trim() ? Number(f.tol_percent) : null;
  if (tolPct !== null && (!Number.isFinite(tolPct) || tolPct < 0 || tolPct > 100)) return "The tolerance percent goes from 0 to 100.";
  return {
    type: f.type,
    name: f.name.trim() || null,
    column: needsColumn || f.column.trim() ? f.column.trim() || null : null,
    params,
    severity: f.severity,
    tolerance: { max_count: tolCount, max_percent: tolPct },
    dimension: f.dimension || null,
    filter_sql: f.filter_sql.trim() || null,
    enabled: f.enabled,
  };
}

/** An existing check (or a draft) back into the editor. */
export function fromCheck(c: {
  type: string;
  name?: string | null;
  column?: string | null;
  params?: Record<string, unknown> | null;
  severity?: string | null;
  dimension?: string | null;
  filter_sql?: string | null;
  tolerance?: Record<string, unknown> | null;
  enabled?: boolean | null;
}): CheckForm {
  const type = c.type as CheckType;
  const params = c.params ?? {};
  const p: ParamState = { ...EMPTY_PARAMS };
  const arr = (k: string) => (Array.isArray(params[k]) ? (params[k] as unknown[]) : []);
  switch (type) {
    case "not_null":
      p.empty_is_null = params.empty_is_null !== false;
      break;
    case "unique":
    case "duplicate_rows":
      p.key_columns = arr("columns").map((v) => str(v));
      break;
    case "schema":
      p.schema_columns = arr("columns").map((v) => {
        const o = (v ?? {}) as Record<string, unknown>;
        return { name: str(o.name), type: str(o.type, "any"), required: o.required !== false };
      });
      p.allow_extra = params.allow_extra !== false;
      break;
    case "type":
      p.value_type = str(params.type, "integer");
      break;
    case "range":
      p.min = str(params.min);
      p.max = str(params.max);
      p.inclusive = params.inclusive !== false;
      break;
    case "pattern":
      if (typeof params.regex === "string") {
        p.pattern_mode = "regex";
        p.regex = params.regex;
      } else {
        p.pattern_mode = "preset";
        p.preset = str(params.preset, "email");
      }
      break;
    case "accepted_values":
      p.values = arr("values").map((v) => str(v));
      p.case_sensitive = params.case_sensitive !== false;
      break;
    case "length":
    case "row_count":
      p.min = str(params.min);
      p.max = str(params.max);
      break;
    case "freshness":
      p.max_age_hours = str(params.max_age_hours, "24");
      break;
    case "referential":
      p.ref_dataset = str(params.dataset);
      p.ref_column = str(params.column);
      break;
    case "compare":
      p.op = str(params.op, "<=");
      p.other = str(params.other);
      break;
    case "format_consistency":
      p.min_share = typeof params.min_share === "number" ? String(Math.round(params.min_share * 10000) / 100) : "95";
      break;
    case "outliers":
      p.z = str(params.z, "3");
      break;
    case "custom_sql":
      p.sql = str(params.sql);
      break;
  }
  const tol = c.tolerance ?? {};
  return {
    type,
    name: c.name ?? "",
    column: c.column ?? "",
    severity: c.severity === "warn" ? "warn" : "error",
    dimension: (c.dimension as Dimension | null | undefined) ?? "",
    filter_sql: c.filter_sql ?? "",
    tol_count: str(tol.max_count),
    tol_percent: str(tol.max_percent),
    enabled: c.enabled !== false,
    p,
  };
}
