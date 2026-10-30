"use client";

import { ArrowLeftIcon, CalendarClockIcon, DownloadIcon, Link2Icon, PlayIcon, TerminalIcon, UploadIcon } from "lucide-react";
import Link from "next/link";
import * as React from "react";
import { toast } from "sonner";

import { CopyButton } from "@/components/copy-button";
import { ErrorState } from "@/components/error-state";
import { ScoreChip } from "@/components/quality";
import { Surface } from "@/components/surface";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ChecksTab } from "@/features/checks/components/checks-tab";
import { useCurrentProject } from "@/features/projects/api";
import { reportUrls, useScanPages } from "@/features/scans/api";
import { NoScans, ScanList } from "@/features/scans/components/scan-list";
import { download } from "@/lib/api/client";
import { ApiError, errorMessage } from "@/lib/api/errors";
import type { Dataset } from "@/lib/api/types";
import { formatRelative } from "@/lib/format";
import { useTabParam } from "@/lib/use-tab-param";

import { useDataset, useUploadFile } from "../api";
import { kindLabel, restOptions, scheduleText, sourceLabel } from "../meta";
import { useActiveScan } from "../use-active-scan";
import { useScanAndOpen } from "../use-scan-and-open";
import { DatasetOverview } from "./dataset-overview";
import { DatasetProfile } from "./dataset-profile";
import { DatasetSettings } from "./dataset-settings";

const TABS = ["overview", "profile", "checks", "scans", "settings"] as const;
type Tab = (typeof TABS)[number];
const TAB_LABEL: Record<Tab, string> = { overview: "Overview", profile: "Profile", checks: "Checks", scans: "Scans", settings: "Settings" };

export function DatasetScreen({ did }: { did: string }) {
  const { pid, canEdit } = useCurrentProject();
  const q = useDataset(pid, did);
  const [tab, setTab] = useTabParam<Tab>("overview", TABS);

  if (q.isPending) return <HeaderSkeleton />;
  if (q.isError && !q.data) {
    const gone = q.error instanceof ApiError && q.error.status === 404;
    return (
      <>
        <BackToList pid={pid} />
        <Surface>
          <ErrorState
            error={q.error}
            title={gone ? "This dataset does not exist" : "Could not load this dataset"}
            onRetry={gone ? undefined : () => void q.refetch()}
          />
        </Surface>
      </>
    );
  }
  const d = q.data;
  return (
    <>
      <BackToList pid={pid} />
      <DatasetHeader pid={pid} d={d} canEdit={canEdit} />
      <Tabs value={tab} onValueChange={(v) => setTab(String(v))} className="mt-5">
        <div className="-mx-4 overflow-x-auto px-4 no-scrollbar sm:mx-0 sm:px-0">
          <TabsList className="flex-nowrap">
            {TABS.map((t) => (
              <TabsTrigger key={t} value={t}>
                {TAB_LABEL[t]}
                {t === "checks" && d.checks ? <span className="text-[11px] text-subtle tabular">{d.checks}</span> : null}
              </TabsTrigger>
            ))}
          </TabsList>
        </div>
        <TabsContent value="overview">{tab === "overview" && <DatasetOverview pid={pid} d={d} canEdit={canEdit} />}</TabsContent>
        <TabsContent value="profile">{tab === "profile" && <DatasetProfile pid={pid} d={d} canEdit={canEdit} />}</TabsContent>
        <TabsContent value="checks">{tab === "checks" && <ChecksTab pid={pid} d={d} canEdit={canEdit} />}</TabsContent>
        <TabsContent value="scans">{tab === "scans" && <DatasetScans pid={pid} d={d} canEdit={canEdit} />}</TabsContent>
        <TabsContent value="settings">{tab === "settings" && <DatasetSettings pid={pid} d={d} canEdit={canEdit} />}</TabsContent>
      </Tabs>
    </>
  );
}

function BackToList({ pid }: { pid: string }) {
  return (
    <Link href={`/projects/${pid}/datasets`} className="mb-2 inline-flex items-center gap-1 text-[12.5px] text-muted-foreground hover:text-foreground">
      <ArrowLeftIcon className="size-3.5" />
      Datasets
    </Link>
  );
}

