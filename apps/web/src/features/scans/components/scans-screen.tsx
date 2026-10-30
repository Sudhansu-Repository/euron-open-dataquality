"use client";

import Link from "next/link";
import * as React from "react";

import { PageHeader } from "@/components/page-header";
import { Surface } from "@/components/surface";
import { Button, buttonVariants } from "@/components/ui/button";
import { SimpleSelect } from "@/components/ui/select";
import { useDatasets } from "@/features/datasets/api";
import { useCurrentProject } from "@/features/projects/api";

import { useScanPages } from "../api";
import { NoScans, ScanList } from "./scan-list";

type Status = "queued" | "running" | "succeeded" | "failed" | "cancelled";
const STATUS_OPTIONS: { value: "" | Status; label: string }[] = [
  { value: "", label: "Any status" },
  { value: "running", label: "Running" },
  { value: "queued", label: "Queued" },
  { value: "succeeded", label: "Done" },
  { value: "failed", label: "Failed" },
  { value: "cancelled", label: "Cancelled" },
];

export function ScansScreen() {
  const { pid } = useCurrentProject();
  const [status, setStatus] = React.useState<"" | Status>("");
  const [datasetId, setDatasetId] = React.useState("");
  const datasets = useDatasets(pid);
  const q = useScanPages(pid, { status: status || undefined, dataset_id: datasetId || undefined, limit: 50 });
  const filtered = !!status || !!datasetId;

  const datasetOptions = React.useMemo(
    () => [{ value: "all", label: "All datasets" }, ...(datasets.data ?? []).map((d) => ({ value: d.id, label: d.name }))],
    [datasets.data],
  );

  return (
    <>
      <PageHeader
        title="Scans"
        description="Every run of a dataset's checks, newest first. Running scans update live; open one for its results and failing rows."
      />
      <div className="mb-3 flex flex-col gap-2 sm:flex-row sm:items-center">
        <SimpleSelect
          aria-label="Filter by dataset"
          value={datasetId || "all"}
          onValueChange={(v) => setDatasetId(v === "all" ? "" : v)}
          options={datasetOptions}
          className="sm:w-60"
          size="sm"
        />
        <SimpleSelect
          aria-label="Filter by status"
          value={status || "all"}
          onValueChange={(v) => setStatus(v === "all" ? "" : (v as Status))}
          options={STATUS_OPTIONS.map((o) => ({ value: o.value || "all", label: o.label }))}
          className="sm:w-44"
          size="sm"
        />
        {filtered && (
          <Button
            variant="subtle"
            size="sm"
            onClick={() => {
              setStatus("");
              setDatasetId("");
            }}
          >
            Clear filters
          </Button>
        )}
      </div>
      <Surface className="overflow-hidden">
        <ScanList
          pid={pid}
          q={q}
          empty={
            filtered ? (
              <NoScans
                title="No scans match these filters"
                description="Try another status or dataset, or clear the filters to see every scan."
                action={
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      setStatus("");
                      setDatasetId("");
                    }}
                  >
                    Clear filters
                  </Button>
                }
              />
            ) : (
              <NoScans
                title="No scans yet"
                description="A scan reads a dataset, runs its checks and scores it. Run one from a dataset, or give a dataset a schedule."
                action={
                  <Link href={`/projects/${pid}/datasets`} className={buttonVariants({ size: "sm" })}>
                    Go to datasets
                  </Link>
                }
              />
            )
          }
        />
      </Surface>
    </>
  );
}
