"use client";

import {
  ArrowDownRightIcon,
  ArrowRightIcon,
  ArrowUpRightIcon,
  CableIcon,
  CopyIcon,
  DatabaseIcon,
  DownloadIcon,
  GaugeIcon,
  PlusIcon,
  ShieldCheckIcon,
  SirenIcon,
  SparklesIcon,
  XCircleIcon,
} from "lucide-react";
import Link from "next/link";
import * as React from "react";
import { toast } from "sonner";

import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { Hint } from "@/components/hint";
import { PageHeader } from "@/components/page-header";
import { ScoreValue, toneText } from "@/components/quality";
import { Stat } from "@/components/stat";
import { Surface, SurfaceHeader } from "@/components/surface";
import { Button, buttonVariants } from "@/components/ui/button";
import { Chip } from "@/components/ui/chip";
import { Skeleton } from "@/components/ui/skeleton";
import { useCurrentProject } from "@/features/projects/api";
import { DimensionBars } from "@/features/scans/components/dimension-bars";
import { reportUrls } from "@/features/scans/api";
import { download } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";
import type { Dashboard } from "@/lib/api/types";
import { cn } from "@/lib/cn";
import { formatCompact, formatNumber, formatPercent, formatRelative } from "@/lib/format";
import { checkTypeLabel, scoreLabel, scoreTone } from "@/lib/quality";

import { kindLabel } from "../../datasets/meta";
import { SeriesChart, scoreDomain, scoreTicks, shortDay } from "../../datasets/components/series-chart";
import { useDashboard } from "../api";

export function DashboardScreen() {
  const { pid, project, canEdit } = useCurrentProject();
  const q = useDashboard(pid);
  const [downloading, setDownloading] = React.useState(false);

  async function downloadSummary() {
    setDownloading(true);
    try {
      await download(reportUrls.summary(pid), "dataquality-summary.pdf");
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setDownloading(false);
    }
  }

  const d = q.data;
  const empty = d && d.datasets === 0;

  return (
    <>
      <PageHeader
        title="Dashboard"
        description={project ? `How healthy the data in ${project.name} is right now, and where it is failing.` : "How healthy your data is right now, and where it is failing."}
        actions={
          d && !empty ? (
            <Button variant="outline" size="sm" onClick={downloadSummary} disabled={downloading}>
              <DownloadIcon />
              {downloading ? "Preparing..." : "Download summary (PDF)"}
            </Button>
          ) : undefined
        }
      />
      {q.isPending ? (
        <DashboardSkeleton />
      ) : q.isError && !d ? (
        <Surface>
          <ErrorState error={q.error} title="Could not load the dashboard" onRetry={() => void q.refetch()} />
        </Surface>
      ) : empty ? (
        <Welcome pid={pid} canEdit={canEdit} />
      ) : d ? (
        <DashboardBody pid={pid} d={d} />
      ) : null}
    </>
  );
}

function DashboardBody({ pid, d }: { pid: string; d: Dashboard }) {
  const base = `/projects/${pid}`;
  const unscanned = d.datasets - d.datasets_scanned;
  return (
    <div className="space-y-5">
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.35fr)]">
        <HeroScore d={d} />
        <Surface>
          <SurfaceHeader
            title="Score by dimension"
            titleExtra={<Hint term="score" />}
            description="Latest scan of every dataset, per kind of quality."
          />
          <div className="px-5 pt-1 pb-5">
            <DimensionBars scores={d.dimensions} />
          </div>
        </Surface>
      </div>

      <div className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-5">
        <Stat
          label="Datasets scanned"
          icon={DatabaseIcon}
          value={
            <span>
              {formatNumber(d.datasets_scanned)}
              <span className="text-[15px] font-medium text-muted-foreground"> of {formatNumber(d.datasets)}</span>
            </span>
          }
          detail={unscanned > 0 ? `${unscanned} not scanned yet` : `${formatNumber(d.scans_24h)} scans in 24 hours`}
        />
        <Stat label="Records scanned" icon={GaugeIcon} value={<span title={formatNumber(d.records_scanned)}>{formatCompact(d.records_scanned)}</span>} detail="Rows in the latest scans" />
        <Stat
          label="Failed checks"
          icon={XCircleIcon}
          value={<span className={cn(d.failed_checks > 0 && "text-fail")}>{formatNumber(d.failed_checks)}</span>}
          detail="In the latest scans"
        />
        <Stat
          label="Duplicate records"
          icon={CopyIcon}
          value={<span className={cn(d.duplicate_records > 0 && "text-warn")}>{formatNumber(d.duplicate_records)}</span>}
          detail="Extra copies of rows or keys"
        />
        <Link
          href={`${base}/incidents`}
          className="col-span-2 rounded-[14px] transition-transform focus-visible:outline-2 focus-visible:outline-ring sm:col-span-1 lg:col-span-1 [&:hover>div]:shadow-[var(--elev-3)]"
        >
          <Stat
            className="h-full transition-shadow"
            label="Open incidents"
            icon={SirenIcon}
            value={<span className={cn(d.open_incidents > 0 && "text-fail")}>{formatNumber(d.open_incidents)}</span>}
            detail={
              <span className="inline-flex items-center gap-1 text-primary">
                View incidents <ArrowRightIcon className="size-3" />
              </span>
            }
          />
        </Link>
      </div>

      <Surface>
        <SurfaceHeader title="Quality score, last 30 days" description="Average score of the scans that ran each day. Hover a day for its scans and failed checks." />
        <div className="px-3 pb-4 sm:px-5">
          {d.trend.some((t) => t.score != null) ? (
            <SeriesChart
              ariaLabel="Quality score per day for the last 30 days"
              label="Score"
              data={d.trend.map((t) => ({ ...t, x: shortDay(t.day), y: t.score }))}
              formatY={(v) => formatPercent(v)}
              formatTick={(v) => `${v}%`}
              domain={scoreDomain(d.trend.map((t) => t.score))}
              ticks={scoreTicks(scoreDomain(d.trend.map((t) => t.score)))}
              tooltip={(p) => ({
                title: shortDay(p.day, true),
                rows: [
                  { label: "Scans", value: formatNumber(p.scans), color: "transparent" },
                  { label: "Failed checks", value: formatNumber(p.failed_checks), color: "transparent" },
                ],
              })}
              height={240}
            />
          ) : (
            <p className="px-2 py-10 text-center text-[13px] text-muted-foreground">The trend appears once scans have run on at least one day.</p>
          )}
        </div>
      </Surface>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
        <RecentIssues base={base} d={d} />
        <NeedsAttention base={base} d={d} />
      </div>
    </div>
  );
}

