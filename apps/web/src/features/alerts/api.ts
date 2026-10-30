"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";
import type { ChannelIn, RuleIn } from "@/lib/api/types";
import { qk, STALE } from "@/lib/query-keys";

const p = (pid: string) => ({ params: { path: { project_id: pid } } });

export function useChannels(pid: string) {
  return useQuery({ queryKey: qk.channels(pid), queryFn: () => unwrap(api.GET("/api/v1/projects/{project_id}/alert-channels", p(pid))), staleTime: STALE.list });
}

export function useCreateChannel(pid: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: ChannelIn) => unwrap(api.POST("/api/v1/projects/{project_id}/alert-channels", { ...p(pid), body })),
    onSuccess: () => client.invalidateQueries({ queryKey: qk.channels(pid) }),
  });
}

export function useUpdateChannel(pid: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: { name?: string; recipients?: string[]; url?: string; enabled?: boolean } }) =>
      unwrap(api.PATCH("/api/v1/projects/{project_id}/alert-channels/{channel_id}", { params: { path: { project_id: pid, channel_id: id } }, body })),
    onSuccess: () => client.invalidateQueries({ queryKey: qk.channels(pid) }),
  });
}

export function useDeleteChannel(pid: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => unwrap(api.DELETE("/api/v1/projects/{project_id}/alert-channels/{channel_id}", { params: { path: { project_id: pid, channel_id: id } } })),
    onSuccess: () => client.invalidateQueries({ queryKey: qk.channels(pid) }),
  });
}

export function useTestChannel(pid: string) {
  return useMutation({
    mutationFn: (id: string) => unwrap(api.POST("/api/v1/projects/{project_id}/alert-channels/{channel_id}/test", { params: { path: { project_id: pid, channel_id: id } } })),
  });
}

export function useRules(pid: string) {
  return useQuery({ queryKey: qk.rules(pid), queryFn: () => unwrap(api.GET("/api/v1/projects/{project_id}/alert-rules", p(pid))), staleTime: STALE.list });
}

export function useCreateRule(pid: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: RuleIn) => unwrap(api.POST("/api/v1/projects/{project_id}/alert-rules", { ...p(pid), body })),
    onSuccess: () => client.invalidateQueries({ queryKey: qk.rules(pid) }),
  });
}

export function useUpdateRule(pid: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: Partial<RuleIn> }) =>
      unwrap(api.PATCH("/api/v1/projects/{project_id}/alert-rules/{rule_id}", { params: { path: { project_id: pid, rule_id: id } }, body })),
    onSuccess: () => client.invalidateQueries({ queryKey: qk.rules(pid) }),
  });
}

export function useDeleteRule(pid: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => unwrap(api.DELETE("/api/v1/projects/{project_id}/alert-rules/{rule_id}", { params: { path: { project_id: pid, rule_id: id } } })),
    onSuccess: () => client.invalidateQueries({ queryKey: qk.rules(pid) }),
  });
}

export function useIncidents(pid: string, filters: { status?: "active" | "open" | "acknowledged" | "resolved"; dataset_id?: string; limit?: number }) {
  return useQuery({
    queryKey: qk.incidents(pid, filters),
    queryFn: () => unwrap(api.GET("/api/v1/projects/{project_id}/incidents", { params: { path: { project_id: pid }, query: filters } })),
    staleTime: STALE.list,
  });
}

export function useIncident(pid: string, iid: string) {
  return useQuery({
    queryKey: qk.incident(pid, iid),
    queryFn: () => unwrap(api.GET("/api/v1/projects/{project_id}/incidents/{incident_id}", { params: { path: { project_id: pid, incident_id: iid } } })),
    staleTime: STALE.live,
    // Follow notifications until they are delivered (or given up on).
    refetchInterval: (q) => (q.state.data?.notifications?.some((n) => n.status === "pending") ? 3_000 : false),
  });
}

function useIncidentAction(pid: string, action: "acknowledge" | "resolve") {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (iid: string) =>
      action === "acknowledge"
        ? unwrap(api.POST("/api/v1/projects/{project_id}/incidents/{incident_id}/acknowledge", { params: { path: { project_id: pid, incident_id: iid } } }))
        : unwrap(api.POST("/api/v1/projects/{project_id}/incidents/{incident_id}/resolve", { params: { path: { project_id: pid, incident_id: iid } } })),
    onSuccess: (data) => {
      client.setQueryData(qk.incident(pid, data.id), data);
      void client.invalidateQueries({ queryKey: qk.incidentsAll(pid) });
      void client.invalidateQueries({ queryKey: qk.dashboard(pid) });
    },
  });
}

export const useAcknowledgeIncident = (pid: string) => useIncidentAction(pid, "acknowledge");
export const useResolveIncident = (pid: string) => useIncidentAction(pid, "resolve");

/** Optional AI explanation of an incident. */
export function useExplainIncident(pid: string) {
  return useMutation({
    mutationFn: (iid: string) => unwrap(api.POST("/api/v1/projects/{project_id}/incidents/{incident_id}/explain", { params: { path: { project_id: pid, incident_id: iid } } })),
  });
}
