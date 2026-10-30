"use client";

import { useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangleIcon,
  ArrowLeftIcon,
  CheckCircle2Icon,
  DownloadIcon,
  FileTextIcon,
  Loader2Icon,
  MinusCircleIcon,
  SquareIcon,
  XCircleIcon,
} from "lucide-react";
import Link from "next/link";
import * as React from "react";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { Hint } from "@/components/hint";
import { PageHeader } from "@/components/page-header";
import { ScanStatusChip, ScoreChip } from "@/components/quality";
import { Surface, SurfaceHeader } from "@/components/surface";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useCurrentProject } from "@/features/projects/api";
import { download } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";
import type { ScanDetail } from "@/lib/api/types";
import { cn } from "@/lib/cn";
import { formatDateTime, formatDuration, formatNumber, formatRelative, plural } from "@/lib/format";
import { qk } from "@/lib/query-keys";

import { reportUrls, useCancelScan, useScan } from "../api";
import { DimensionBars } from "./dimension-bars";
import { ResultRow } from "./result-row";
import { triggerLabel } from "./scan-list";

const ACTIVE = new Set(["queued", "running"]);

export function ScanScreen({ sid }: { sid: string }) {
  const { pid, canEdit } = useCurrentProject();
  const q = useScan(pid, sid);
  const client = useQueryClient();
  const s = q.data;
  const active = s ? ACTIVE.has(s.status) : false;

  // When a live scan finishes, everything derived from it (dataset, profile, checks'
  // last results, dashboard) is stale: refresh it once.
  const wasActive = React.useRef(false);
  React.useEffect(() => {
    if (!s) return;
    if (wasActive.current && !active) {
      void client.invalidateQueries({ queryKey: qk.dataset(pid, s.dataset_id) });
      void client.invalidateQueries({ queryKey: qk.datasets(pid) });
      void client.invalidateQueries({ queryKey: qk.dashboard(pid) });
      void client.invalidateQueries({ queryKey: qk.scansAll(pid) });
    }
    wasActive.current = active;
  }, [s, active, client, pid]);

  if (q.isPending) return <ScanSkeleton />;
  if (q.isError && !s) {
    return (
      <>
        <BackLink pid={pid} />
        <Surface>
          <ErrorState error={q.error} title="Could not load this scan" onRetry={() => void q.refetch()} />
        </Surface>
      </>
    );
  }
  if (!s) return null;
  return <ScanView pid={pid} s={s} canEdit={canEdit} />;
}

function BackLink({ pid, datasetId, datasetName }: { pid: string; datasetId?: string; datasetName?: string | null }) {
  return (
    <Link
      href={datasetId ? `/projects/${pid}/datasets/${datasetId}?tab=scans` : `/projects/${pid}/scans`}
      className="inline-flex items-center gap-1 text-[12.5px] text-muted-foreground hover:text-foreground"
    >
      <ArrowLeftIcon className="size-3.5" />
      {datasetId ? (datasetName ?? "Dataset") : "Scans"}
    </Link>
  );
}

