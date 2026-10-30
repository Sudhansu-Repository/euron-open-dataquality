"use client";

import { EyeIcon, EyeOffIcon, Loader2Icon, ScanSearchIcon } from "lucide-react";
import * as React from "react";

import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { Hint } from "@/components/hint";
import { Surface, SurfaceHeader } from "@/components/surface";
import { TableSkeleton } from "@/components/table-skeleton";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { RowsTable } from "@/features/scans/components/result-row";
import { ApiError } from "@/lib/api/errors";
import type { ColumnProfile, Dataset } from "@/lib/api/types";
import { cn } from "@/lib/cn";
import { formatDuration, formatNumber, formatPercent, formatRelative } from "@/lib/format";

import { usePreview, useProfile } from "../api";
import { useActiveScan } from "../use-active-scan";
import { useScanAndOpen } from "../use-scan-and-open";
import { ColumnSheet, valueText } from "./column-sheet";

export function missingOf(c: ColumnProfile): { n: number; pct: number } {
  const n = c.nulls + c.blanks;
  return { n, pct: c.rows ? (100 * n) / c.rows : 0 };
}

export function DatasetProfile({ pid, d, canEdit }: { pid: string; d: Dataset; canEdit: boolean }) {
  // A dataset with no finished scan has no profile, so do not ask for one (a 404).
  const q = useProfile(pid, d.id, !!d.last_scan_id);
  const { active: scanning } = useActiveScan(pid, d.id);
  const scan = useScanAndOpen(pid);
  const [selected, setSelected] = React.useState<ColumnProfile | null>(null);
  const [preview, setPreview] = React.useState(false);

  const notProfiled = !d.last_scan_id || (q.error instanceof ApiError && (q.error.code === "no_profile" || q.error.status === 404));

  let body: React.ReactNode;
  if (!d.last_scan_id && scanning) {
    body = (
      <Surface>
        <EmptyState
          icon={Loader2Icon}
          title="Profiling now"
          description="The first scan is reading this dataset. Its column profile appears here when the scan finishes."
        />
      </Surface>
    );
  } else if (notProfiled) {
    body = (
      <Surface>
        <EmptyState
          icon={ScanSearchIcon}
          title="Not profiled yet"
          description="A profile summarizes every column inside the source: types, missing values, distinct values, ranges, common values and value shapes. It is computed during a scan."
          action={
            canEdit ? (
              <Button onClick={() => scan.start(d.id, true)} disabled={scan.pending}>
                {scan.pending ? "Starting..." : "Scan with profiling"}
              </Button>
            ) : (
              <span className="text-[13px] text-muted-foreground">An editor of this project can run a profiling scan.</span>
            )
          }
        />
      </Surface>
    );
  } else if (q.isPending) {
    body = (
      <Surface className="pt-3">
        <TableSkeleton rows={8} cols={7} />
      </Surface>
    );
  } else if (q.isError && !q.data) {
    body = (
      <Surface>
        <ErrorState error={q.error} title="Could not load the profile" onRetry={() => void q.refetch()} />
      </Surface>
    );
  } else if (q.data) {
    const p = q.data;
    body = (
      <Surface className="overflow-hidden">
        <SurfaceHeader
          title="Column profile"
          titleExtra={<Hint term="profile" />}
          description={
            <>
              {p.sampled ? `Profiled the first ${formatNumber(p.rows_profiled)} of ${formatNumber(p.row_count)} rows` : `All ${formatNumber(p.row_count)} rows profiled`}
              {` · ${p.columns.length} columns · ${formatRelative(p.created_at)} in ${formatDuration(p.ms)}. Select a column for its details.`}
            </>
          }
        />
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Column</TableHead>
              <TableHead>Type</TableHead>
              <TableHead>Missing</TableHead>
              <TableHead className="text-right">Distinct</TableHead>
              <TableHead className="hidden md:table-cell">Min</TableHead>
              <TableHead className="hidden md:table-cell">Max</TableHead>
              <TableHead className="hidden text-right lg:table-cell">Mean</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {p.columns.map((c) => {
              const m = missingOf(c);
              return (
                <TableRow key={c.name} className="cursor-pointer" onClick={() => setSelected(c)}>
                  <TableCell className="max-w-[220px]">
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        setSelected(c);
                      }}
                      className="block max-w-full truncate text-left font-mono text-[12.5px] font-medium text-foreground hover:text-primary focus-visible:text-primary focus-visible:outline-none"
                    >
                      {c.name}
                    </button>
                  </TableCell>
                  <TableCell>
                    <span className="rounded bg-muted px-1.5 py-0.5 text-[11.5px] text-muted-foreground" title={c.native}>
                      {c.logical}
                    </span>
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center gap-2">
                      <div className="h-1.5 w-14 shrink-0 overflow-hidden rounded-full bg-muted" aria-hidden>
                        {m.n > 0 && <div className="h-full rounded-full bg-warn" style={{ width: `${Math.max(4, Math.min(100, m.pct))}%` }} />}
                      </div>
                      <span className={cn("whitespace-nowrap tabular", m.n ? "text-foreground" : "text-faint")}>
                        {formatNumber(m.n)}
                        <span className="text-subtle"> ({formatPercent(m.pct, m.pct > 0 && m.pct < 0.1 ? 2 : 1)})</span>
                      </span>
                    </div>
                  </TableCell>
                  <TableCell className="text-right tabular">{c.distinct == null ? <span className="text-faint">n/a</span> : formatNumber(c.distinct)}</TableCell>
                  <TableCell className="hidden max-w-[160px] truncate font-mono text-[12px] md:table-cell" title={valueText(c.min)}>
                    {valueText(c.min)}
                  </TableCell>
                  <TableCell className="hidden max-w-[160px] truncate font-mono text-[12px] md:table-cell" title={valueText(c.max)}>
                    {valueText(c.max)}
                  </TableCell>
                  <TableCell className="hidden text-right tabular lg:table-cell">
                    {c.mean == null ? <span className="text-faint">n/a</span> : c.mean.toLocaleString("en-US", { maximumFractionDigits: 2 })}
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </Surface>
    );
  }

  return (
    <div className="space-y-5">
      {body}
      <PreviewPanel pid={pid} did={d.id} open={preview} onToggle={() => setPreview((v) => !v)} masked={d.masked_columns} />
      <ColumnSheet column={selected} onOpenChange={(o) => !o && setSelected(null)} />
    </div>
  );
}

function PreviewPanel({ pid, did, open, onToggle, masked }: { pid: string; did: string; open: boolean; onToggle: () => void; masked: string[] }) {
  const q = usePreview(pid, did, open);
  const columns = q.data?.columns.map((c) => String(c.name)) ?? [];
  return (
    <Surface className="overflow-hidden">
      <SurfaceHeader
        title="Preview rows"
        description={
          masked.length
            ? `The first 50 rows, read live from the source. ${masked.length} masked column${masked.length === 1 ? " shows" : "s show"} [masked].`
            : "The first 50 rows, read live from the source."
        }
        action={
          <Button variant="outline" size="sm" onClick={onToggle} aria-expanded={open}>
            {open ? <EyeOffIcon /> : <EyeIcon />}
            {open ? "Hide rows" : "Preview rows"}
          </Button>
        }
      />
      {open && (
        <div className="px-5 pb-5">
          {q.isPending ? (
            <TableSkeleton rows={6} cols={6} />
          ) : q.isError && !q.data ? (
            <ErrorState compact error={q.error} title="Could not read the rows" onRetry={() => void q.refetch()} />
          ) : q.data && q.data.rows.length === 0 ? (
            <p className="py-6 text-center text-[13px] text-muted-foreground">The source returned no rows.</p>
          ) : q.data ? (
            <RowsTable rows={q.data.rows} columns={columns} maxHeight={440} />
          ) : null}
        </div>
      )}
    </Surface>
  );
}
