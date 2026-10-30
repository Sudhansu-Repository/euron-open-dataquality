"use client";

import { ActivityIcon, AlertTriangleIcon, ArrowRightIcon, CheckCircle2Icon, MinusCircleIcon, PlayIcon, ScanSearchIcon, SirenIcon, XCircleIcon } from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { Hint } from "@/components/hint";
import { Surface, SurfaceHeader } from "@/components/surface";
import { Button } from "@/components/ui/button";
import { Chip } from "@/components/ui/chip";
import { Skeleton } from "@/components/ui/skeleton";
import { useIncidents } from "@/features/alerts/api";
import { useAnomalies, useScan } from "@/features/scans/api";
import { DimensionBars } from "@/features/scans/components/dimension-bars";
import type { Dataset, MetricSeries } from "@/lib/api/types";
import { cn } from "@/lib/cn";
import { formatCompact, formatNumber, formatPercent, formatRelative, plural } from "@/lib/format";

import { useMetrics } from "../api";
import { useScanAndOpen } from "../use-scan-and-open";
import { SeriesChart, scoreDomain, scoreTicks } from "./series-chart";

const pointFmt = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric" });
const pointLongFmt = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false });

interface Pt {
  x: string;
  y: number | null;
  at: string;
}

function toPoints(series: MetricSeries[] | undefined): Pt[] {
  const pts = series?.[0]?.points ?? [];
  return pts
    .map((p) => {
      const at = typeof p.at === "string" ? p.at : "";
      const v = typeof p.value === "number" ? p.value : null;
      return { at, y: v, x: at ? pointFmt.format(new Date(at)) : "" };
    })
    .filter((p) => p.at);
}

export function DatasetOverview({ pid, d, canEdit }: { pid: string; d: Dataset; canEdit: boolean }) {
  const scan = useScanAndOpen(pid);
  if (!d.last_scan_id) {
    return (
      <Surface>
        <EmptyState
          icon={ScanSearchIcon}
          title="This dataset has not been scanned yet"
          description="The first scan reads the data inside its source, profiles every column, suggests checks and records a score. It usually takes a few seconds."
          action={
            canEdit ? (
              <Button onClick={() => scan.start(d.id, true)} disabled={scan.pending}>
                <PlayIcon className="size-3.5" />
                {scan.pending ? "Starting..." : "Run the first scan"}
              </Button>
            ) : (
              <span className="text-[13px] text-muted-foreground">An editor of this project can run it.</span>
            )
          }
        />
      </Surface>
    );
  }
  return (
    <div className="space-y-5">
      <div className="grid items-start gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <LatestScan pid={pid} sid={d.last_scan_id} />
        <OpenIncidents pid={pid} did={d.id} />
      </div>
      <div className="grid gap-5 lg:grid-cols-2">
        <HistoryChart pid={pid} did={d.id} metric="score" />
        <HistoryChart pid={pid} did={d.id} metric="row_count" />
      </div>
      <RecentAnomalies pid={pid} did={d.id} />
    </div>
  );
}

function LatestScan({ pid, sid }: { pid: string; sid: string }) {
  const q = useScan(pid, sid);
  const s = q.data;
  return (
    <Surface>
      <SurfaceHeader
        title="Latest scan"
        titleExtra={<Hint term="score" />}
        description={s ? `${formatRelative(s.finished_at ?? s.created_at)} · ${plural(s.row_count, "row")}` : undefined}
        action={
          <Link href={`/projects/${pid}/scans/${sid}`} className="inline-flex items-center gap-1 text-[12.5px] font-medium text-primary hover:underline">
            Open scan <ArrowRightIcon className="size-3" />
          </Link>
        }
      />
      <div className="px-5 pb-5">
        {q.isPending ? (
          <div className="space-y-3">
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className="h-4" />
            ))}
          </div>
        ) : q.isError && !s ? (
          <ErrorState compact error={q.error} onRetry={() => void q.refetch()} />
        ) : s && s.status !== "succeeded" ? (
          <p className="py-6 text-center text-[13px] text-muted-foreground">
            The latest scan is {s.status === "failed" ? "failed" : s.status}. Open it for details.
          </p>
        ) : s ? (
          <>
            <div className="mb-5 flex flex-wrap gap-2">
              <Count icon={CheckCircle2Icon} tone="success" n={s.checks_passed} label="passed" />
              <Count icon={XCircleIcon} tone="danger" n={s.checks_failed} label="failed" />
              <Count icon={AlertTriangleIcon} tone="warning" n={s.checks_warned} label={s.checks_warned === 1 ? "warning" : "warnings"} />
              <Count icon={MinusCircleIcon} tone="neutral" n={s.checks_errored} label="could not run" />
            </div>
            <DimensionBars scores={s.dimension_scores} />
          </>
        ) : null}
      </div>
    </Surface>
  );
}

function Count({ icon: Icon, tone, n, label }: { icon: typeof XCircleIcon; tone: "success" | "danger" | "warning" | "neutral"; n: number; label: string }) {
  return (
    <Chip tone={n ? tone : "neutral"} className={cn("h-6 px-2.5 text-[12px]", !n && "opacity-70")}>
      <Icon />
      <span className="tabular">{n}</span> {label}
    </Chip>
  );
}

