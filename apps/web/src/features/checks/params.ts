/**
 * Check parameters in words ("between 0 and 100", "matches email"), and the pattern
 * presets the API knows. Pure functions so they can be unit tested.
 */

export const PATTERN_PRESETS: Record<string, { label: string; example: string }> = {
  email: { label: "Email address", example: "asha@example.com" },
  phone_e164: { label: "Phone (E.164)", example: "+14155550134" },
  phone_in: { label: "Indian mobile number", example: "+91 9876543210" },
  phone_us: { label: "US phone number", example: "(415) 555-0134" },
  url: { label: "URL", example: "https://example.com/a" },
  uuid: { label: "UUID", example: "0f8fad5b-d9cb-469f-a165-70867728950e" },
  ipv4: { label: "IPv4 address", example: "10.0.0.1" },
  pin_in: { label: "Indian PIN code", example: "560001" },
  zip_us: { label: "US ZIP code", example: "94105" },
  pan_in: { label: "Indian PAN", example: "ABCDE1234F" },
  iso_date: { label: "Date (YYYY-MM-DD)", example: "2026-10-30" },
  slug: { label: "Slug", example: "summer-sale" },
};

export const TYPE_CHOICES = ["integer", "decimal", "boolean", "date", "datetime", "uuid"] as const;
export const SCHEMA_TYPES = ["any", "integer", "decimal", "boolean", "date", "datetime", "text", "uuid"] as const;
export const COMPARE_OPS = ["<", "<=", "=", "!=", ">=", ">"] as const;

const OP_WORDS: Record<string, string> = { "<": "less than", "<=": "at most", "=": "equal to", "!=": "different from", ">=": "at least", ">": "greater than" };

const fmt = (v: unknown): string => {
  if (typeof v === "number") return v.toLocaleString("en-US", { maximumFractionDigits: 6 });
  if (typeof v === "string") return v;
  return JSON.stringify(v);
};

function bounds(min: unknown, max: unknown, unit = ""): string {
  const u = unit ? ` ${unit}` : "";
  if (min != null && max != null && fmt(min) === fmt(max)) return `exactly ${fmt(min)}${u}`;
  if (min != null && max != null) return `between ${fmt(min)} and ${fmt(max)}${u}`;
  if (min != null) return `at least ${fmt(min)}${u}`;
  if (max != null) return `at most ${fmt(max)}${u}`;
  return "";
}

function list(values: unknown[], max = 4): string {
  const shown = values.slice(0, max).map(fmt).join(", ");
  return values.length > max ? `${shown} and ${values.length - max} more` : shown;
}

/** The key parameters of a check in a few words, or "" when there is nothing to say. */
export function describeParams(type: string, params: Record<string, unknown> | null | undefined): string {
  const p = params ?? {};
  const arr = (k: string) => (Array.isArray(p[k]) ? (p[k] as unknown[]) : []);
  switch (type) {
    case "not_null":
      return p.empty_is_null === false ? "blanks allowed" : "";
    case "unique": {
      const cols = arr("columns");
      return cols.length ? `with ${list(cols)}` : "";
    }
    case "duplicate_rows": {
      const cols = arr("columns");
      return cols.length ? `on ${list(cols)}` : "all columns";
    }
    case "schema": {
      const cols = arr("columns");
      return `${cols.length} column${cols.length === 1 ? "" : "s"}${p.allow_extra === false ? ", no extras" : ""}`;
    }
    case "type":
      return p.type ? `is ${fmt(p.type)}` : "";
    case "range": {
      const b = bounds(p.min, p.max);
      return p.inclusive === false && b ? `${b} (exclusive)` : b;
    }
    case "pattern":
      if (typeof p.preset === "string") return `matches ${PATTERN_PRESETS[p.preset]?.label ?? p.preset}`;
      return typeof p.regex === "string" ? `matches /${p.regex}/` : "";
    case "accepted_values": {
      const vals = arr("values");
      return vals.length ? `one of ${list(vals)}${p.case_sensitive === false ? " (any case)" : ""}` : "";
    }
    case "length":
      return bounds(p.min, p.max, "characters");
    case "freshness":
      return typeof p.max_age_hours === "number" ? `newer than ${hoursPhrase(p.max_age_hours)}` : "";
    case "row_count":
      return bounds(p.min, p.max, "rows");
    case "referential":
      return p.dataset ? `in ${fmt(p.dataset)}.${fmt(p.column)}` : "";
    case "compare":
      return p.op && p.other ? `${OP_WORDS[String(p.op)] ?? String(p.op)} ${fmt(p.other)}` : "";
    case "format_consistency":
      return typeof p.min_share === "number" ? `${Math.round(p.min_share * 1000) / 10}% share one shape` : "";
    case "outliers":
      return typeof p.z === "number" ? `within ${fmt(p.z)} standard deviations` : "";
    case "custom_sql":
      return "custom query";
    default:
      return "";
  }
}

export function hoursPhrase(h: number): string {
  if (h % 24 === 0 && h >= 24) return `${h / 24} day${h === 24 ? "" : "s"}`;
  return `${fmt(h)} hour${h === 1 ? "" : "s"}`;
}

/** A tolerance in words: "up to 10 rows and 0.5%" (both must hold), or "" for none. */
export function describeTolerance(t: Record<string, unknown> | null | undefined): string {
  const c = t?.max_count;
  const p = t?.max_percent;
  const parts: string[] = [];
  if (typeof c === "number") parts.push(`${fmt(c)} row${c === 1 ? "" : "s"}`);
  if (typeof p === "number") parts.push(`${fmt(p)}%`);
  return parts.length ? `up to ${parts.join(" and ")}` : "";
}
