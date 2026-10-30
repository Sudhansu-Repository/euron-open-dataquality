"use client";

import { useRouter } from "next/navigation";
import { toast } from "sonner";

import { useRunScan } from "@/features/scans/api";
import { errorMessage } from "@/lib/api/errors";

/** Start a scan and go to its live page. */
export function useScanAndOpen(pid: string) {
  const router = useRouter();
  const run = useRunScan(pid);
  const start = (datasetId: string, profile?: boolean) =>
    run.mutate(
      { datasetId, profile },
      {
        onSuccess: (scan) => router.push(`/projects/${pid}/scans/${scan.id}`),
        onError: (err) => toast.error(errorMessage(err)),
      },
    );
  return { start, pending: run.isPending };
}
