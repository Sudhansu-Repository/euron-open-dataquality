"use client";

import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";
import type { ScanDetail } from "@/lib/api/types";
import { qk, STALE } from "@/lib/query-keys";

const ACTIVE = new Set(["queued", "running"]);

export function useScans(pid: string, filters: { dataset_id?: string; status?: "queued" | "running" | "succeeded" | "failed" | "cancelled"; cursor?: string; limit?: number }) {
  return useQuery({
    queryKey: qk.scans(pid, filters),
    queryFn: () => unwrap(api.GET("/api/v1/projects/{project_id}/scans", { params: { path: { project_id: pid }, query: filters } })),
    staleTime: STALE.live,
    // Keep a list with running scans fresh until they finish.
    refetchInterval: (q) => (q.state.data?.items.some((s) => ACTIVE.has(s.status)) ? 2_000 : false),
  });
}

type ScanStatus = "queued" | "running" | "succeeded" | "failed" | "cancelled";

/**
 * Scans page by page (keyset: each page passes the previous next_cursor). Polls while any
 * loaded scan is queued or running, so a list with live scans updates itself.
 */
export function useScanPages(pid: string, filters: { dataset_id?: string; status?: ScanStatus; limit?: number }) {
  return useInfiniteQuery({
    queryKey: [...qk.scans(pid, filters), "pages"],
    queryFn: ({ pageParam }) =>
      unwrap(api.GET("/api/v1/projects/{project_id}/scans", { params: { path: { project_id: pid }, query: { ...filters, cursor: pageParam } } })),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    staleTime: STALE.live,
    refetchInterval: (q) => (q.state.data?.pages.some((p) => p.items.some((s) => ACTIVE.has(s.status))) ? 2_500 : false),
  });
}

/** A scan with its results; polls while it is queued or running. */
export function useScan(pid: string, sid: string, enabled = true) {
  return useQuery({
    queryKey: qk.scan(pid, sid),
    queryFn: () => unwrap(api.GET("/api/v1/projects/{project_id}/scans/{scan_id}", { params: { path: { project_id: pid, scan_id: sid } } })),
    staleTime: STALE.live,
    enabled: enabled && !!sid,
    refetchInterval: (q) => (q.state.data && ACTIVE.has(q.state.data.status) ? 1_500 : false),
  });
}

/** Start a scan now. Returns at once (queued); the scan page follows it live. */
export function useRunScan(pid: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ datasetId, profile }: { datasetId: string; profile?: boolean }): Promise<ScanDetail> =>
      unwrap(api.POST("/api/v1/projects/{project_id}/datasets/{dataset_id}/scans", { params: { path: { project_id: pid, dataset_id: datasetId }, query: { wait: 0 } }, body: profile === undefined ? {} : { profile } })),
    onSuccess: (scan) => {
      client.setQueryData(qk.scan(pid, scan.id), scan);
      void client.invalidateQueries({ queryKey: qk.scansAll(pid) });
      void client.invalidateQueries({ queryKey: qk.datasets(pid) });
    },
  });
}

export function useCancelScan(pid: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (sid: string) => unwrap(api.POST("/api/v1/projects/{project_id}/scans/{scan_id}/cancel", { params: { path: { project_id: pid, scan_id: sid } } })),
    onSuccess: (_, sid) => {
      void client.invalidateQueries({ queryKey: qk.scan(pid, sid) });
      void client.invalidateQueries({ queryKey: qk.scansAll(pid) });
    },
  });
}

export function useAnomalies(pid: string, datasetId?: string) {
  return useQuery({
    queryKey: qk.anomalies(pid, datasetId),
    queryFn: () => unwrap(api.GET("/api/v1/projects/{project_id}/anomalies", { params: { path: { project_id: pid }, query: { dataset_id: datasetId, limit: 100 } } })),
    staleTime: STALE.list,
  });
}

/** Report downloads (use lib/api/client download()). */
export const reportUrls = {
  csv: (pid: string, sid: string) => `/api/v1/projects/${pid}/scans/${sid}/report.csv`,
  pdf: (pid: string, sid: string) => `/api/v1/projects/${pid}/scans/${sid}/report.pdf`,
  history: (pid: string, did: string) => `/api/v1/projects/${pid}/datasets/${did}/history.csv`,
  summary: (pid: string) => `/api/v1/projects/${pid}/report.pdf`,
  yaml: (pid: string, did: string) => `/api/v1/projects/${pid}/datasets/${did}/checks/yaml`,
};
