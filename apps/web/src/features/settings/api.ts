"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";
import type { SettingsUpdate } from "@/lib/api/types";
import { qk, STALE } from "@/lib/query-keys";

const KEY = ["org", "settings"] as const;

export function useOrgSettings() {
  return useQuery({ queryKey: KEY, queryFn: () => unwrap(api.GET("/api/v1/org/settings")), staleTime: STALE.config });
}

export function useUpdateOrgSettings() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: SettingsUpdate) => unwrap(api.PATCH("/api/v1/org/settings", { body })),
    onSuccess: (data) => {
      client.setQueryData(KEY, data);
      void client.invalidateQueries({ queryKey: qk.publicSettings });
    },
  });
}
