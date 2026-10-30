"use client";

import { useQueryClient } from "@tanstack/react-query";
import * as React from "react";

import { useScans } from "@/features/scans/api";
import { qk } from "@/lib/query-keys";

const ACTIVE = new Set(["queued", "running"]);

/**
 * Whether the dataset's newest scan is queued or running (the scan list polls while it
 * is), and a refresh of everything the scan changes once it ends: the dataset's score,
 * its profile, suggestions, checks, history and anomalies. A dataset only records a scan
 * when it finishes, so this is how a page learns that one is under way.
 */
export function useActiveScan(pid: string, did: string): { active: boolean; scanId: string | null } {
  const client = useQueryClient();
  const q = useScans(pid, { dataset_id: did, limit: 1 });
  const latest = q.data?.items[0];
  const active = !!latest && ACTIVE.has(latest.status);
  const was = React.useRef(active);
  React.useEffect(() => {
    if (was.current && !active) {
      for (const key of [qk.dataset(pid, did), qk.profile(pid, did), qk.suggestions(pid, did), qk.checks(pid, did), qk.anomalies(pid, did), qk.dashboard(pid), qk.datasets(pid)]) {
        void client.invalidateQueries({ queryKey: key });
      }
      void client.invalidateQueries({ queryKey: ["p", pid, "datasets", did, "metrics"] });
    }
    was.current = active;
  }, [active, client, pid, did]);
  return { active, scanId: latest?.id ?? null };
}
