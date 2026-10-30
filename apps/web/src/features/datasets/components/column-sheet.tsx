"use client";

import * as React from "react";
import { Bar, BarChart, CartesianGrid, Tooltip, XAxis, YAxis } from "recharts";

import { CHART, ChartTooltipCard } from "@/components/charts/chart-tooltip";
import { Hint } from "@/components/hint";
import { Sheet, SheetBody, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import type { ColumnProfile } from "@/lib/api/types";
import { formatCompact, formatNumber, formatPercent } from "@/lib/format";

/** A profile value (min, max, a top value) as short text. */
export function valueText(v: unknown): string {
  if (v === null || v === undefined) return "n/a";
  if (typeof v === "number") return v.toLocaleString("en-US", { maximumFractionDigits: 4 });
  if (typeof v === "string") return v === "" ? '""' : v;
  return JSON.stringify(v);
}

const SEMANTIC_LABEL: Record<string, string> = {
  email: "emails",
  phone: "phone numbers",
  url: "URLs",
  uuid: "UUIDs",
  date: "dates",
  datetime: "date-times",
  integer: "whole numbers",
  decimal: "decimal numbers",
  boolean: "true/false values",
};

function Section({ title, hint, children }: { title: string; hint?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="mt-6">
      <h3 className="mb-2.5 flex items-center gap-1.5 text-[12px] font-semibold tracking-[0.04em] text-subtle uppercase">
        {title}
        {hint}
      </h3>
      {children}
    </section>
  );
}

function Fact({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="min-w-0 rounded-lg bg-muted/60 px-3 py-2">
      <div className="text-[11px] text-subtle">{label}</div>
      <div className="mt-0.5 truncate text-[13px] font-medium tabular" title={typeof value === "string" ? value : undefined}>
        {value}
      </div>
    </div>
  );
}

function compactEdge(n: number): string {
  return Math.abs(n) >= 1000 ? formatCompact(n) : n.toLocaleString("en-US", { maximumFractionDigits: 2 });
}

function Histogram({ c }: { c: ColumnProfile }) {
  const data = c.histogram.map((b) => ({ ...b, label: compactEdge(b.low) }));
  return (
    <div className="h-48" role="img" aria-label={`Distribution of ${c.name} in ${data.length} bins`}>
      <BarChart responsive style={{ width: "100%", height: "100%" }} data={data} margin={{ top: 4, right: 4, bottom: 0, left: 0 }} barCategoryGap={2}>
          <CartesianGrid vertical={false} stroke={CHART.grid} />
          <XAxis dataKey="label" tickLine={false} axisLine={false} tick={{ fill: CHART.axis, fontSize: 10.5 }} interval="preserveStartEnd" minTickGap={16} />
          <YAxis width={40} tickLine={false} axisLine={false} tick={{ fill: CHART.axis, fontSize: 10.5 }} tickFormatter={(v: number) => formatCompact(v)} tickCount={4} />
          <Tooltip
            cursor={{ fill: "var(--muted)", opacity: 0.6 }}
            isAnimationActive={false}
            content={({ active, payload }) => {
              const item = payload?.[0];
              if (!active || !item) return null;
              const b = item.payload as (typeof data)[number];
              return (
                <ChartTooltipCard
                  title={`${valueText(b.low)} to ${valueText(b.high)}`}
                  rows={[{ label: "Rows", value: formatNumber(b.count), color: CHART.series1 }]}
                />
              );
            }}
          />
          <Bar dataKey="count" fill={CHART.series1} radius={[4, 4, 0, 0]} maxBarSize={24} isAnimationActive={false} />
      </BarChart>
    </div>
  );
}

/** Counted items as thin horizontal bars, the count at the tip. */
function share(n: number, total: number): string {
  const pct = total ? (100 * n) / total : 0;
  return formatPercent(pct, pct > 0 && pct < 1 ? 2 : 1);
}

function CountBars({ items, total, mono = false }: { items: { label: string; count: number }[]; total: number; mono?: boolean }) {
  const max = Math.max(1, ...items.map((i) => i.count));
  return (
    <ul className="space-y-1.5">
      {items.map((i) => (
        <li key={i.label} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3" title={`${i.label}: ${formatNumber(i.count)} (${share(i.count, total)})`}>
          <div className="min-w-0">
            <div className={mono ? "truncate font-mono text-[12px]" : "truncate text-[12.5px]"}>{i.label}</div>
            <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-muted">
              <div className="h-full rounded-full bg-series-1" style={{ width: `${Math.max(2, (100 * i.count) / max)}%` }} />
            </div>
          </div>
          <div className="text-right text-[12px] tabular">
            {formatNumber(i.count)}
            <span className="ml-1 text-subtle">{share(i.count, total)}</span>
          </div>
        </li>
      ))}
    </ul>
  );
}

export function ColumnSheet({ column: c, onOpenChange }: { column: ColumnProfile | null; onOpenChange: (open: boolean) => void }) {
  // Keep the last column while the sheet animates closed.
  const [shown, setShown] = React.useState<ColumnProfile | null>(c);
  React.useEffect(() => {
    if (c) setShown(c);
  }, [c]);
  const col = c ?? shown;
  return (
    <Sheet open={!!c} onOpenChange={onOpenChange}>
      <SheetContent>{col && <ColumnDetail c={col} />}</SheetContent>
    </Sheet>
  );
}

function ColumnDetail({ c }: { c: ColumnProfile }) {
  const missing = c.nulls + c.blanks;
  const present = c.rows - missing;
  const semantic = Object.entries(c.semantic ?? {})
    .filter(([, share]) => share >= 0.05)
    .sort((a, b) => b[1] - a[1]);
  const quantiles = Object.entries(c.quantiles ?? {});
  const numeric = c.mean != null;
  const mostlyUnique = c.distinct != null && present > 0 && c.distinct / present > 0.95;

  return (
    <>
      <SheetHeader>
        <SheetTitle className="font-mono">{c.name}</SheetTitle>
        <SheetDescription>
          {c.logical} ({c.native}) · {formatNumber(c.rows)} rows profiled
        </SheetDescription>
      </SheetHeader>
      <SheetBody>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
          <Fact label="Missing (null)" value={`${formatNumber(c.nulls)}`} />
          <Fact label="Blank text" value={formatNumber(c.blanks)} />
          <Fact label="Missing share" value={formatPercent(c.rows ? (100 * missing) / c.rows : 0, 2)} />
          <Fact label="Distinct" value={c.distinct == null ? "n/a" : formatNumber(c.distinct)} />
          <Fact label="Min" value={valueText(c.min)} />
          <Fact label="Max" value={valueText(c.max)} />
          {numeric && <Fact label="Mean" value={valueText(c.mean)} />}
          {c.stddev != null && <Fact label="Std deviation" value={valueText(c.stddev)} />}
          {c.distinct != null && present > 0 && <Fact label="Unique share" value={formatPercent((100 * c.distinct) / present, 1)} />}
        </div>

        {semantic.length > 0 && (
          <Section title="Looks like">
            <ul className="flex flex-wrap gap-1.5">
              {semantic.map(([k, share]) => (
                <li key={k} className="rounded-md bg-primary-soft px-2 py-1 text-[12.5px] text-primary">
                  <span className="font-semibold tabular">{formatPercent(share * 100, share > 0.99 && share < 1 ? 2 : 1)}</span> look like {SEMANTIC_LABEL[k] ?? k}
                </li>
              ))}
            </ul>
          </Section>
        )}

        {c.histogram.length > 0 && (
          <Section title="Distribution">
            <Histogram c={c} />
          </Section>
        )}

        {quantiles.length > 0 && (
          <Section title="Quantiles">
            <div className="grid grid-cols-3 gap-2 sm:grid-cols-5">
              {quantiles.map(([k, v]) => (
                <Fact key={k} label={k.toUpperCase()} value={valueText(v)} />
              ))}
            </div>
          </Section>
        )}

        {c.top_values.length > 0 && (
          <Section title="Most common values">
            {mostlyUnique ? (
              <p className="text-[13px] text-muted-foreground">Nearly every value is different, so no value stands out. The most repeated one appears {formatNumber(c.top_values[0]?.count ?? 0)} times.</p>
            ) : (
              <CountBars items={c.top_values.map((t) => ({ label: valueText(t.value), count: t.count }))} total={present} />
            )}
          </Section>
        )}

        {c.shapes.length > 0 && (
          <Section title="Value shapes" hint={<Hint term="shape" />}>
            <CountBars items={c.shapes.map((s) => ({ label: s.shape, count: s.count }))} total={present} mono />
          </Section>
        )}

        {(c.min_length != null || c.max_length != null) && (
          <Section title="Text length">
            <div className="grid grid-cols-3 gap-2">
              <Fact label="Shortest" value={valueText(c.min_length)} />
              <Fact label="Average" value={c.mean_length == null ? "n/a" : c.mean_length.toFixed(1)} />
              <Fact label="Longest" value={valueText(c.max_length)} />
            </div>
          </Section>
        )}
      </SheetBody>
    </>
  );
}
