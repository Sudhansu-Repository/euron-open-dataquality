"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "next/navigation";

import { api, unwrap } from "@/lib/api/client";
import type { ApiKey, Member, Project, ProjectCreate, ProjectRole, ProjectUpdate, Scope } from "@/lib/api/types";
import { qk, STALE } from "@/lib/query-keys";
import { can } from "@/lib/roles";

const p = (pid: string) => ({ params: { path: { project_id: pid } } });

/** The project id from the URL (/projects/[pid]/...). */
export function useProjectId(): string {
  const params = useParams<{ pid: string }>();
  return params.pid;
}

export function useProjects() {
  return useQuery({ queryKey: qk.projects, queryFn: () => unwrap(api.GET("/api/v1/projects")), staleTime: STALE.list });
}

export function useProject(pid: string) {
  return useQuery({
    queryKey: qk.project(pid),
    queryFn: () => unwrap(api.GET("/api/v1/projects/{project_id}", p(pid))),
    staleTime: STALE.config,
  });
}

/** The current project and what the signed-in person may do in it. */
export function useCurrentProject(): {
  pid: string;
  project: Project | undefined;
  role: ProjectRole | undefined;
  canEdit: boolean;
  canOwn: boolean;
  query: ReturnType<typeof useProject>;
} {
  const pid = useProjectId();
  const query = useProject(pid);
  const role = query.data?.role;
  return { pid, project: query.data, role, canEdit: can(role, "editor"), canOwn: can(role, "owner"), query };
}

export function useCreateProject() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: ProjectCreate) => unwrap(api.POST("/api/v1/projects", { body })),
    onSuccess: () => client.invalidateQueries({ queryKey: qk.projects }),
  });
}

export function useUpdateProject(pid: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: ProjectUpdate) => unwrap(api.PATCH("/api/v1/projects/{project_id}", { ...p(pid), body })),
    onSuccess: (data) => {
      client.setQueryData(qk.project(pid), data);
      void client.invalidateQueries({ queryKey: qk.projects });
    },
  });
}

export function useDeleteProject(pid: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => unwrap(api.DELETE("/api/v1/projects/{project_id}", p(pid))),
    onSuccess: () => {
      client.removeQueries({ queryKey: qk.project(pid) });
      void client.invalidateQueries({ queryKey: qk.projects });
    },
  });
}

export function useMembers(pid: string) {
  return useQuery<Member[]>({
    queryKey: qk.members(pid),
    queryFn: () => unwrap(api.GET("/api/v1/projects/{project_id}/members", p(pid))),
    staleTime: STALE.list,
  });
}

export function useAddMember(pid: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { email: string; role: ProjectRole }) =>
      unwrap(api.POST("/api/v1/projects/{project_id}/members", { ...p(pid), body })),
    onSuccess: () => client.invalidateQueries({ queryKey: qk.members(pid) }),
  });
}

export function useUpdateMember(pid: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ userId, role }: { userId: string; role: ProjectRole }) =>
      unwrap(api.PATCH("/api/v1/projects/{project_id}/members/{user_id}", { params: { path: { project_id: pid, user_id: userId } }, body: { role } })),
    onSuccess: () => client.invalidateQueries({ queryKey: qk.members(pid) }),
  });
}

export function useRemoveMember(pid: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (userId: string) =>
      unwrap(api.DELETE("/api/v1/projects/{project_id}/members/{user_id}", { params: { path: { project_id: pid, user_id: userId } } })),
    onSuccess: () => client.invalidateQueries({ queryKey: qk.members(pid) }),
  });
}

export function useApiKeys(pid: string, enabled = true) {
  return useQuery<ApiKey[]>({
    queryKey: qk.apiKeys(pid),
    queryFn: () => unwrap(api.GET("/api/v1/projects/{project_id}/api-keys", p(pid))),
    staleTime: STALE.list,
    enabled,
  });
}

export function useCreateApiKey(pid: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { name: string; scopes: Scope[] }) =>
      unwrap(api.POST("/api/v1/projects/{project_id}/api-keys", { ...p(pid), body })),
    onSuccess: () => client.invalidateQueries({ queryKey: qk.apiKeys(pid) }),
  });
}

export function useRevokeApiKey(pid: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (keyId: string) =>
      unwrap(api.DELETE("/api/v1/projects/{project_id}/api-keys/{key_id}", { params: { path: { project_id: pid, key_id: keyId } } })),
    onSuccess: () => client.invalidateQueries({ queryKey: qk.apiKeys(pid) }),
  });
}
