"use client";

import { CalendarClockIcon, DatabaseIcon, PlayIcon, PlusIcon, SearchIcon, SirenIcon, XCircleIcon } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import * as React from "react";
import { toast } from "sonner";

import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { PageHeader } from "@/components/page-header";
import { ScanStatusChip, ScoreValue } from "@/components/quality";
import { Surface } from "@/components/surface";
import { Button, buttonVariants } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { useCurrentProject } from "@/features/projects/api";
import { useRunScan } from "@/features/scans/api";
import { errorMessage } from "@/lib/api/errors";
import type { Dataset } from "@/lib/api/types";
import { cn } from "@/lib/cn";
import { formatCompact, formatNumber, formatRelative } from "@/lib/format";
import { DATASET_KINDS, scoreLabel } from "@/lib/quality";

import { useDatasets } from "../api";
import { kindLabel, scheduleText, sourceLabel } from "../meta";

type Health = "healthy" | "attention" | "poor" | "unscanned";
const HEALTH: { value: Health; label: string }[] = [
  { value: "healthy", label: "Healthy" },
  { value: "attention", label: "Needs attention" },
  { value: "poor", label: "Poor" },
  { value: "unscanned", label: "Not scanned" },
];

function healthOf(d: Dataset): Health {
  const l = scoreLabel(d.last_score);
  if (l === "Healthy") return "healthy";
  if (l === "Needs attention") return "attention";
  if (l === "Poor") return "poor";
  return "unscanned";
}

function FilterChip({ active, onClick, children, count }: { active: boolean; onClick: () => void; children: React.ReactNode; count?: number }) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        "inline-flex h-7 items-center gap-1.5 rounded-full px-3 text-[12.5px] font-medium transition-colors focus-visible:outline-2 focus-visible:outline-ring",
        active ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground hover:bg-accent hover:text-foreground",
      )}
    >
      {children}
      {count != null && <span className={cn("tabular text-[11px]", active ? "opacity-80" : "text-faint")}>{count}</span>}
    </button>
  );
}

export function DatasetsScreen() {
  const { pid, canEdit } = useCurrentProject();
  const q = useDatasets(pid);
  const [search, setSearch] = React.useState("");
  const [kind, setKind] = React.useState<string>("");
  const [health, setHealth] = React.useState<Health | "">("");

  const all = React.useMemo(() => q.data ?? [], [q.data]);
  const kinds = React.useMemo(() => Object.keys(DATASET_KINDS).filter((k) => all.some((d) => d.kind === k)), [all]);
  const term = search.trim().toLowerCase();
  const rows = all.filter(
    (d) =>
      (!kind || d.kind === kind) &&
      (!health || healthOf(d) === health) &&
      (!term || [d.name, d.description, sourceLabel(d), ...d.tags].some((t) => t.toLowerCase().includes(term))),
  );
  const filtered = !!(term || kind || health);
  const clear = () => {
    setSearch("");
    setKind("");
    setHealth("");
  };

  return (
    <>
      <PageHeader
        title="Datasets"
        description="Tables, queries, files, REST endpoints and pushed records that DataQuality checks. Each one has its own checks, profile, schedule and score."
        actions={
          canEdit && all.length > 0 ? (
            <Link href={`/projects/${pid}/datasets/new`} className={buttonVariants({ size: "sm" })}>
              <PlusIcon />
              Add dataset
            </Link>
          ) : undefined
        }
      />
      {q.isPending ? (
        <ListSkeleton />
      ) : q.isError && !q.data ? (
        <Surface>
          <ErrorState error={q.error} title="Could not load datasets" onRetry={() => void q.refetch()} />
        </Surface>
      ) : all.length === 0 ? (
        <Surface>
          <EmptyState
            icon={DatabaseIcon}
            title="No datasets yet"
            description="A dataset is anything DataQuality can read: a database table or query, an uploaded CSV or Excel file, a JSON endpoint, or records your app pushes. Add one to profile it and get checks suggested."
            action={
              canEdit ? (
                <Link href={`/projects/${pid}/datasets/new`} className={buttonVariants()}>
                  <PlusIcon />
                  Add a dataset
                </Link>
              ) : (
                <span className="text-[13px] text-muted-foreground">Ask an editor of this project to add one.</span>
              )
            }
          />
        </Surface>
      ) : (
        <>
          <div className="mb-4 flex flex-col gap-3">
            <div className="relative w-full sm:w-80">
              <SearchIcon className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-faint" />
              <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search by name, source or tag" aria-label="Search datasets" className="pl-9" />
            </div>
            <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="Filter by kind and health">
              <FilterChip active={!kind} onClick={() => setKind("")}>
                All kinds
              </FilterChip>
              {kinds.map((k) => (
                <FilterChip key={k} active={kind === k} onClick={() => setKind(kind === k ? "" : k)} count={all.filter((d) => d.kind === k).length}>
                  {kindLabel(k)}
                </FilterChip>
              ))}
              <span className="mx-1 h-4 w-px bg-border" aria-hidden />
              {HEALTH.filter((h) => all.some((d) => healthOf(d) === h.value)).map((h) => (
                <FilterChip key={h.value} active={health === h.value} onClick={() => setHealth(health === h.value ? "" : h.value)} count={all.filter((d) => healthOf(d) === h.value).length}>
                  {h.label}
                </FilterChip>
              ))}
            </div>
          </div>
          {rows.length === 0 ? (
            <Surface>
              <EmptyState
                icon={SearchIcon}
                title="No datasets match"
                description={filtered ? "Nothing matches this search and these filters. Clear them to see every dataset." : ""}
                action={
                  <Button variant="outline" size="sm" onClick={clear}>
                    Clear filters
                  </Button>
                }
              />
            </Surface>
          ) : (
            <ul className="space-y-2.5">
              {rows.map((d) => (
                <DatasetRow key={d.id} pid={pid} d={d} canEdit={canEdit} />
              ))}
            </ul>
          )}
        </>
      )}
    </>
  );
}