function ScanView({ pid, s, canEdit }: { pid: string; s: ScanDetail; canEdit: boolean }) {
  const active = ACTIVE.has(s.status);
  const [busy, setBusy] = React.useState<"" | "csv" | "pdf">("");
  const [confirm, setConfirm] = React.useState(false);
  const cancel = useCancelScan(pid);
  const results = s.results ?? [];
  const failing = results.filter((r) => r.status !== "pass");
  const passing = results.filter((r) => r.status === "pass");
  const [showPassing, setShowPassing] = React.useState(false);
  const short = s.id.slice(0, 8);
  const order = React.useMemo(() => s.columns.map((c) => c.name), [s.columns]);

  async function get(kind: "csv" | "pdf") {
    setBusy(kind);
    try {
      await download(kind === "csv" ? reportUrls.csv(pid, s.id) : reportUrls.pdf(pid, s.id), `scan-${short}.${kind}`);
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setBusy("");
    }
  }

  return (
    <>
      <div className="mb-2">
        <BackLink pid={pid} datasetId={s.dataset_id} datasetName={s.dataset_name} />
      </div>
      <PageHeader
        title={
          <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <span>Scan of {s.dataset_name ?? "dataset"}</span>
            <ScanStatusChip status={s.status} />
            {s.status === "succeeded" && <ScoreChip score={s.score} />}
          </span>
        }
        description={
          <span className="flex flex-wrap gap-x-3 gap-y-0.5">
            <span>{triggerLabel(s.trigger)} scan</span>
            <span>{s.started_at ? `Started ${formatDateTime(s.started_at)}` : `Queued ${formatDateTime(s.created_at)}`}</span>
            {s.attempt > 1 && <span>Attempt {s.attempt}</span>}
            <span className="font-mono text-[12px] text-subtle">#{short}</span>
          </span>
        }
        actions={
          <>
            {active && canEdit && (
              <Button variant="destructive-soft" size="sm" onClick={() => setConfirm(true)} disabled={s.cancel_requested || cancel.isPending}>
                <SquareIcon className="size-3.5" />
                {s.cancel_requested ? "Cancelling..." : "Cancel scan"}
              </Button>
            )}
            {s.status === "succeeded" && (
              <>
                <Button variant="outline" size="sm" onClick={() => void get("csv")} disabled={!!busy}>
                  <DownloadIcon />
                  {busy === "csv" ? "Preparing..." : "CSV"}
                </Button>
                <Button variant="outline" size="sm" onClick={() => void get("pdf")} disabled={!!busy}>
                  <FileTextIcon />
                  {busy === "pdf" ? "Preparing..." : "PDF report"}
                </Button>
              </>
            )}
          </>
        }
      />

      <ConfirmDialog
        open={confirm}
        onOpenChange={setConfirm}
        title="Cancel this scan?"
        description="The scan stops at its next step and no score is recorded. You can run it again at any time."
        confirmLabel="Cancel scan"
        pending={cancel.isPending}
        onConfirm={() =>
          cancel.mutate(s.id, {
            onSuccess: () => {
              setConfirm(false);
              toast.success("Cancelling the scan");
            },
            onError: (err) => toast.error(errorMessage(err)),
          })
        }
      />

      <div className="space-y-5">
        <Facts s={s} />
        {active ? (
          <LiveProgress s={s} />
        ) : s.status === "failed" ? (
          <FailedBox pid={pid} s={s} />
        ) : s.status === "cancelled" ? (
          <Surface>
            <EmptyState
              icon={MinusCircleIcon}
              title="This scan was cancelled"
              description="It stopped before finishing, so it has no score or results. Run the dataset again to get fresh results."
              action={
                <Link href={`/projects/${pid}/datasets/${s.dataset_id}`} className="text-[13px] font-medium text-primary hover:underline">
                  Open the dataset
                </Link>
              }
            />
          </Surface>
        ) : null}

        {s.status === "succeeded" && (
          <>
            <div className="grid items-start gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
              <Surface>
                <SurfaceHeader title="Score by dimension" titleExtra={<Hint term="score" />} description="Dimensions without checks are left out of the score." />
                <div className="px-5 pb-5">
                  <DimensionBars scores={s.dimension_scores} />
                </div>
              </Surface>
              <Surface>
                <SurfaceHeader title="Check outcomes" description={`${plural(s.checks_total, "check")} ran on ${plural(s.row_count, "row")}.`} />
                <div className="grid grid-cols-2 gap-3 px-5 pb-5 sm:grid-cols-4">
                  <Outcome icon={CheckCircle2Icon} tone="text-pass bg-pass-soft" label="Passed" value={s.checks_passed} />
                  <Outcome icon={XCircleIcon} tone="text-fail bg-fail-soft" label="Failed" value={s.checks_failed} />
                  <Outcome icon={AlertTriangleIcon} tone="text-warn bg-warn-soft" label="Warnings" value={s.checks_warned} />
                  <Outcome icon={MinusCircleIcon} tone="text-errored bg-errored-soft" label="Could not run" value={s.checks_errored} />
                </div>
                <div className="flex flex-wrap gap-x-5 gap-y-1 px-5 pb-5 text-xs text-muted-foreground">
                  <span>
                    <span className="font-semibold text-foreground tabular">{formatNumber(s.failed_rows)}</span> failing rows across checks
                  </span>
                  <span>
                    <span className="font-semibold text-foreground tabular">{formatNumber(s.duplicate_rows)}</span> duplicate rows
                  </span>
                </div>
              </Surface>
            </div>

            <Surface className="overflow-hidden">
              <SurfaceHeader
                title="Results"
                description={failing.length ? "Problems first. Open a result for what was measured and the failing rows." : "Every check passed."}
              />
              {results.length === 0 ? (
                <EmptyState
                  compact
                  icon={CheckCircle2Icon}
                  title="No checks ran"
                  description="This dataset had no enabled checks when it was scanned. Add checks to the dataset, then scan again."
                  action={
                    <Link href={`/projects/${pid}/datasets/${s.dataset_id}?tab=checks`} className="text-[13px] font-medium text-primary hover:underline">
                      Add checks
                    </Link>
                  }
                />
              ) : (
                <>
                  <ul className="border-t border-hairline">
                    {failing.map((r, i) => (
                      <ResultRow key={r.id} r={r} defaultOpen={i === 0} order={order} />
                    ))}
                    {(showPassing || !failing.length) && passing.map((r) => <ResultRow key={r.id} r={r} order={order} />)}
                  </ul>
                  {failing.length > 0 && passing.length > 0 && (
                    <div className="px-5 py-3">
                      <Button variant="subtle" size="sm" onClick={() => setShowPassing((v) => !v)}>
                        {showPassing ? "Hide passing checks" : `Show ${passing.length} passing checks`}
                      </Button>
                    </div>
                  )}
                </>
              )}
            </Surface>
          </>
        )}
      </div>
    </>
  );
}

