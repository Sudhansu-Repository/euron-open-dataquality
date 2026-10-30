"use client";

import { useRouter } from "next/navigation";
import { toast } from "sonner";

import { useRunScan } from "@/features/scans/api";
import { errorMessage } from "@/lib/api/errors";
import type { Dataset } from "@/lib/api/types";

/**
 * After a dataset is created: start its first scan with profiling, then open the
 * dataset on its checks tab, where the suggested checks show up when the scan is done.
 * A scan that cannot start still lands on the dataset, with the reason in a toast.
 */
export function useFirstScan(pid: string) {
  const run = useRunScan(pid);
  const router = useRouter();
  const go = (d: Dataset) => router.push(`/projects/${pid}/datasets/${d.id}?tab=checks`);

  function start(d: Dataset): Promise<void> {
    return new Promise((resolve) => {
      run.mutate(
        { datasetId: d.id, profile: true },
        {
          onSuccess: () => {
            toast.success(`${d.name} added. The first scan is profiling it now.`);
            go(d);
            resolve();
          },
          onError: (err) => {
            toast.error(`${d.name} was added, but the first scan did not start: ${errorMessage(err)}`);
            go(d);
            resolve();
          },
        },
      );
    });
  }

  return { start, isPending: run.isPending };
}