function OpenIncidents({ pid, did }: { pid: string; did: string }) {
  const q = useIncidents(pid, { dataset_id: did, status: "active", limit: 6 });
  const rows = q.data ?? [];
  return (
    <Surface className="overflow-hidden">
      <SurfaceHeader title="Open incidents" titleExtra={<Hint term="incident" />} description="Problems an alert rule opened for this dataset." />
      {q.isPending ? (
        <div className="space-y-2 px-5 pb-5">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-12" />
          ))}
        </div>
      ) : q.isError && !q.data ? (
        <ErrorState compact error={q.error} onRetry={() => void q.refetch()} />
      ) : rows.length === 0 ? (
        <EmptyState
          compact
          icon={CheckCircle2Icon}
          title="No open incidents"
          description="When an alert rule matches a scan of this dataset, the incident shows up here until a later scan shows it fixed."
        />
      ) : (
        <ul className="pb-2">
          {rows.map((i) => (
            <li key={i.id}>
              <Link href={`/projects/${pid}/incidents/${i.id}`} className="group flex items-start gap-3 px-5 py-2.5 transition-colors hover:bg-muted/60 focus-visible:bg-muted/60 focus-visible:outline-none">
                <span className={cn("mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-lg", i.severity === "warn" ? "bg-warn-soft text-warn" : "bg-fail-soft text-fail")}>
                  <SirenIcon className="size-3.5" />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[13px] font-medium group-hover:text-primary">{i.title}</span>
                  <span className="block truncate text-xs text-muted-foreground">
                    {i.status === "acknowledged" ? "Acknowledged" : "Open"} · seen {i.occurrences} time{i.occurrences === 1 ? "" : "s"} · last {formatRelative(i.last_seen_at)}
                  </span>
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Surface>
  );
}

function HistoryChart({ pid, did, metric }: { pid: string; did: string; metric: "score" | "row_count" }) {
  const q = useMetrics(pid, did, metric);
  const points = React.useMemo(() => toPoints(q.data), [q.data]);
  const score = metric === "score";
  return (
    <Surface>
      <SurfaceHeader
        title={score ? "Score history" : "Row count history"}
        description={score ? "Quality score of each scan, last 30 days." : "Rows read by each scan, last 30 days. A sudden drop often means a broken load."}
      />
      <div className="px-3 pb-4 sm:px-5">
        {q.isPending ? (
          <Skeleton className="h-[200px]" />
        ) : q.isError && !q.data ? (
          <ErrorState compact error={q.error} onRetry={() => void q.refetch()} />
        ) : points.length < 2 ? (
          <p className="flex h-[200px] items-center justify-center px-4 text-center text-[13px] text-muted-foreground">The history appears after two or more scans.</p>
        ) : (
          <SeriesChart
            ariaLabel={score ? "Score per scan over the last 30 days" : "Row count per scan over the last 30 days"}
            data={points}
            label={score ? "Score" : "Rows"}
            formatY={score ? (v) => formatPercent(v) : (v) => formatNumber(v)}
            formatTick={score ? (v) => `${v}%` : (v) => formatCompact(v)}
            domain={score ? scoreDomain(points.map((p) => p.y)) : [0, "auto"]}
            ticks={score ? scoreTicks(scoreDomain(points.map((p) => p.y))) : undefined}
            tooltip={(p) => ({ title: pointLongFmt.format(new Date(p.at)) })}
            height={200}
          />
        )}
      </div>
    </Surface>
  );
}

function RecentAnomalies({ pid, did }: { pid: string; did: string }) {
  const q = useAnomalies(pid, did);
  const rows = (q.data ?? []).slice(0, 8);
  return (
    <Surface className="overflow-hidden">
      <SurfaceHeader title="Recent anomalies" titleExtra={<Hint term="anomaly" />} description="Metrics that moved far from their own history, and schema changes." />
      {q.isPending ? (
        <div className="space-y-2 px-5 pb-5">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-10" />
          ))}
        </div>
      ) : q.isError && !q.data ? (
        <ErrorState compact error={q.error} onRetry={() => void q.refetch()} />
      ) : rows.length === 0 ? (
        <EmptyState
          compact
          icon={ActivityIcon}
          title="Nothing unusual"
          description="Every scan learns what normal looks like for this dataset: row counts, missing values, failure rates. Big departures appear here."
        />
      ) : (
        <ul className="pb-2">
          {rows.map((a) => (
            <li key={a.id} className="flex items-start gap-3 px-5 py-2.5">
              <Chip tone={a.kind === "schema" ? "info" : "warning"} className="mt-0.5">
                {a.kind === "schema" ? "Schema" : "Metric"}
              </Chip>
              <span className="min-w-0 flex-1 text-[13px] leading-snug">{a.explanation}</span>
              {a.scan_id ? (
                <Link href={`/projects/${pid}/scans/${a.scan_id}`} className="shrink-0 text-xs text-muted-foreground hover:text-primary">
                  {formatRelative(a.created_at)}
                </Link>
              ) : (
                <span className="shrink-0 text-xs text-muted-foreground">{formatRelative(a.created_at)}</span>
              )}
            </li>
          ))}
        </ul>
      )}
    </Surface>
  );
}