function Metric({ label, children, className, wrap = false }: { label: string; children: React.ReactNode; className?: string; wrap?: boolean }) {
  return (
    <div className={cn("min-w-0", className)}>
      <div className="text-[11px] text-subtle">{label}</div>
      <div className={cn("mt-0.5 text-[13px] font-medium tabular", wrap ? "leading-snug" : "truncate")}>{children}</div>
    </div>
  );
}

function DatasetRow({ pid, d, canEdit }: { pid: string; d: Dataset; canEdit: boolean }) {
  const router = useRouter();
  const run = useRunScan(pid);
  const href = `/projects/${pid}/datasets/${d.id}`;
  const failing = d.last_failed_checks ?? 0;
  const incidents = d.open_incidents ?? 0;
  const live = d.last_status === "queued" || d.last_status === "running";

  function scanNow() {
    run.mutate(
      { datasetId: d.id },
      {
        onSuccess: (scan) =>
          toast.success(`Scan of ${d.name} started`, {
            action: { label: "View scan", onClick: () => router.push(`/projects/${pid}/scans/${scan.id}`) },
          }),
        onError: (err) => toast.error(errorMessage(err)),
      },
    );
  }

  return (
    <li className="surface group relative transition-shadow hover:shadow-[var(--elev-3)]">
      <div className="flex flex-col gap-3 p-4 sm:px-5 lg:flex-row lg:items-center lg:gap-6">
        <div className="min-w-0 lg:w-[27%]">
          <div className="flex items-center gap-2">
            <Link href={href} className="truncate text-[14px] font-semibold text-foreground after:absolute after:inset-0 after:rounded-[14px] hover:text-primary focus-visible:outline-none focus-visible:after:outline-2 focus-visible:after:outline-ring">
              {d.name}
            </Link>
            <span className="shrink-0 rounded-md bg-muted px-1.5 py-0.5 text-[11px] font-medium text-muted-foreground">{kindLabel(d.kind)}</span>
          </div>
          <div className="mt-0.5 truncate text-xs text-muted-foreground">{sourceLabel(d)}</div>
          {d.tags.length > 0 && (
            <div className="mt-1.5 flex flex-wrap gap-1">
              {d.tags.slice(0, 4).map((t) => (
                <span key={t} className="rounded bg-primary-soft px-1.5 py-px text-[10.5px] font-medium text-primary">
                  {t}
                </span>
              ))}
            </div>
          )}
        </div>
        <div className="grid min-w-0 flex-1 grid-cols-3 gap-x-4 gap-y-2.5 sm:grid-cols-[4.5rem_4rem_6.5rem_4.5rem_5rem_minmax(8rem,1fr)]">
          <Metric label="Score">
            {live ? <ScanStatusChip status={d.last_status ?? "queued"} /> : <ScoreValue score={d.last_score} />}
          </Metric>
          <Metric label="Rows">
            <span title={d.last_row_count == null ? undefined : formatNumber(d.last_row_count)}>{d.last_row_count == null ? "n/a" : formatCompact(d.last_row_count)}</span>
          </Metric>
          <Metric label="Failing checks">
            <span className={cn("inline-flex items-center gap-1", failing > 0 ? "text-fail" : "text-muted-foreground")}>
              {failing > 0 && <XCircleIcon className="size-3.5" />}
              {d.last_failed_checks == null ? "n/a" : failing}
              <span className="font-normal text-faint">/ {d.checks ?? 0}</span>
            </span>
          </Metric>
          <Metric label="Incidents">
            <span className={cn("inline-flex items-center gap-1", incidents > 0 ? "text-fail" : "text-muted-foreground")}>
              {incidents > 0 && <SirenIcon className="size-3.5" />}
              {incidents}
            </span>
          </Metric>
          <Metric label="Last scan">
            <span className="font-normal text-muted-foreground">{formatRelative(d.last_scan_at)}</span>
          </Metric>
          <Metric label="Schedule" wrap>
            <span className="inline-flex max-w-full items-start gap-1 font-normal text-muted-foreground" title={d.schedule_cron ? `${d.schedule_cron} (${d.schedule_tz})` : undefined}>
              {d.schedule_enabled && d.schedule_cron && <CalendarClockIcon className="mt-0.5 size-3.5 shrink-0" />}
              <span className="min-w-0 break-words">{scheduleText(d)}</span>
            </span>
          </Metric>
        </div>
        {canEdit && (
          <Button variant="outline" size="sm" className="relative z-[1] self-start lg:self-center" onClick={scanNow} disabled={run.isPending || live}>
            <PlayIcon className="size-3.5" />
            {run.isPending ? "Starting..." : "Scan now"}
          </Button>
        )}
      </div>
    </li>
  );
}

function ListSkeleton() {
  return (
    <div className="space-y-2.5" aria-busy aria-label="Loading datasets">
      <Skeleton className="mb-4 h-9 w-80 max-w-full" />
      {Array.from({ length: 6 }).map((_, i) => (
        <Skeleton key={i} className="h-[76px] rounded-[14px]" />
      ))}
    </div>
  );
}
