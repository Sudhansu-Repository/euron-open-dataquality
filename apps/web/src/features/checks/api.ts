"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";
import type { CheckIn, CheckUpdate } from "@/lib/api/types";
import { qk, STALE } from "@/lib/query-keys";

const d = (pid: string, did: string) => ({ params: { path: { project_id: pid, dataset_id: did } } });

export function useChecks(pid: string, did: string) {
  return useQuery({
    queryKey: qk.checks(pid, did),
    queryFn: () => unwrap(api.GET("/api/v1/projects/{project_id}/datasets/{dataset_id}/checks", d(pid, did))),
    staleTime: STALE.list,
  });
}

function useInvalidateChecks(pid: string, did: string) {
  const client = useQueryClient();
  return () => {
    void client.invalidateQueries({ queryKey: qk.checks(pid, did) });
    void client.invalidateQueries({ queryKey: qk.suggestions(pid, did) });
    void client.invalidateQueries({ queryKey: qk.dataset(pid, did) });
  };
}

export function useCreateCheck(pid: string, did: string) {
  const done = useInvalidateChecks(pid, did);
  return useMutation({
    mutationFn: (body: CheckIn) => unwrap(api.POST("/api/v1/projects/{project_id}/datasets/{dataset_id}/checks", { ...d(pid, did), body })),
    onSuccess: done,
  });
}

/** Accept several checks at once (suggestions). */
export function useBulkCreateChecks(pid: string, did: string) {
  const done = useInvalidateChecks(pid, did);
  return useMutation({
    mutationFn: ({ checks, origin }: { checks: CheckIn[]; origin: "manual" | "suggested" | "ai" | "yaml" }) =>
      unwrap(api.POST("/api/v1/projects/{project_id}/datasets/{dataset_id}/checks/bulk", { ...d(pid, did), body: { checks, origin } })),
    onSuccess: done,
  });
}

export function useUpdateCheck(pid: string, did: string) {
  const done = useInvalidateChecks(pid, did);
  return useMutation({
    mutationFn: ({ checkId, body }: { checkId: string; body: CheckUpdate }) =>
      unwrap(api.PATCH("/api/v1/projects/{project_id}/datasets/{dataset_id}/checks/{check_id}", { params: { path: { project_id: pid, dataset_id: did, check_id: checkId } }, body })),
    onSuccess: done,
  });
}

export function useDeleteCheck(pid: string, did: string) {
  const done = useInvalidateChecks(pid, did);
  return useMutation({
    mutationFn: (checkId: string) =>
      unwrap(api.DELETE("/api/v1/projects/{project_id}/datasets/{dataset_id}/checks/{check_id}", { params: { path: { project_id: pid, dataset_id: did, check_id: checkId } } })),
    onSuccess: done,
  });
}

export function useApplyYaml(pid: string, did: string) {
  const done = useInvalidateChecks(pid, did);
  return useMutation({
    mutationFn: (body: { yaml: string; prune: boolean }) =>
      unwrap(api.PUT("/api/v1/projects/{project_id}/datasets/{dataset_id}/checks/yaml", { ...d(pid, did), body })),
    onSuccess: done,
  });
}

/** Plain language to a proposed check (optional AI; nothing is saved). */
export function useDraftCheck(pid: string, did: string) {
  return useMutation({
    mutationFn: (prompt: string) =>
      unwrap(api.POST("/api/v1/projects/{project_id}/datasets/{dataset_id}/checks/draft", { ...d(pid, did), body: { prompt } })),
  });
}
