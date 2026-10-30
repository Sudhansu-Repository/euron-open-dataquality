"use client";

import { useQuery } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";
import { qk, STALE } from "@/lib/query-keys";

/** The project dashboard (cached 30 s on the server, refreshed after every scan). */
export function useDashboard(pid: string) {
  return useQuery({
    queryKey: qk.dashboard(pid),
    queryFn: () => unwrap(api.GET("/api/v1/projects/{project_id}/dashboard", { params: { path: { project_id: pid } } })),
    staleTime: STALE.list,
    refetchInterval: 60_000,
  });
}
