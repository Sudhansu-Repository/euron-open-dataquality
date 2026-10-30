"use client";

import { ChevronRightIcon } from "lucide-react";
import * as React from "react";

import { ResultChip } from "@/components/quality";
import type { CheckResult } from "@/lib/api/types";
import { cn } from "@/lib/cn";
import { formatDateTime, formatNumber, formatPercent, plural } from "@/lib/format";
import { checkTypeLabel, dimensionLabel } from "@/lib/quality";

import { describeParams } from "../../checks/params";

/** A cell value as text: null stays visible as "null", objects as JSON. */
export function cellText(v: unknown): string {
  if (v === null || v === undefined) return "null";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

/** A compact table for sample rows, scrolling inside its own container. */
export function RowsTable({ rows, columns, order, maxHeight = 320 }: { rows: Record<string, unknown>[]; columns?: string[]; order?: string[]; maxHeight?: number }) {
  const cols = React.useMemo(() => {
    if (columns?.length) return columns;
    const seen = new Set<string>();
    for (const r of rows) for (const k of Object.keys(r)) seen.add(k);
    // Dataset column order when known; "copies" (from duplicate checks) reads best first.
    const rank = new Map((order ?? []).map((c, i) => [c, i]));
    return [...seen].sort((a, b) => {
      if (a === "copies" || b === "copies") return a === "copies" ? -1 : 1;
      return (rank.get(a) ?? 1e6) - (rank.get(b) ?? 1e6);
    });
  }, [rows, columns, order]);
  return (
    <div className="overflow-auto rounded-lg bg-muted/50" style={{ maxHeight }}>
      <table className="w-max min-w-full text-[12px]">
        <thead className="sticky top-0 z-[1] bg-muted">
          <tr>
            {cols.map((c) => (
              <th key={c} scope="col" className="px-3 py-2 text-left font-mono text-[11px] font-medium whitespace-nowrap text-muted-foreground">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-t border-hairline">
              {cols.map((c) => {
                const v = r[c];
                const t = cellText(v);
                return (
                  <td
                    key={c}
                    className={cn(
                      "max-w-[280px] truncate px-3 py-1.5 font-mono whitespace-nowrap",
                      v == null ? "text-faint italic" : t === "[masked]" ? "text-subtle" : "text-foreground",
                    )}
                    title={t}
                  >
                    {t}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0 rounded-lg bg-muted/60 px-3 py-2">
      <div className="text-[11px] text-subtle">{label}</div>
      <div className="mt-0.5 truncate text-[13px] font-medium text-foreground tabular">{children}</div>
    </div>
  );
}

const num = (v: unknown) => (typeof v === "number" ? v.toLocaleString("en-US", { maximumFractionDigits: 4 }) : cellText(v));

function hoursText(h: number): string {
  if (h < 1) return `${Math.round(h * 60)} minutes`;
  if (h < 48) return `${h.toFixed(1).replace(/\.0$/, "")} hours`;
  return `${(h / 24).toFixed(1).replace(/\.0$/, "")} days`;
}

/** What the check measured, laid out per check type. */
function Observed({ r }: { r: CheckResult }) {
  const o = r.observed ?? {};
  const facts: React.ReactNode[] = [];
  if (r.type === "freshness") {
    facts.push(<Fact key="n" label="Newest value">{o.newest ? formatDateTime(String(o.newest)) : "None"}</Fact>);
    if (typeof o.age_hours === "number") facts.push(<Fact key="a" label="Age">{hoursText(o.age_hours)}</Fact>);
    if (typeof o.max_age_hours === "number") facts.push(<Fact key="m" label="Allowed age">{hoursText(o.max_age_hours)}</Fact>);
  } else if (r.type === "outliers") {
    if (o.low != null && o.high != null) facts.push(<Fact key="b" label="Accepted range">{`${num(o.low)} to ${num(o.high)}`}</Fact>);
    if (o.mean != null) facts.push(<Fact key="m" label="Mean">{num(o.mean)}</Fact>);
    if (o.stddev != null) facts.push(<Fact key="s" label="Standard deviation">{num(o.stddev)}</Fact>);
    if (o.z != null) facts.push(<Fact key="z" label="Limit">{`${num(o.z)} deviations`}</Fact>);
  } else if (r.type === "format_consistency") {
    if (o.dominant_shape) facts.push(<Fact key="d" label="Dominant shape"><span className="font-mono">{String(o.dominant_shape)}</span></Fact>);
    if (typeof o.share === "number") facts.push(<Fact key="s" label="Share with that shape">{formatPercent(o.share * 100, 2)}</Fact>);
  } else if (r.type === "row_count") {
    if (o.row_count != null) facts.push(<Fact key="r" label="Rows">{num(o.row_count)}</Fact>);
    if (o.min != null) facts.push(<Fact key="mi" label="Minimum">{num(o.min)}</Fact>);
    if (o.max != null) facts.push(<Fact key="ma" label="Maximum">{num(o.max)}</Fact>);
  } else if (r.type === "unique" || r.type === "duplicate_rows") {
    if (o.duplicate_groups != null) facts.push(<Fact key="g" label="Duplicate groups">{num(o.duplicate_groups)}</Fact>);
  } else if (r.type === "referential") {
    if (o.reference) facts.push(<Fact key="r" label="Reference">{String(o.reference)}</Fact>);
  }
  const shapes = r.type === "format_consistency" && Array.isArray(o.shapes) ? (o.shapes as { shape: string; count: number }[]) : [];
  if (!facts.length && !shapes.length) return null;
  return (
    <div className="space-y-2">
      {facts.length > 0 && <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">{facts}</div>}
      {shapes.length > 0 && (
        <ul className="flex flex-wrap gap-1.5">
          {shapes.map((s) => (
            <li key={s.shape} className="rounded-md bg-muted px-2 py-1 text-[12px]">
              <span className="font-mono">{s.shape}</span> <span className="text-subtle tabular">{formatNumber(s.count)}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

const PROBLEM: Record<string, string> = { missing: "Missing column", type: "Wrong type", unexpected: "Unexpected column" };

function SchemaProblems({ rows }: { rows: Record<string, unknown>[] }) {
  return (
    <ul className="space-y-1">
      {rows.map((p, i) => (
        <li key={i} className="flex flex-wrap items-baseline gap-x-2 rounded-lg bg-muted/60 px-3 py-2 text-[13px]">
          <span className="font-medium text-fail">{PROBLEM[String(p.problem)] ?? String(p.problem)}</span>
          <span className="font-mono">{String(p.column)}</span>
          <span className="text-muted-foreground">
            {p.expected != null && `expected ${String(p.expected)}`}
            {p.expected != null && p.actual != null && ", "}
            {p.actual != null && `found ${String(p.actual)}`}
          </span>
        </li>
      ))}
    </ul>
  );
}

/** One check result: a summary line that expands to what was observed and failing rows. */
export function ResultRow({ r, defaultOpen = false, order }: { r: CheckResult; defaultOpen?: boolean; order?: string[] }) {
  const [open, setOpen] = React.useState(defaultOpen);
  const id = React.useId();
  const params = describeParams(r.type, r.params);
  return (
    <li className="border-b border-hairline last:border-0">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-start gap-3 px-5 py-3 text-left transition-colors hover:bg-muted/50 focus-visible:bg-muted/50 focus-visible:outline-none"
      >
        <ChevronRightIcon className={cn("mt-0.5 size-4 shrink-0 text-subtle transition-transform", open && "rotate-90")} />
        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="text-[13px] font-medium text-foreground">{r.check_name}</span>
            <span className="text-xs text-subtle">
              {checkTypeLabel(r.type)}
              {r.column ? ` · ${r.column}` : ""}
              {params ? ` · ${params}` : ""}
            </span>
          </span>
          <span className="mt-0.5 block text-xs text-muted-foreground">{r.error ?? r.message}</span>
        </span>
        <span className="flex shrink-0 flex-col items-end gap-1">
          <ResultChip status={r.status} severity={r.severity} />
          {r.failed > 0 && r.status !== "pass" && <span className="text-[11px] text-subtle tabular">{plural(r.failed, "row")}</span>}
        </span>
      </button>
      {open && (
        <div id={id} className="space-y-3 px-5 pb-4 sm:pl-12">
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
            <span>
              Dimension <span className="text-foreground">{dimensionLabel(r.dimension)}</span>
            </span>
            <span>
              Severity <span className="text-foreground">{r.severity === "warn" ? "Warning" : "Error"}</span>
            </span>
            <span className="tabular">
              Evaluated <span className="text-foreground">{formatNumber(r.evaluated)}</span>
            </span>
            <span className="tabular">
              Failed <span className="text-foreground">{formatNumber(r.failed)}</span> ({formatPercent(r.failed_pct, 2)})
            </span>
            <span className="tabular">Took {r.ms < 1000 ? `${Math.round(r.ms)} ms` : `${(r.ms / 1000).toFixed(1)} s`}</span>
          </div>
          {r.error && <p className="rounded-lg bg-errored-soft px-3 py-2 text-[13px] text-errored">{r.error}</p>}
          <Observed r={r} />
          {r.sample.length > 0 &&
            (r.type === "schema" ? (
              <SchemaProblems rows={r.sample} />
            ) : (
              <div className="space-y-1.5">
                <div className="text-xs font-medium text-muted-foreground">
                  {r.type === "unique" || r.type === "duplicate_rows" ? "Most repeated values" : "Failing rows"} (first {r.sample.length})
                </div>
                <RowsTable rows={r.sample} order={order} />
              </div>
            ))}
          {r.status !== "pass" && !r.sample.length && !r.error && r.type !== "schema" && (
            <p className="text-xs text-subtle">No sample rows were kept for this check.</p>
          )}
        </div>
      )}
    </li>
  );
}
