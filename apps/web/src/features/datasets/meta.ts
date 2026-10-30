/** Plain-words descriptions of a dataset: where it comes from and when it runs. */
import type { Dataset } from "@/lib/api/types";
import { DATASET_KINDS } from "@/lib/quality";

export function kindLabel(kind: string): string {
  return DATASET_KINDS[kind]?.label ?? kind;
}

/** The REST options stored on a dataset (url, records path), when it has them. */
export function restOptions(d: Pick<Dataset, "options">): { url: string; records_path: string } {
  const o = d.options ?? {};
  return {
    url: typeof o.url === "string" ? o.url : "",
    records_path: typeof o.records_path === "string" ? o.records_path : "",
  };
}

function hostOf(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}

/** Where the rows come from, in a few words. */
export function sourceLabel(d: Dataset): string {
  switch (d.kind) {
    case "table": {
      const t = [d.schema_name, d.table_name].filter(Boolean).join(".");
      return [d.connection_name, t].filter(Boolean).join(" · ") || "Database table";
    }
    case "query":
      return d.connection_name ? `${d.connection_name} · SQL query` : "SQL query";
    case "file":
      return "Uploaded file";
    case "rest": {
      const url = restOptions(d).url;
      return url ? hostOf(url) : "REST endpoint";
    }
    case "push":
      return "Pushed through the API";
    default:
      return d.connection_name ?? "";
  }
}

const DAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const pad = (n: number) => String(n).padStart(2, "0");
const isInt = (s: string, lo: number, hi: number) => /^\d+$/.test(s) && Number(s) >= lo && Number(s) <= hi;

/**
 * A cron expression in words when it is a simple one (hourly, daily, weekly, every N
 * minutes or hours); anything else comes back unchanged, so nothing is ever misstated.
 */
export function describeCron(expr: string | null | undefined): string {
  if (!expr) return "";
  const parts = expr.trim().split(/\s+/);
  if (parts.length !== 5) return expr;
  const [m, h, dom, mon, dow] = parts as [string, string, string, string, string];
  if (dom !== "*" || mon !== "*") return expr;
  const every = /^\*\/(\d+)$/;
  if (h === "*" && dow === "*") {
    if (m === "*") return "Every minute";
    const em = every.exec(m);
    if (em) return `Every ${em[1]} minutes`;
    if (isInt(m, 0, 59)) return m === "0" ? "Hourly" : `Hourly at :${pad(Number(m))}`;
    return expr;
  }
  if (!isInt(m, 0, 59)) return expr;
  const eh = every.exec(h);
  if (eh && dow === "*") return `Every ${eh[1]} hours`;
  if (!isInt(h, 0, 23)) return expr;
  const time = `${pad(Number(h))}:${pad(Number(m))}`;
  if (dow === "*") return `Daily at ${time}`;
  if (dow === "1-5") return `Weekdays at ${time}`;
  if (isInt(dow, 0, 7)) return `${DAYS[Number(dow) % 7]}s at ${time}`;
  return expr;
}

/** The schedule as one short phrase for lists, or "Manual" when there is none. */
export function scheduleText(d: Pick<Dataset, "schedule_cron" | "schedule_enabled" | "schedule_tz">): string {
  if (!d.schedule_cron || !d.schedule_enabled) return "Manual";
  return describeCron(d.schedule_cron);
}
