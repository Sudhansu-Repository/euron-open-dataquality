"use client";

import { HistoryIcon } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import * as React from "react";

import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { ScanStatusChip, ScoreValue } from "@/components/quality";
import { TableSkeleton } from "@/components/table-skeleton";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { Scan } from "@/lib/api/types";
import { cn } from "@/lib/cn";
import { formatCompact, formatDateTime, formatDuration, formatNumber, formatRelative } from "@/lib/format";

import { type useScanPages } from "../api";

export const TRIGGER_LABEL: Record<string, string> = {
  manual: "Manual",
  schedule: "Scheduled",
  push: "Push",
  upload: "Upload",
  api: "API",
  retry: "Retry",
};

export function triggerLabel(t: string): string {
  return TRIGGER_LABEL[t] ?? t.charAt(0).toUpperCase() + t.slice(1);
}

/**
 * A page-by-page list of scans: each row opens its scan. Rows are links (keyboard and
 * middle click work); the table scrolls inside its own container on narrow screens.
 */
export function ScanList({
  pid,
  q,
  showDataset = true,
  empty,
}: {
  pid: string;
  q: ReturnType<typeof useScanPages>;
  showDataset?: boolean;
  empty: React.ReactNode;
}) {
  const router = useRouter();
  const rows: Scan[] = q.data?.pages.flatMap((p) => p.items) ?? [];

  if (q.isPending) {
    return (
      <div className="pt-3">
        <TableSkeleton rows={8} cols={6} />
      </div>
    );
  }
  if (q.isError && !q.data) return <ErrorState error={q.error} title="Could not load scans" onRetry={() => void q.refetch()} />;
  if (!rows.length) return <>{empty}</>;

  return (
    <>
      <Table>
        <TableHeader>
          <TableRow>
            {showDataset && <TableHead>Dataset</TableHead>}
            <TableHead>Status</TableHead>
            <TableHead>Started</TableHead>
            <TableHead className="hidden sm:table-cell">Trigger</TableHead>
            <TableHead className="text-right">Duration</TableHead>
            <TableHead className="text-right">Rows</TableHead>
            <TableHead className="text-right">Score</TableHead>
            <TableHead className="text-right">Failed checks</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((s) => {
            const href = `/projects/${pid}/scans/${s.id}`;
            const failing = s.checks_failed + s.checks_errored;
            return (
              <TableRow key={s.id} className="cursor-pointer" onClick={(e) => !(e.target as HTMLElement).closest("a") && router.push(href)}>
                {showDataset && (
                  <TableCell className="max-w-[220px]">
                    <Link href={href} className="block truncate font-medium text-foreground hover:text-primary focus-visible:text-primary">
                      {s.dataset_name ?? "Dataset"}
                    </Link>
                  </TableCell>
                )}
                <TableCell>
                  {showDataset ? (
                    <ScanStatusChip status={s.status} />
                  ) : (
                    <Link href={href} aria-label={`Open scan from ${formatDateTime(s.created_at)}`} className="rounded-full focus-visible:outline-2 focus-visible:outline-ring">
                      <ScanStatusChip status={s.status} />
                    </Link>
                  )}
                </TableCell>
                <TableCell className="whitespace-nowrap">
                  <div className="tabular">{formatDateTime(s.started_at ?? s.created_at)}</div>
                  <div className="text-[11px] text-subtle">{formatRelative(s.started_at ?? s.created_at)}</div>
                </TableCell>
                <TableCell className="hidden text-muted-foreground sm:table-cell">{triggerLabel(s.trigger)}</TableCell>
                <TableCell className="text-right whitespace-nowrap text-muted-foreground tabular">{s.duration_ms == null ? "" : formatDuration(s.duration_ms)}</TableCell>
                <TableCell className="text-right tabular" title={s.row_count == null ? undefined : formatNumber(s.row_count)}>
                  {s.row_count == null ? <span className="text-faint">n/a</span> : formatCompact(s.row_count)}
                </TableCell>
                <TableCell className="text-right">
                  <ScoreValue score={s.score} className="tabular" />
                </TableCell>
                <TableCell className="text-right tabular">
                  {s.status === "succeeded" ? (
                    <span className={cn(failing > 0 ? "font-semibold text-fail" : "text-muted-foreground")}>
                      {failing}
                      <span className="font-normal text-faint"> / {s.checks_total}</span>
                    </span>
                  ) : (
                    <span className="text-faint">n/a</span>
                  )}
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
      <div className="flex items-center justify-between gap-3 px-5 py-3 text-xs text-muted-foreground">
        <span className="tabular">
          {rows.length} scan{rows.length === 1 ? "" : "s"} shown
        </span>
        {q.hasNextPage ? (
          <Button variant="outline" size="sm" onClick={() => void q.fetchNextPage()} disabled={q.isFetchingNextPage}>
            {q.isFetchingNextPage ? "Loading..." : "Load more"}
          </Button>
        ) : (
          <span>That is every scan</span>
        )}
      </div>
    </>
  );
}

export function NoScans({ title, description, action }: { title: string; description: string; action?: React.ReactNode }) {
  return <EmptyState icon={HistoryIcon} title={title} description={description} action={action} />;
}
