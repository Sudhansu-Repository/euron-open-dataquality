"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, rawJson, unwrap } from "@/lib/api/client";
import type { Connection, ConnectionTest, ConnectionUpdate, ServerConnection } from "@/lib/api/types";
import { qk, STALE } from "@/lib/query-keys";

const c = (pid: string, cid: string) => ({ params: { path: { project_id: pid, connection_id: cid } } });

export function useConnections(pid: string) {
  return useQuery({
    queryKey: qk.connections(pid),
    queryFn: () => unwrap(api.GET("/api/v1/projects/{project_id}/connections", { params: { path: { project_id: pid } } })),
    staleTime: STALE.list,
  });
}

export function useTables(pid: string, cid: string | undefined) {
  return useQuery({
    queryKey: qk.tables(pid, cid ?? ""),
    queryFn: () => unwrap(api.GET("/api/v1/projects/{project_id}/connections/{connection_id}/tables", c(pid, cid as string))),
    enabled: !!cid,
    staleTime: STALE.config,
    retry: false,
  });
}

export function useCreateConnection(pid: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: ServerConnection) => unwrap(api.POST("/api/v1/projects/{project_id}/connections", { params: { path: { project_id: pid } }, body })),
    onSuccess: () => client.invalidateQueries({ queryKey: qk.connections(pid) }),
  });
}

/** A SQLite database file (multipart). */
export function useCreateSqlite(pid: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ name, file }: { name: string; file: File }) => {
      const form = new FormData();
      form.set("name", name);
      form.set("file", file);
      return rawJson<Connection>("POST", `/api/v1/projects/${pid}/connections/sqlite`, form);
    },
    onSuccess: () => client.invalidateQueries({ queryKey: qk.connections(pid) }),
  });
}

export function useTestUnsaved(pid: string) {
  return useMutation({
    mutationFn: (body: ServerConnection) => unwrap(api.POST("/api/v1/projects/{project_id}/connections/test", { params: { path: { project_id: pid } }, body })),
  });
}

export function useTestConnection(pid: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (cid: string): Promise<ConnectionTest> => unwrap(api.POST("/api/v1/projects/{project_id}/connections/{connection_id}/test", c(pid, cid))),
    onSettled: () => client.invalidateQueries({ queryKey: qk.connections(pid) }),
  });
}

export function useUpdateConnection(pid: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ cid, body }: { cid: string; body: ConnectionUpdate }) =>
      unwrap(api.PATCH("/api/v1/projects/{project_id}/connections/{connection_id}", { ...c(pid, cid), body })),
    onSuccess: () => client.invalidateQueries({ queryKey: qk.connections(pid) }),
  });
}

export function useDeleteConnection(pid: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (cid: string) => unwrap(api.DELETE("/api/v1/projects/{project_id}/connections/{connection_id}", c(pid, cid))),
    onSuccess: () => client.invalidateQueries({ queryKey: qk.connections(pid) }),
  });
}
