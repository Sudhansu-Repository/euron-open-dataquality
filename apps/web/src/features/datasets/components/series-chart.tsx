"use client";

import * as React from "react";
import { Area, AreaChart, CartesianGrid, Tooltip, XAxis, YAxis } from "recharts";

import { CHART, ChartTooltipCard, type TooltipRow } from "@/components/charts/chart-tooltip";

export interface SeriesPoint {
  /** The x value as a label (already formatted, e.g. "Oct 14"). */
  x: string;
  y: number | null;
}

/**
 * One series over time: a 2px line over a 10% wash, a recessive horizontal grid, one
 * axis, and a crosshair tooltip. A single series needs no legend (the title names it).
 */
export function SeriesChart<P extends SeriesPoint>({
  data,
  label,
  formatY,
  formatTick,
  domain,
  ticks,
  tooltip,
  height = 220,
  ariaLabel,
}: {
  data: P[];
  label: string;
  formatY: (v: number) => string;
  formatTick?: (v: number) => string;
  domain?: [number | "auto" | "dataMin", number | "auto" | "dataMax"];
  ticks?: number[];
  /** Extra tooltip rows for a point (beside the main value). */
  tooltip?: (p: P) => { title?: string; rows?: TooltipRow[]; footer?: React.ReactNode };
  height?: number;
  ariaLabel: string;
}) {
  const gid = React.useId().replace(/:/g, "");
  return (
    <div style={{ height }} role="img" aria-label={ariaLabel} className="w-full min-w-0">
      <AreaChart responsive style={{ width: "100%", height: "100%" }} data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <defs>
            <linearGradient id={`fill-${gid}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={CHART.series1} stopOpacity={0.1} />
              <stop offset="100%" stopColor={CHART.series1} stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid vertical={false} stroke={CHART.grid} strokeWidth={1} />
          <XAxis
            dataKey="x"
            tickLine={false}
            axisLine={false}
            tick={{ fill: CHART.axis, fontSize: 11 }}
            minTickGap={28}
            tickMargin={8}
          />
          <YAxis
            width={48}
            tickLine={false}
            axisLine={false}
            tick={{ fill: CHART.axis, fontSize: 11 }}
            tickFormatter={(v: number) => (formatTick ?? formatY)(v)}
            domain={domain ?? ["auto", "auto"]}
            allowDecimals
            tickCount={4}
            ticks={ticks}
          />
          <Tooltip
            cursor={{ stroke: CHART.axis, strokeWidth: 1, strokeOpacity: 0.5 }}
            isAnimationActive={false}
            content={({ active, payload }) => {
              const item = payload?.[0];
              if (!active || !item) return null;
              const p = item.payload as P;
              const extra = tooltip?.(p);
              const rows: TooltipRow[] = [
                { label, value: p.y == null ? "No scan" : formatY(p.y), color: CHART.series1 },
                ...(extra?.rows ?? []),
              ];
              return <ChartTooltipCard title={extra?.title ?? p.x} rows={rows} footer={extra?.footer} />;
            }}
          />
          <Area
            type="monotoneX"
            dataKey="y"
            stroke={CHART.series1}
            strokeWidth={2}
            strokeLinejoin="round"
            strokeLinecap="round"
            fill={`url(#fill-${gid})`}
            connectNulls
            dot={false}
            activeDot={{ r: 4.5, fill: CHART.series1, stroke: "var(--card)", strokeWidth: 2 }}
            isAnimationActive={false}
          />
      </AreaChart>
    </div>
  );
}

/** A y-domain for scores that keeps small movements visible: a rounded floor, capped at 100. */
export function scoreDomain(values: (number | null | undefined)[]): [number, number] {
  const present = values.filter((v): v is number => v != null);
  if (!present.length) return [0, 100];
  const min = Math.min(...present);
  const floor = Math.max(0, Math.floor((min - 1) / 5) * 5);
  return [Math.min(floor, 95), 100];
}

/** Clean ticks for a score domain from scoreDomain(): 95, 97.5, 100 or 80, 90, 100. */
export function scoreTicks([lo, hi]: [number, number]): number[] {
  const span = hi - lo;
  const step = span <= 5 ? 2.5 : span <= 10 ? 5 : span <= 20 ? 10 : span <= 50 ? 25 : 50;
  const out: number[] = [];
  for (let v = hi; v >= lo - 1e-9; v -= step) out.unshift(Math.round(v * 10) / 10);
  return out;
}

const dayFmt = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric" });
const dayLongFmt = new Intl.DateTimeFormat("en-US", { weekday: "short", month: "short", day: "numeric" });

/** "2026-10-14" (a calendar day) as "Oct 14", read in UTC so the day never shifts. */
export function shortDay(day: string, long = false): string {
  const d = new Date(day.length === 10 ? `${day}T00:00:00Z` : day);
  if (Number.isNaN(d.getTime())) return day;
  return (long ? dayLongFmt : dayFmt).format(day.length === 10 ? new Date(d.getTime() + d.getTimezoneOffset() * 60_000) : d);
}