function HeroScore({ d }: { d: Dashboard }) {
  const tone = scoreTone(d.score);
  const change = d.score_change;
  const up = change != null && change > 0;
  const flat = change == null || change === 0;
  return (
    <Surface className="relative flex flex-col justify-between overflow-hidden p-6">
      <div>
        <div className="flex items-center gap-1.5 text-[13px] font-medium text-muted-foreground">
          Overall quality score <Hint term="score" />
        </div>
        <div className="mt-3 flex flex-wrap items-end gap-x-4 gap-y-2">
          <span className={cn("text-[56px] leading-none font-semibold tracking-[-0.04em]", toneText(tone))}>
            {d.score == null ? "n/a" : formatPercent(d.score)}
          </span>
          <Chip tone={tone} className="mb-2 h-6 px-2.5 text-[12px]">
            {tone === "success" ? <ShieldCheckIcon /> : <SirenIcon />}
            {scoreLabel(d.score)}
          </Chip>
        </div>
        <div className="mt-3 flex items-center gap-1.5 text-[13px] text-muted-foreground">
          {flat ? (
            <span>{change == null ? "No history from a week ago yet" : "Unchanged from a week ago"}</span>
          ) : (
            <>
              <span className={cn("inline-flex items-center gap-0.5 font-semibold tabular", up ? "text-pass" : "text-fail")}>
                {up ? <ArrowUpRightIcon className="size-4" /> : <ArrowDownRightIcon className="size-4" />}
                {up ? "+" : ""}
                {change.toFixed(1)} pts
              </span>
              <span>versus a week ago</span>
            </>
          )}
        </div>
      </div>
      <p className="mt-6 max-w-sm text-[12.5px] leading-relaxed text-muted-foreground">
        98% and above is healthy, 90% and above needs attention, below 90% is poor. Updated {formatRelative(d.generated_at)}.
      </p>
    </Surface>
  );
}