function Facts({ s }: { s: ScanDetail }) {
  const items: { label: string; value: React.ReactNode }[] = [
    { label: "Started", value: s.started_at ? formatRelative(s.started_at) : "Waiting" },
    { label: "Duration", value: s.duration_ms != null ? formatDuration(s.duration_ms) : s.started_at ? "Running" : "n/a" },
    { label: "Rows", value: s.row_count != null ? formatNumber(s.row_count) : "n/a" },
    { label: "Columns", value: s.columns.length ? formatNumber(s.columns.length) : "n/a" },
    { label: "Checks", value: formatNumber(s.checks_total) },
  ];
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
      {items.map((i, n) => (
        <div key={i.label} className={cn("surface px-4 py-3", n === items.length - 1 && "col-span-2 sm:col-span-1")}>
          <div className="text-xs text-muted-foreground">{i.label}</div>
          <div className="mt-0.5 text-[15px] font-semibold tabular">{i.value}</div>
        </div>
      ))}
    </div>
  );
}

function Outcome({ icon: Icon, tone, label, value }: { icon: typeof XCircleIcon; tone: string; label: string; value: number }) {
  return (
    <div className="flex items-center gap-2.5 rounded-xl bg-muted/50 p-3">
      <span className={cn("flex size-8 shrink-0 items-center justify-center rounded-lg", value ? tone : "bg-muted text-faint")}>
        <Icon className="size-4" />
      </span>
      <span className="min-w-0">
        <span className="block text-[18px] leading-tight font-semibold tabular">{value}</span>
        <span className="block truncate text-[11.5px] text-muted-foreground">{label}</span>
      </span>
    </div>
  );
}

function LiveProgress({ s }: { s: ScanDetail }) {
  const running = s.status === "running";
  return (
    <Surface className="overflow-hidden" aria-live="polite">
      <div className="h-1 overflow-hidden bg-primary-soft">
        <div className="h-full w-1/3 animate-[dq-slide_1.4s_ease-in-out_infinite] rounded-full bg-primary" />
      </div>
      <div className="flex flex-col items-center px-6 py-12 text-center">
        <div className="mb-3 flex size-11 items-center justify-center rounded-xl bg-primary-soft text-primary">
          <Loader2Icon className="size-5 animate-spin" />
        </div>
        <h2 className="text-sm font-semibold">{running ? "Scanning now" : "Waiting for a worker"}</h2>
        <p className="mt-1 max-w-md text-[13px] leading-relaxed text-muted-foreground">
          {running
            ? "Reading the data, running every check inside the source and profiling columns. Results appear here the moment it finishes."
            : "The scan is queued and starts as soon as a worker is free, usually within seconds."}
          {s.cancel_requested && " Cancellation was requested."}
        </p>
      </div>
      <style>{`@keyframes dq-slide{0%{transform:translateX(-100%)}100%{transform:translateX(300%)}}`}</style>
    </Surface>
  );
}

function FailedBox({ pid, s }: { pid: string; s: ScanDetail }) {
  return (
    <div role="alert" className="flex gap-3 rounded-[14px] bg-fail-soft p-5">
      <XCircleIcon className="mt-0.5 size-5 shrink-0 text-fail" />
      <div className="min-w-0">
        <h2 className="text-sm font-semibold text-fail">The scan could not finish</h2>
        <p className="mt-1 font-mono text-[12.5px] leading-relaxed break-words text-foreground">{s.error ?? "No error message was recorded."}</p>
        <p className="mt-2 text-[13px] text-muted-foreground">
          Check that the source is reachable and the login can read it, or that the dataset settings (table, query, filter) are still valid. Then scan again from the{" "}
          <Link href={`/projects/${pid}/datasets/${s.dataset_id}?tab=settings`} className="font-medium text-primary hover:underline">
            dataset settings
          </Link>
          .
        </p>
      </div>
    </div>
  );
}

function ScanSkeleton() {
  return (
    <div className="space-y-5" aria-busy aria-label="Loading the scan">
      <Skeleton className="h-4 w-24" />
      <Skeleton className="h-8 w-80 max-w-full" />
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
        {Array.from({ length: 5 }).map((_, i) => (
          <Skeleton key={i} className="h-16 rounded-[14px]" />
        ))}
      </div>
      <Skeleton className="h-64 rounded-[14px]" />
    </div>
  );
}
