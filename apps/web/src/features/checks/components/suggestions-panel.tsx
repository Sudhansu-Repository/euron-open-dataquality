"use client";

import { CheckIcon, ChevronDownIcon, SparklesIcon, Loader2Icon } from "lucide-react";
import * as React from "react";
import { toast } from "sonner";

import { Surface } from "@/components/surface";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useSuggestions } from "@/features/datasets/api";
import { useActiveScan } from "@/features/datasets/use-active-scan";
import { errorMessage } from "@/lib/api/errors";
import type { CheckIn, Dataset, Severity, Suggestion } from "@/lib/api/types";
import { cn } from "@/lib/cn";
import { checkTypeLabel } from "@/lib/quality";

import { useBulkCreateChecks } from "../api";
import { describeParams } from "../params";

function toCheckIn(s: Suggestion): CheckIn {
  return { type: s.type as CheckIn["type"], column: s.column, params: s.params, severity: (s.severity === "warn" ? "warn" : "error") as Severity };
}

/**
 * Checks proposed from the latest profile. New ones start selected; ones that already
 * exist are shown as added so the list explains itself.
 */
export function SuggestionsPanel({ pid, d }: { pid: string; d: Dataset }) {
  const q = useSuggestions(pid, d.id, !!d.last_scan_id);
  const { active: profiling } = useActiveScan(pid, d.id);
  const bulk = useBulkCreateChecks(pid, d.id);
  const items = React.useMemo(() => q.data ?? [], [q.data]);
  const fresh = items.filter((s) => !s.exists);
  const [picked, setPicked] = React.useState<Set<string>>(new Set());
  const [open, setOpen] = React.useState(true);
  const [showAdded, setShowAdded] = React.useState(false);
  const seeded = React.useRef("");

  // Select every new suggestion once per distinct list.
  React.useEffect(() => {
    const sig = fresh.map((s) => s.key).join("|");
    if (sig && sig !== seeded.current) {
      seeded.current = sig;
      setPicked(new Set(fresh.map((s) => s.key)));
    }
  }, [fresh]);

  if (!d.last_scan_id && profiling) {
    return (
      <div className="flex items-center gap-3 rounded-[14px] bg-primary-soft px-4 py-3 text-[13px] text-primary" role="status">
        <Loader2Icon className="size-4 shrink-0 animate-spin" />
        The first scan is profiling this dataset. Suggested checks appear here when it finishes.
      </div>
    );
  }
  if (!d.last_scan_id || q.isError) return null;
  if (q.isPending) return <Skeleton className="h-16 rounded-[14px]" />;
  if (!items.length) return null;

  const toggle = (k: string) =>
    setPicked((prev) => {
      const next = new Set(prev);
      if (next.has(k)) next.delete(k);
      else next.add(k);
      return next;
    });

  function addSelected() {
    const chosen = fresh.filter((s) => picked.has(s.key));
    bulk.mutate(
      { checks: chosen.map(toCheckIn), origin: "suggested" },
      {
        onSuccess: (r) => {
          toast.success(`${r.created} check${r.created === 1 ? "" : "s"} added. They run on the next scan.`);
          setPicked(new Set());
        },
        onError: (err) => toast.error(errorMessage(err)),
      },
    );
  }

  const shown = showAdded ? items : fresh;

  return (
    <Surface className="overflow-hidden">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-3 px-5 py-3.5 text-left focus-visible:bg-muted/50 focus-visible:outline-none"
      >
        <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-primary-soft text-primary">
          <SparklesIcon className="size-4" />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block text-[14px] font-semibold">Suggested checks</span>
          <span className="block text-xs text-muted-foreground">
            {fresh.length ? `${fresh.length} new from the latest profile` : "Every suggestion from the latest profile is already added"}
          </span>
        </span>
        <ChevronDownIcon className={cn("size-4 text-subtle transition-transform", open && "rotate-180")} />
      </button>
      {open && (
        <>
          {shown.length > 0 && (
            <ul className="max-h-[360px] overflow-y-auto border-t border-hairline">
              {shown.map((s) => {
                const params = describeParams(s.type, s.params);
                const id = `sg-${s.key}`;
                return (
                  <li key={s.key} className="border-b border-hairline last:border-0">
                    <label htmlFor={id} className={cn("flex items-start gap-3 px-5 py-2.5", s.exists ? "opacity-60" : "cursor-pointer hover:bg-muted/50")}>
                      {s.exists ? (
                        <span className="mt-0.5 flex size-4 shrink-0 items-center justify-center rounded bg-pass-soft text-pass" aria-label="Already added">
                          <CheckIcon className="size-3" />
                        </span>
                      ) : (
                        <input id={id} type="checkbox" checked={picked.has(s.key)} onChange={() => toggle(s.key)} className="mt-0.5 size-4 shrink-0 accent-[var(--primary)]" />
                      )}
                      <span className="min-w-0 flex-1">
                        <span className="flex flex-wrap items-baseline gap-x-2 text-[13px]">
                          <span className="font-medium">{checkTypeLabel(s.type)}</span>
                          {s.column && <span className="font-mono text-[12px]">{s.column}</span>}
                          {params && <span className="text-muted-foreground">{params}</span>}
                          {s.severity === "warn" && <span className="text-[11px] text-warn">warning</span>}
                          {s.exists && <span className="text-[11px] text-subtle">already added</span>}
                        </span>
                        <span className="mt-0.5 block text-xs text-muted-foreground">{s.reason}</span>
                      </span>
                    </label>
                  </li>
                );
              })}
            </ul>
          )}
          <div className="flex flex-wrap items-center justify-between gap-2 bg-muted/40 px-5 py-3">
            <div className="flex flex-wrap gap-1">
              {fresh.length > 0 && (
                <Button variant="subtle" size="xs" onClick={() => setPicked(picked.size === fresh.length ? new Set() : new Set(fresh.map((s) => s.key)))}>
                  {picked.size === fresh.length ? "Select none" : "Select all"}
                </Button>
              )}
              {items.length > fresh.length && (
                <Button variant="subtle" size="xs" onClick={() => setShowAdded((v) => !v)}>
                  {showAdded ? "Hide added" : `Show ${items.length - fresh.length} already added`}
                </Button>
              )}
            </div>
            {fresh.length > 0 && (
              <Button size="sm" onClick={addSelected} disabled={!picked.size || bulk.isPending}>
                {bulk.isPending ? "Adding..." : `Add selected (${picked.size})`}
              </Button>
            )}
          </div>
        </>
      )}
    </Surface>
  );
}
