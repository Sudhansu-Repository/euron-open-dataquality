"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, rawJson, unwrap } from "@/lib/api/client";
import type { Dataset, DatasetCreate, DatasetUpdate } from "@/lib/api/types";
import { qk, STALE } from "@/lib/query-keys";

const d = (pid: string, did: string) => ({ params: { path: { project_id: pid, dataset_id: did } } });

export function useDatasets(pid: string) {
  return useQuery({
    queryKey: qk.datasets(pid),
    queryFn: () => unwrap(api.GET("/api/v1/projects/{project_id}/datasets", { params: { path: { project_id: pid } } })),
    staleTime: STALE.list,
  });
}

export function useDataset(pid: string, did: string) {
  return useQuery({
    queryKey: qk.dataset(pid, did),
    queryFn: () => unwrap(api.GET("/api/v1/projects/{project_id}/datasets/{dataset_id}", d(pid, did))),
    staleTime: STALE.list,
  });
}

export function useProfile(pid: string, did: string, enabled = true) {
  return useQuery({
    queryKey: qk.profile(pid, did),
    queryFn: () => unwrap(api.GET("/api/v1/projects/{project_id}/datasets/{dataset_id}/profile", d(pid, did))),
    staleTime: STALE.config,
    retry: false,
    enabled,
  });
}

export function useSuggestions(pid: string, did: string, enabled = true) {
  return useQuery({
    queryKey: qk.suggestions(pid, did),
    queryFn: () => unwrap(api.GET("/api/v1/projects/{project_id}/datasets/{dataset_id}/suggestions", d(pid, did))),
    staleTime: STALE.config,
    retry: false,
    enabled,
  });
}

/** The first rows, read live from the source (so it is only fetched on demand). */
export function usePreview(pid: string, did: string, enabled: boolean) {
  return useQuery({
    queryKey: qk.preview(pid, did),
    queryFn: () => unwrap(api.GET("/api/v1/projects/{project_id}/datasets/{dataset_id}/preview", { params: { path: { project_id: pid, dataset_id: did }, query: { limit: 50 } } })),
    staleTime: STALE.config,
    retry: false,
    enabled,
  });
}

export function useFiles(pid: string, did: string, enabled = true) {
  return useQuery({
    queryKey: qk.files(pid, did),
    queryFn: () => unwrap(api.GET("/api/v1/projects/{project_id}/datasets/{dataset_id}/files", d(pid, did))),
    staleTime: STALE.list,
    enabled,
  });
}

type Metric = "row_count" | "score" | "dimension" | "check_failed_pct" | "null_rate" | "distinct" | "mean";

export function useMetrics(pid: string, did: string, metric: Metric, key?: string, days = 30) {
  return useQuery({
    queryKey: [...qk.metrics(pid, did, metric, key), days],
    queryFn: () =>
      unwrap(api.GET("/api/v1/projects/{project_id}/datasets/{dataset_id}/metrics", { params: { path: { project_id: pid, dataset_id: did }, query: { metric, key, days } } })),
    staleTime: STALE.list,
  });
}

export function useCreateDataset(pid: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: DatasetCreate) => unwrap(api.POST("/api/v1/projects/{project_id}/datasets", { params: { path: { project_id: pid } }, body })),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: qk.datasets(pid) });
      void client.invalidateQueries({ queryKey: qk.projects });
    },
  });
}

/** A new file dataset, or a new version of one when ``datasetId`` is given (multipart). */
export function useUploadFile(pid: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ file, name, sheet, delimiter, datasetId }: { file: File; name?: string; sheet?: string; delimiter?: string; datasetId?: string }) => {
      const form = new FormData();
      form.set("file", file);
      if (name) form.set("name", name);
      if (sheet) form.set("sheet", sheet);
      if (delimiter) form.set("delimiter", delimiter);
      const path = datasetId ? `/api/v1/projects/${pid}/datasets/${datasetId}/files` : `/api/v1/projects/${pid}/datasets/upload`;
      return rawJson<Dataset>("POST", path, form);
    },
    onSuccess: (data) => {
      client.setQueryData(qk.dataset(pid, data.id), data);
      void client.invalidateQueries({ queryKey: qk.datasets(pid) });
      void client.invalidateQueries({ queryKey: qk.files(pid, data.id) });
      void client.invalidateQueries({ queryKey: qk.projects });
    },
  });
}

export function useUpdateDataset(pid: string, did: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: DatasetUpdate) => unwrap(api.PATCH("/api/v1/projects/{project_id}/datasets/{dataset_id}", { ...d(pid, did), body })),
    onSuccess: (data) => {
      client.setQueryData(qk.dataset(pid, did), data);
      void client.invalidateQueries({ queryKey: qk.datasets(pid) });
    },
  });
}

export function useDeleteDataset(pid: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (did: string) => unwrap(api.DELETE("/api/v1/projects/{project_id}/datasets/{dataset_id}", d(pid, did))),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: qk.datasets(pid) });
      void client.invalidateQueries({ queryKey: qk.dashboard(pid) });
      void client.invalidateQueries({ queryKey: qk.projects });
    },
  });
}
