"use client";

import { SparklesIcon, WandSparklesIcon } from "lucide-react";
import * as React from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Dialog, DialogBody, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/input";
import { FieldError } from "@/components/ui/label";
import { ApiError, errorMessage } from "@/lib/api/errors";
import type { Dataset, Draft } from "@/lib/api/types";
import { checkTypeLabel } from "@/lib/quality";

import { useBulkCreateChecks, useDraftCheck } from "../api";
import { type CheckForm, fromCheck } from "../form";
import { describeParams, describeTolerance } from "../params";

const EXAMPLES = ["Order totals are never negative", "Every email looks like an email address", "Data is no older than a day"];

/** Plain words to a proposed check (optional AI). Nothing is saved until the person adds it. */
export function DraftDialog({
  pid,
  d,
  open,
  onOpenChange,
  onEdit,
}: {
  pid: string;
  d: Dataset;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onEdit: (form: CheckForm) => void;
}) {
  const [prompt, setPrompt] = React.useState("");
  const [draft, setDraft] = React.useState<Draft | null>(null);
  const [error, setError] = React.useState<unknown>(null);
  const run = useDraftCheck(pid, d.id);
  const add = useBulkCreateChecks(pid, d.id);
  const disabled = error instanceof ApiError && error.code === "ai_disabled";

  function close(o: boolean) {
    onOpenChange(o);
    if (!o) {
      setDraft(null);
      setError(null);
    }
  }

  function ask(e: React.FormEvent) {
    e.preventDefault();
    if (!prompt.trim()) return;
    setError(null);
    setDraft(null);
    run.mutate(prompt.trim(), { onSuccess: setDraft, onError: setError });
  }

  function addDraft() {
    if (!draft) return;
    add.mutate(
      { checks: [draft.check], origin: "ai" },
      {
        onSuccess: () => {
          toast.success("Check added. It runs on the next scan.");
          setPrompt("");
          close(false);
        },
        onError: setError,
      },
    );
  }

  const c = draft?.check;
  const params = c ? describeParams(c.type, c.params ?? {}) : "";
  const tol = c ? describeTolerance(c.tolerance as Record<string, unknown> | undefined) : "";

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent className="max-w-xl">
        <form onSubmit={ask} className="flex min-h-0 flex-1 flex-col">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <WandSparklesIcon className="size-4 text-primary" />
              Describe a check
            </DialogTitle>
            <DialogDescription>Say what should be true about {d.name} in plain words. The assistant proposes a check; you review it before anything is saved.</DialogDescription>
          </DialogHeader>
          <DialogBody className="space-y-3">
            <Textarea
              aria-label="What should be true"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              rows={3}
              maxLength={1000}
              placeholder="Lifetime value is never negative and never above 10 lakh"
              autoFocus
            />
            {!prompt && (
              <div className="flex flex-wrap gap-1.5">
                {EXAMPLES.map((x) => (
                  <button key={x} type="button" onClick={() => setPrompt(x)} className="rounded-full bg-muted px-2.5 py-1 text-xs text-muted-foreground hover:bg-accent hover:text-foreground">
                    {x}
                  </button>
                ))}
              </div>
            )}
            {disabled ? <AiNote /> : error ? <FieldError className="rounded-lg bg-danger-soft px-3 py-2 text-[13px]">{errorMessage(error)}</FieldError> : null}
            {c && draft && (
              <div className="rounded-xl bg-primary-soft/60 p-4">
                <div className="flex items-center gap-1.5 text-[11px] font-semibold tracking-[0.04em] text-primary uppercase">
                  <SparklesIcon className="size-3.5" /> Proposed check
                </div>
                <div className="mt-2 text-[14px] font-semibold">{c.name || `${checkTypeLabel(c.type)}${c.column ? ` on ${c.column}` : ""}`}</div>
                <div className="mt-0.5 flex flex-wrap gap-x-1.5 text-[12.5px] text-muted-foreground">
                  <span className="font-medium text-foreground">{checkTypeLabel(c.type)}</span>
                  {c.column && <span className="font-mono">{c.column}</span>}
                  {params && <span>{params}</span>}
                  {tol && <span>· tolerates {tol}</span>}
                  <span>· {c.severity === "warn" ? "warning" : "error"}</span>
                </div>
                {draft.explanation && <p className="mt-2 text-[13px] leading-relaxed">{draft.explanation}</p>}
              </div>
            )}
          </DialogBody>
          <DialogFooter>
            {c ? (
              <>
                <Button type="button" variant="ghost" onClick={() => draft && onEdit(fromCheck({ ...draft.check, tolerance: draft.check.tolerance as Record<string, unknown> | undefined }))}>
                  Edit first
                </Button>
                <Button type="button" onClick={addDraft} disabled={add.isPending}>
                  {add.isPending ? "Adding..." : "Add this check"}
                </Button>
              </>
            ) : (
              <>
                <Button type="button" variant="ghost" onClick={() => close(false)}>
                  Cancel
                </Button>
                <Button type="submit" disabled={!prompt.trim() || run.isPending || disabled}>
                  {run.isPending ? "Thinking..." : "Propose a check"}
                </Button>
              </>
            )}
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function AiNote() {
  return (
    <p className="flex items-start gap-2 rounded-lg bg-muted/60 px-3 py-2.5 text-[13px] text-muted-foreground">
      <SparklesIcon className="mt-0.5 size-4 shrink-0 text-primary" />
      <span>
        The assistant is off on this instance. An admin can turn it on in Instance settings with any OpenAI-compatible endpoint. Until then, add checks with <b>Add check</b> or from
        the suggestions.
      </span>
    </p>
  );
}
