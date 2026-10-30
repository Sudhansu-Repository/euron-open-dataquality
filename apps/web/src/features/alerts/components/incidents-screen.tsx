"use client";

import { BellRingIcon, ChevronRightIcon, SirenIcon } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import * as React from "react";

import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { Hint } from "@/components/hint";
import { PageHeader } from "@/components/page-header";
import { IncidentStatusChip, SeverityChip } from "@/components/quality";
import { Segmented } from "@/components/segmented";
import { Surface } from "@/components/surface";
import { TableSkeleton } from "@/components/table-skeleton";
import { buttonVariants } from "@/components/ui/button";
import { SimpleSelect } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useDatasets } from "@/features/datasets/api";
import { useCurrentProject } from "@/features/projects/api";
import { GLOSSARY } from "@/lib/glossary";
import { formatDateTime, formatNumber, formatRelative } from "@/lib/format";

import { useIncidents } from "../api";

type Filter = "active" | "resolved" | "all";

export function IncidentsScreen() {
  const { pid } = useCurrentProject();
  const router = useRouter();
  const [filter, setFilter] = React.useState<Filter>("active");
  const [datasetId, setDatasetId] = React.useState("");
  const datasets = useDatasets(pid);
  const q = useIncidents(pid, { status: filter === "all" ? undefined : filter, dataset_id: datasetId || undefined, limit: 200 });
  const rows = q.data ?? [];
  const filtered = filter !== "active" || !!datasetId;

  return (
    <>
      <PageHeader
        title={
          <span className="inline-flex items-center gap-2">
            Incidents
            <Hint term="incident" />
          </span>
        }
        description="Problems your alert rules found. Each stays open while later scans still show it, notifies once, and resolves itself when a scan shows it gone."
      />
      <div className="mb-3 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <Segmented<Filter>
          ariaLabel="Incident status"
          value={filter}
          onChange={setFilter}
          className="sm:w-auto"
          options={[
            { value: "active", label: "Active" },
            { value: "resolved", label: "Resolved" },
            { value: "all", label: "All" },
          ]}
        />
        <SimpleSelect
          aria-label="Dataset"
          size="sm"
          className="sm:w-56"
          value={datasetId || "all"}
          onValueChange={(v) => setDatasetId(v === "all" ? "" : v)}
          options={[{ value: "all", label: "All datasets" }, ...(datasets.data ?? []).map((d) => ({ value: d.id, label: d.name }))]}
        />
      </div>
      <Surface className="overflow-hidden">
        {q.isPending ? (
          <div className="pt-3">
            <TableSkeleton rows={6} cols={5} />
          </div>
        ) : q.isError ? (
          <ErrorState error={q.error} title="Incidents could not be loaded" onRetry={() => void q.refetch()} />
        ) : rows.length === 0 ? (
          filtered ? (
            <EmptyState
              icon={SirenIcon}
              title={filter === "active" ? "Nothing open here" : "No incidents match"}
              description={
                filter === "active"
                  ? "No open or acknowledged incident for this dataset. Everything its rules watch is passing."
                  : "Try another status or dataset."
              }
            />
          ) : (
            <EmptyState
              icon={SirenIcon}
              title="No incidents"
              description={`${GLOSSARY.incident} Set up alert rules to decide what counts as a problem and who hears about it.`}
              action={
                <Link href={`/projects/${pid}/alerts`} className={buttonVariants({ size: "sm" })}>
                  <BellRingIcon />
                  Set up alert rules
                </Link>
              }
            />
          )
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="hidden w-28 sm:table-cell">Severity</TableHead>
                <TableHead>Incident</TableHead>
                <TableHead className="hidden lg:table-cell">Opened</TableHead>
                <TableHead className="hidden md:table-cell">Last seen</TableHead>
                <TableHead className="hidden text-right sm:table-cell">Scans</TableHead>
                <TableHead className="hidden sm:table-cell">Status</TableHead>
                <TableHead className="w-8" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((i) => {
                const href = `/projects/${pid}/incidents/${i.id}`;
                return (
                  <TableRow key={i.id} className="cursor-pointer" onClick={() => router.push(href)}>
                    <TableCell className="hidden sm:table-cell">
                      <SeverityChip severity={i.severity} />
                    </TableCell>
                    <TableCell className="max-w-0 sm:min-w-48">
                      <Link href={href} className="line-clamp-2 block font-medium hover:underline sm:truncate focus-visible:outline-2 focus-visible:outline-ring" onClick={(e) => e.stopPropagation()}>
                        {i.title}
                      </Link>
                      <div className="line-clamp-2 text-[12px] text-muted-foreground sm:truncate">
                        {i.dataset_name && !i.title.startsWith(i.dataset_name)
                          ? `${i.dataset_name}${i.detail ? `: ${i.detail}` : ""}`
                          : i.detail || i.dataset_name}
                      </div>
                      <div className="mt-1.5 flex flex-wrap gap-1.5 sm:hidden">
                        <SeverityChip severity={i.severity} />
                        <IncidentStatusChip status={i.status} />
                      </div>
                    </TableCell>
                    <TableCell className="hidden whitespace-nowrap text-muted-foreground lg:table-cell" title={formatDateTime(i.opened_at)}>
                      {formatDateTime(i.opened_at)}
                    </TableCell>
                    <TableCell className="hidden whitespace-nowrap text-muted-foreground md:table-cell" title={formatDateTime(i.last_seen_at)}>
                      {formatRelative(i.last_seen_at)}
                    </TableCell>
                    <TableCell className="tabular hidden text-right sm:table-cell">{formatNumber(i.occurrences)}</TableCell>
                    <TableCell className="hidden sm:table-cell">
                      <IncidentStatusChip status={i.status} />
                    </TableCell>
                    <TableCell className="text-faint">
                      <ChevronRightIcon className="size-4" aria-hidden />
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        )}
      </Surface>
      {rows.length > 0 && <p className="mt-3 text-xs text-muted-foreground">{formatNumber(rows.length)} incidents. Scans counts the scans that showed each problem.</p>}
    </>
  );
}
