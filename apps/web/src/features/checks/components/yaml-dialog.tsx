"use client";

import { DownloadIcon, UploadIcon } from "lucide-react";
import * as React from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Dialog, DialogBody, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/input";
import { FieldError } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { reportUrls } from "@/features/scans/api";
import { download } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";
import type { BulkResult, Dataset } from "@/lib/api/types";

import { useApplyYaml } from "../api";

/** Checks as code: export the dataset's checks as YAML, or apply a YAML file. */
export function YamlDialog({ pid, d, open, onOpenChange, canEdit }: { pid: string; d: Dataset; open: boolean; onOpenChange: (o: boolean) => void; canEdit: boolean }) {
  const [text, setText] = React.useState("");
  const [prune, setPrune] = React.useState(false);
  const [error, setError] = React.useState("");
  const [result, setResult] = React.useState<BulkResult | null>(null);
  const [exporting, setExporting] = React.useState(false);
  const apply = useApplyYaml(pid, d.id);
  const fileRef = React.useRef<HTMLInputElement>(null);

  async function exportYaml() {
    setExporting(true);
    try {
      await download(reportUrls.yaml(pid, d.id), `${d.slug}.dataquality.yaml`);
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setExporting(false);
    }
  }

  async function onFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    if (file.size > 1_000_000) {
      setError("That file is larger than 1 MB. A checks file is usually a few KB.");
      return;
    }
    setText(await file.text());
    setError("");
    setResult(null);
  }

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!text.trim()) return;
    setError("");
    apply.mutate(
      { yaml: text, prune },
      {
        onSuccess: (r) => {
          setResult(r);
          toast.success("Checks applied from YAML");
        },
        onError: (err) => setError(errorMessage(err)),
      },
    );
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        onOpenChange(o);
        if (!o) {
          setResult(null);
          setError("");
        }
      }}
    >
      <DialogContent className="max-w-2xl">
        <form onSubmit={submit} className="flex min-h-0 flex-1 flex-col">
          <DialogHeader>
            <DialogTitle>Checks as code</DialogTitle>
            <DialogDescription>Keep this dataset&apos;s checks in a YAML file in your repository, review changes like code, and apply them here or from CI.</DialogDescription>
          </DialogHeader>
          <DialogBody className="space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl bg-muted/60 px-4 py-3">
              <div>
                <div className="text-[13px] font-medium">Export</div>
                <div className="text-xs text-muted-foreground">Every check of {d.name}, as one YAML file.</div>
              </div>
              <Button type="button" variant="outline" size="sm" onClick={() => void exportYaml()} disabled={exporting}>
                <DownloadIcon />
                {exporting ? "Preparing..." : "Download YAML"}
              </Button>
            </div>
            {canEdit && (
              <>
                <div className="flex items-center justify-between gap-3">
                  <div className="text-[13px] font-medium">Import</div>
                  <input ref={fileRef} type="file" accept=".yaml,.yml,text/yaml" className="hidden" onChange={(e) => void onFile(e)} />
                  <Button type="button" variant="subtle" size="xs" onClick={() => fileRef.current?.click()}>
                    <UploadIcon />
                    Load a file
                  </Button>
                </div>
                <Textarea
                  aria-label="Checks YAML"
                  value={text}
                  onChange={(e) => {
                    setText(e.target.value);
                    setResult(null);
                  }}
                  rows={10}
                  spellCheck={false}
                  className="font-mono text-[12px] leading-relaxed"
                  placeholder={"version: 1\ndataset: customers\nchecks:\n- name: Email present\n  type: not_null\n  column: email"}
                />
                <div className="flex items-start justify-between gap-4 rounded-lg bg-muted/50 px-3.5 py-2.5">
                  <div>
                    <label htmlFor="yaml-prune" className="text-[13px] font-medium">
                      Remove checks missing from the file
                    </label>
                    <p className="mt-0.5 text-xs text-muted-foreground">Off: checks only in the app are kept. On: the file becomes the full list.</p>
                  </div>
                  <Switch id="yaml-prune" checked={prune} onCheckedChange={setPrune} />
                </div>
                {error && <FieldError className="rounded-lg bg-danger-soft px-3 py-2 text-[13px] whitespace-pre-wrap">{error}</FieldError>}
                {result && (
                  <div className="grid grid-cols-3 gap-2" role="status">
                    {[
                      { label: "Created", n: result.created },
                      { label: "Updated", n: result.updated ?? 0 },
                      { label: "Removed", n: result.removed?.length ?? 0 },
                    ].map((x) => (
                      <div key={x.label} className="rounded-lg bg-pass-soft px-3 py-2">
                        <div className="text-[18px] font-semibold tabular">{x.n}</div>
                        <div className="text-xs text-muted-foreground">{x.label}</div>
                      </div>
                    ))}
                    {!!result.removed?.length && <p className="col-span-3 text-xs text-muted-foreground">Removed: {result.removed.join(", ")}</p>}
                    {!!result.skipped?.length && <p className="col-span-3 text-xs text-muted-foreground">Skipped: {result.skipped.join(", ")}</p>}
                  </div>
                )}
              </>
            )}
          </DialogBody>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
              Close
            </Button>
            {canEdit && (
              <Button type="submit" disabled={!text.trim() || apply.isPending}>
                {apply.isPending ? "Applying..." : "Apply YAML"}
              </Button>
            )}
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
