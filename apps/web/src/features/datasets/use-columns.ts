"use client";

import { useScan } from "@/features/scans/api";
import type { Dataset } from "@/lib/api/types";

import { useProfile } from "./api";

export interface DatasetColumn {
  name: string;
  type: string;
}

/**
 * A dataset's columns as the latest scan saw them, falling back to the latest profile.
 * Empty until the dataset has been scanned once.
 */
export function useDatasetColumns(pid: string, d: Dataset | undefined): { columns: DatasetColumn[]; loading: boolean } {
  const sid = d?.last_scan_id ?? "";
  const scan = useScan(pid, sid, !!sid);
  const fromScan = scan.data?.columns ?? [];
  const profile = useProfile(pid, d?.id ?? "", !!d && !!sid && scan.isSuccess && fromScan.length === 0);
  if (fromScan.length) return { columns: fromScan.map((c) => ({ name: c.name, type: c.type })), loading: false };
  const fromProfile = profile.data?.columns.map((c) => ({ name: c.name, type: c.logical })) ?? [];
  return { columns: fromProfile, loading: !!sid && (scan.isPending || profile.isFetching) };
}