function DatasetHeader({ pid, d, canEdit }: { pid: string; d: Dataset; canEdit: boolean }) {
  const scan = useScanAndOpen(pid);
  const upload = useUploadFile(pid);
  const fileRef = React.useRef<HTMLInputElement>(null);
  const { active: live } = useActiveScan(pid, d.id);

  function onFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    upload.mutate(
      { file, datasetId: d.id },
      {
        onSuccess: () => toast.success(`Uploaded ${file.name} as the newest version. Scan it to check it.`),
        onError: (err) => toast.error(errorMessage(err)),
      },
    );
  }

  return (
    <div>
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
            <h1 className="text-[22px] leading-tight font-semibold tracking-[-0.02em]">{d.name}</h1>
            <ScoreChip score={d.last_score} />
          </div>
          <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[13px] text-muted-foreground">
            <span className="rounded-md bg-muted px-1.5 py-0.5 text-[11.5px] font-medium">{kindLabel(d.kind)}</span>
            <span className="min-w-0 truncate">{sourceLabel(d)}</span>
            <span aria-hidden className="text-faint">·</span>
            <span>Last scan {formatRelative(d.last_scan_at).toLowerCase()}</span>
            <span aria-hidden className="text-faint">·</span>
            <span className="inline-flex items-center gap-1">
              <CalendarClockIcon className="size-3.5" />
              {scheduleText(d)}
            </span>
          </div>
          {d.description && <p className="mt-2 max-w-2xl text-[13px] leading-relaxed text-muted-foreground">{d.description}</p>}
          {d.tags.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1">
              {d.tags.map((t) => (
                <span key={t} className="rounded bg-primary-soft px-1.5 py-px text-[11px] font-medium text-primary">
                  {t}
                </span>
              ))}
            </div>
          )}
        </div>
        {canEdit && (
          <div className="flex shrink-0 flex-wrap gap-2">
            {d.kind === "file" && (
              <>
                <input ref={fileRef} type="file" className="hidden" accept=".csv,.tsv,.txt,.xlsx,.xls,.json,.jsonl,.ndjson,.parquet" onChange={onFile} />
                <Button variant="outline" size="sm" onClick={() => fileRef.current?.click()} disabled={upload.isPending}>
                  <UploadIcon />
                  {upload.isPending ? "Uploading..." : "Upload new version"}
                </Button>
              </>
            )}
            <Button size="sm" onClick={() => scan.start(d.id)} disabled={scan.pending || live}>
              <PlayIcon className="size-3.5" />
              {live ? "Scan in progress" : scan.pending ? "Starting..." : "Scan now"}
            </Button>
          </div>
        )}
      </div>
      {d.kind === "push" && <PushPanel pid={pid} d={d} />}
      {d.kind === "rest" && restOptions(d).url && (
        <div className="mt-3 flex max-w-full min-w-0 items-center gap-2 rounded-lg bg-muted/70 px-3 py-2 text-[12.5px]">
          <Link2Icon className="size-3.5 shrink-0 text-subtle" />
          <span className="min-w-0 truncate font-mono" title={restOptions(d).url}>
            {restOptions(d).url}
          </span>
          {restOptions(d).records_path && <span className="shrink-0 text-subtle">records at {restOptions(d).records_path}</span>}
        </div>
      )}
    </div>
  );
}

function PushPanel({ pid, d }: { pid: string; d: Dataset }) {
  const [open, setOpen] = React.useState(!d.last_scan_id);
  const origin = typeof window === "undefined" ? "" : window.location.origin;
  const curl = `curl -X POST "${origin}/api/v1/projects/${pid}/datasets/${d.id}/records?wait=30" \\
  -H "X-API-Key: dq_your_key" \\
  -H "Content-Type: application/json" \\
  -d '{"records": [{"id": 1, "email": "asha@example.com"}]}'`;
  return (
    <div className="mt-3 rounded-xl bg-muted/60">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2 px-4 py-2.5 text-left text-[13px] font-medium focus-visible:outline-2 focus-visible:outline-ring"
      >
        <TerminalIcon className="size-4 text-primary" />
        How to push records
        <span className="ml-auto text-xs font-normal text-muted-foreground">{open ? "Hide" : "Show"}</span>
      </button>
      {open && (
        <div className="space-y-2 px-4 pb-4">
          <p className="text-[12.5px] leading-relaxed text-muted-foreground">
            Send a batch of JSON records; each batch becomes the newest version and is validated against this dataset&apos;s checks. The response carries the scan
            result (it waits up to <code className="font-mono">wait</code> seconds). Create a key with the push scope in{" "}
            <Link href={`/projects/${pid}/settings`} className="font-medium text-primary hover:underline">
              Project settings
            </Link>
            .
          </p>
          <div className="relative">
            <pre className="overflow-x-auto rounded-lg bg-code-bg p-3 pr-20 font-mono text-[12px] leading-relaxed text-code-fg">{curl}</pre>
            <CopyButton value={curl} className="absolute top-2 right-2" variant="subtle" />
          </div>
        </div>
      )}
    </div>
  );
}

function DatasetScans({ pid, d, canEdit }: { pid: string; d: Dataset; canEdit: boolean }) {
  const q = useScanPages(pid, { dataset_id: d.id, limit: 30 });
  const scan = useScanAndOpen(pid);
  const [busy, setBusy] = React.useState(false);
  async function history() {
    setBusy(true);
    try {
      await download(reportUrls.history(pid, d.id), `${d.slug}-history.csv`);
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Surface className="overflow-hidden">
      <div className="flex flex-wrap items-start justify-between gap-3 px-5 pt-4 pb-3">
        <div>
          <h2 className="text-[14px] font-semibold">Scan history</h2>
          <p className="mt-0.5 text-xs text-muted-foreground">Every scan of {d.name}, newest first.</p>
        </div>
        {!!d.last_scan_id && (
          <Button variant="outline" size="sm" onClick={() => void history()} disabled={busy}>
            <DownloadIcon />
            {busy ? "Preparing..." : "Download history (CSV)"}
          </Button>
        )}
      </div>
      <ScanList
        pid={pid}
        q={q}
        showDataset={false}
        empty={
          <NoScans
            title="Not scanned yet"
            description="A scan reads the dataset, runs its checks inside the source, profiles the columns and records a score."
            action={
              canEdit ? (
                <Button size="sm" onClick={() => scan.start(d.id)} disabled={scan.pending}>
                  <PlayIcon className="size-3.5" />
                  Run the first scan
                </Button>
              ) : undefined
            }
          />
        }
      />
    </Surface>
  );
}

function HeaderSkeleton() {
  return (
    <div className="space-y-3" aria-busy aria-label="Loading the dataset">
      <Skeleton className="h-4 w-20" />
      <Skeleton className="h-8 w-72 max-w-full" />
      <Skeleton className="h-4 w-96 max-w-full" />
      <Skeleton className="mt-6 h-8 w-80 max-w-full" />
      <Skeleton className="h-72 rounded-[14px]" />
    </div>
  );
}