function RecentIssues({ base, d }: { base: string; d: Dashboard }) {
  return (
    <Surface className="overflow-hidden">
      <SurfaceHeader title="Recent issues" description="Failing checks in the latest scan of each dataset, errors first." />
      {d.issues.length === 0 ? (
        <EmptyState
          compact
          icon={ShieldCheckIcon}
          title="No failing checks"
          description="Every check passed in the latest scans. New failures show up here as soon as a scan finds them."
        />
      ) : (
        <ul className="pb-2">
          {d.issues.map((i, n) => (
            <li key={`${i.scan_id}-${n}`}>
              <Link
                href={`${base}/scans/${i.scan_id}`}
                className="group flex items-start gap-3 px-5 py-3 transition-colors hover:bg-muted/60 focus-visible:bg-muted/60 focus-visible:outline-none"
              >
                <span
                  className={cn("mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-lg", i.severity === "warn" ? "bg-warn-soft text-warn" : "bg-fail-soft text-fail")}
                  aria-label={i.severity === "warn" ? "Warning" : "Error"}
                >
                  <XCircleIcon className="size-4" />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="flex flex-wrap items-baseline gap-x-2">
                    <span className="truncate text-[13px] font-medium text-foreground group-hover:text-primary">{i.check_name}</span>
                    <span className="text-xs text-subtle">
                      {i.dataset_name}
                      {i.column ? ` · ${i.column}` : ""} · {checkTypeLabel(i.type)}
                    </span>
                  </span>
                  <span className="mt-0.5 block truncate text-xs text-muted-foreground">{i.message}</span>
                </span>
                <span className="shrink-0 text-right">
                  <span className={cn("block text-[13px] font-semibold tabular", i.severity === "warn" ? "text-warn" : "text-fail")}>{formatNumber(i.failed)}</span>
                  <span className="block text-[11px] text-subtle">failed rows</span>
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Surface>
  );
}

function NeedsAttention({ base, d }: { base: string; d: Dashboard }) {
  return (
    <Surface className="overflow-hidden">
      <SurfaceHeader
        title="Datasets needing attention"
        description="Lowest scores first."
        action={
          <Link href={`${base}/datasets`} className={buttonVariants({ variant: "subtle", size: "xs" })}>
            All datasets
          </Link>
        }
      />
      <ul className="pb-2">
        {d.worst.map((w) => (
          <li key={w.id}>
            <Link
              href={`${base}/datasets/${w.id}`}
              className="group flex items-center gap-3 px-5 py-2.5 transition-colors hover:bg-muted/60 focus-visible:bg-muted/60 focus-visible:outline-none"
            >
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[13px] font-medium text-foreground group-hover:text-primary">{w.name}</span>
                <span className="block text-xs text-subtle">
                  {kindLabel(w.kind)} · {w.row_count == null ? "not scanned" : `${formatCompact(w.row_count)} rows`}
                  {w.failed_checks ? ` · ${w.failed_checks} failing` : ""} · {formatRelative(w.last_scan_at)}
                </span>
              </span>
              <ScoreValue score={w.score} className="text-[14px]" />
            </Link>
          </li>
        ))}
      </ul>
    </Surface>
  );
}

function Welcome({ pid, canEdit }: { pid: string; canEdit: boolean }) {
  const steps = [
    { icon: DatabaseIcon, title: "Add your data", text: "A table or query from PostgreSQL, MySQL, SQL Server or SQLite, a CSV or Excel file, a REST endpoint, or records your app pushes." },
    { icon: SparklesIcon, title: "Get checks suggested", text: "The first scan profiles every column and proposes checks: missing values, duplicates, formats, ranges, freshness." },
    { icon: SirenIcon, title: "Hear about problems", text: "Scheduled scans score each dataset, spot anomalies and open incidents, and alert you by email, Slack or webhook." },
  ];
  return (
    <Surface className="overflow-hidden">
      <div className="px-6 pt-10 pb-6 text-center sm:px-10">
        <div className="mx-auto mb-4 flex size-12 items-center justify-center rounded-2xl bg-primary-soft text-primary">
          <ShieldCheckIcon className="size-6" />
        </div>
        <h2 className="text-lg font-semibold tracking-[-0.01em]">Know your data is right before anyone else finds out it is not</h2>
        <p className="mx-auto mt-2 max-w-xl text-[13px] leading-relaxed text-muted-foreground">
          DataQuality checks your datasets for missing, invalid, duplicate and stale records, scores their health, and tells you when something breaks. This project has no datasets yet.
        </p>
        {canEdit ? (
          <div className="mt-5 flex flex-wrap items-center justify-center gap-2">
            <Link href={`/projects/${pid}/datasets/new`} className={buttonVariants()}>
              <PlusIcon />
              Add a dataset
            </Link>
            <Link href={`/projects/${pid}/connections`} className={buttonVariants({ variant: "outline" })}>
              <CableIcon />
              Connect a database
            </Link>
          </div>
        ) : (
          <p className="mt-4 text-[13px] text-muted-foreground">Ask an editor of this project to add the first dataset.</p>
        )}
      </div>
      <ol className="grid gap-3 bg-muted/40 p-5 sm:grid-cols-3 sm:p-6">
        {steps.map((s, i) => (
          <li key={s.title} className="rounded-xl bg-card p-4 shadow-[var(--elev-1)]">
            <div className="flex items-center gap-2 text-[13px] font-semibold">
              <span className="flex size-6 items-center justify-center rounded-md bg-primary-soft text-[11px] text-primary tabular">{i + 1}</span>
              {s.title}
            </div>
            <p className="mt-1.5 text-xs leading-relaxed text-muted-foreground">{s.text}</p>
          </li>
        ))}
      </ol>
    </Surface>
  );
}

function DashboardSkeleton() {
  return (
    <div className="space-y-5" aria-busy aria-label="Loading the dashboard">
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.35fr)]">
        <Skeleton className="h-56 rounded-[14px]" />
        <Skeleton className="h-56 rounded-[14px]" />
      </div>
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
        {Array.from({ length: 5 }).map((_, i) => (
          <Skeleton key={i} className="h-24 rounded-[14px]" />
        ))}
      </div>
      <Skeleton className="h-72 rounded-[14px]" />
    </div>
  );
}
