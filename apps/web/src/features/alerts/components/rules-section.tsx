"use client";

import { BellIcon, CheckIcon, PencilIcon, PlusIcon, ShieldAlertIcon, Trash2Icon } from "lucide-react";
import * as React from "react";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { Segmented } from "@/components/segmented";
import { Surface, SurfaceHeader } from "@/components/surface";
import { TableSkeleton } from "@/components/table-skeleton";
import { Button } from "@/components/ui/button";
import { Chip } from "@/components/ui/chip";
import { Dialog, DialogBody, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Field, FieldError, Label } from "@/components/ui/label";
import { SimpleSelect } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { useDatasets } from "@/features/datasets/api";
import { errorMessage } from "@/lib/api/errors";
import type { Channel, Rule, RuleIn } from "@/lib/api/types";
import { cn } from "@/lib/cn";
import { formatPercent } from "@/lib/format";
import { RULE_KINDS, ruleKindLabel, type RuleKind } from "@/lib/quality";

import { useChannels, useCreateRule, useDeleteRule, useRules, useUpdateRule } from "../api";

import { CHANNEL_ICON } from "./channels-section";

type Severity = NonNullable<RuleIn["min_severity"]>;

/** One line saying what a rule watches. */
export function ruleSummary(r: Pick<Rule, "kind" | "min_severity" | "threshold">): string {
  if (r.kind === "check_failed") return r.min_severity === "warn" ? "Any check fails, warnings included" : "An error check fails";
  if (r.kind === "score_below") return `Score below ${formatPercent(r.threshold ?? 0)}`;
  return (RULE_KINDS[r.kind as RuleKind]?.description ?? r.kind).replace(/\.$/, "");
}

export function RulesSection({ pid, canEdit }: { pid: string; canEdit: boolean }) {
  const q = useRules(pid);
  const channels = useChannels(pid);
  const datasets = useDatasets(pid);
  const update = useUpdateRule(pid);
  const del = useDeleteRule(pid);
  const [editing, setEditing] = React.useState<Rule | "new" | null>(null);
  const [deleting, setDeleting] = React.useState<Rule | null>(null);
  const list = q.data ?? [];
  const datasetName = (id: string | null) => (id ? (datasets.data?.find((d) => d.id === id)?.name ?? "One dataset") : "All datasets");

  return (
    <Surface className="overflow-hidden">
      <SurfaceHeader
        title="Rules"
        description="What counts as a problem. A problem notifies once, stays one open incident while scans keep showing it, and resolves itself when a later scan no longer does."
        action={
          canEdit &&
          list.length > 0 && (
            <Button size="sm" onClick={() => setEditing("new")}>
              <PlusIcon />
              Add rule
            </Button>
          )
        }
      />
      {q.isPending ? (
        <TableSkeleton rows={4} cols={4} />
      ) : q.isError ? (
        <ErrorState compact error={q.error} title="Rules could not be loaded" onRetry={() => void q.refetch()} />
      ) : list.length === 0 ? (
        <EmptyState
          compact
          icon={ShieldAlertIcon}
          title="No alert rules"
          description="Without rules, failing checks only show up when someone looks. Add a rule such as 'an error check fails' and pick who to tell."
          action={
            canEdit ? (
              <Button size="sm" onClick={() => setEditing("new")}>
                <PlusIcon />
                Add a rule
              </Button>
            ) : undefined
          }
        />
      ) : (
        <ul className="divide-y divide-hairline px-5 pb-2">
          {list.map((r) => {
            const chans = r.channel_ids.map((id) => channels.data?.find((c) => c.id === id)).filter((c): c is Channel => !!c);
            return (
              <li key={r.id} className={cn("flex flex-col gap-3 py-3.5 sm:flex-row sm:items-center", !r.enabled && "opacity-60")}>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-[13.5px] font-medium">{r.name}</span>
                    <Chip tone="primary">{ruleKindLabel(r.kind)}</Chip>
                    <Chip tone="neutral">{datasetName(r.dataset_id)}</Chip>
                  </div>
                  <div className="mt-0.5 text-[12.5px] text-muted-foreground">
                    {ruleSummary(r)}
                    {r.notify_on_resolve ? ". Also tells when it resolves." : "."}
                  </div>
                  <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                    {chans.length ? (
                      chans.map((c) => {
                        const Icon = CHANNEL_ICON[c.kind] ?? BellIcon;
                        return (
                          <span key={c.id} className="inline-flex items-center gap-1 rounded-full bg-muted px-2 py-0.5 text-[11.5px] text-muted-foreground">
                            <Icon className="size-3" />
                            {c.name}
                          </span>
                        );
                      })
                    ) : (
                      <span className="text-[11.5px] text-warn">No channel: incidents open, but nobody is told.</span>
                    )}
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  {canEdit ? (
                    <>
                      <Switch
                        checked={r.enabled}
                        aria-label={r.enabled ? `Pause ${r.name}` : `Enable ${r.name}`}
                        onCheckedChange={(on) =>
                          update.mutate(
                            { id: r.id, body: { enabled: on } },
                            { onSuccess: () => toast.success(on ? `${r.name} enabled.` : `${r.name} paused.`), onError: (err) => toast.error(errorMessage(err)) },
                          )
                        }
                      />
                      <Button variant="subtle" size="icon-xs" aria-label={`Edit ${r.name}`} onClick={() => setEditing(r)}>
                        <PencilIcon />
                      </Button>
                      <Button variant="subtle" size="icon-xs" aria-label={`Delete ${r.name}`} onClick={() => setDeleting(r)}>
                        <Trash2Icon />
                      </Button>
                    </>
                  ) : (
                    <Chip tone={r.enabled ? "success" : "neutral"} dot>
                      {r.enabled ? "Enabled" : "Paused"}
                    </Chip>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}
      <RuleDialog pid={pid} rule={editing} channels={channels.data ?? []} datasets={(datasets.data ?? []).map((d) => ({ value: d.id, label: d.name }))} onClose={() => setEditing(null)} />
      <ConfirmDialog
        open={!!deleting}
        onOpenChange={(o) => !o && setDeleting(null)}
        title={`Delete ${deleting?.name ?? "this rule"}?`}
        description="Its incidents are deleted with it, open or resolved. Pause the rule instead to keep the history."
        confirmLabel="Delete rule"
        pending={del.isPending}
        onConfirm={() =>
          deleting &&
          del.mutate(deleting.id, {
            onSuccess: () => {
              toast.success(`${deleting.name} deleted.`);
              setDeleting(null);
            },
            onError: (err) => toast.error(errorMessage(err)),
          })
        }
      />
    </Surface>
  );
}

const KIND_ORDER: RuleKind[] = ["check_failed", "score_below", "anomaly", "schema_change", "scan_failed"];

function RuleDialog({
  pid,
  rule,
  channels,
  datasets,
  onClose,
}: {
  pid: string;
  rule: Rule | "new" | null;
  channels: Channel[];
  datasets: { value: string; label: string }[];
  onClose: () => void;
}) {
  const create = useCreateRule(pid);
  const update = useUpdateRule(pid);
  const existing = rule && rule !== "new" ? rule : null;
  const [name, setName] = React.useState("");
  const [kind, setKind] = React.useState<RuleKind>("check_failed");
  const [severity, setSeverity] = React.useState<Severity>("error");
  const [threshold, setThreshold] = React.useState("95");
  const [scope, setScope] = React.useState("all");
  const [chosen, setChosen] = React.useState<string[]>([]);
  const [onResolve, setOnResolve] = React.useState(true);
  const [enabled, setEnabled] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const pending = create.isPending || update.isPending;

  React.useEffect(() => {
    if (!rule) return;
    const r = rule === "new" ? null : rule;
    setName(r?.name ?? "");
    setKind((r?.kind as RuleKind) ?? "check_failed");
    setSeverity((r?.min_severity as Severity) ?? "error");
    setThreshold(r?.threshold != null ? String(r.threshold) : "95");
    setScope(r?.dataset_id ?? "all");
    setChosen(r?.channel_ids ?? channels.filter((c) => c.enabled).map((c) => c.id).slice(0, 1));
    setOnResolve(r?.notify_on_resolve ?? true);
    setEnabled(r?.enabled ?? true);
    setError(null);
    // Channels only seed a new rule's default; later channel refreshes must not reset the form.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rule]);

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return setError("Name the rule, like 'Error checks failing'.");
    const t = Number(threshold);
    if (kind === "score_below" && (!Number.isFinite(t) || t <= 0 || t > 100)) return setError("The threshold is a percent from 1 to 100.");
    setError(null);
    const body: RuleIn = {
      name: name.trim(),
      kind,
      dataset_id: scope === "all" ? null : scope,
      min_severity: severity,
      threshold: kind === "score_below" ? t : null,
      channel_ids: chosen,
      notify_on_resolve: onResolve,
      enabled,
    };
    const done = {
      onSuccess: () => {
        toast.success(existing ? `${body.name} saved.` : `${body.name} added. It applies from the next scan.`);
        onClose();
      },
      onError: (err: unknown) => setError(errorMessage(err)),
    };
    if (existing) {
      const { kind: _kind, ...rest } = body;
      update.mutate({ id: existing.id, body: rest }, done);
    } else {
      create.mutate(body, done);
    }
  }

  return (
    <Dialog open={!!rule} onOpenChange={(o) => !o && !pending && onClose()}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>{existing ? `Edit ${existing.name}` : "Add an alert rule"}</DialogTitle>
          <DialogDescription>A problem notifies once, and resolves itself when a later scan no longer shows it.</DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="flex min-h-0 flex-col" noValidate>
          <DialogBody className="space-y-4">
            <Field label="Name" htmlFor="rl-name">
              <Input id="rl-name" maxLength={120} value={name} onChange={(e) => setName(e.target.value)} />
            </Field>
            <Field label="When" htmlFor="rl-kind" hint={existing ? "The kind of a rule is fixed. Add a new rule for another kind." : RULE_KINDS[kind].description}>
              <SimpleSelect
                id="rl-kind"
                value={kind}
                disabled={!!existing}
                onValueChange={(v) => v && setKind(v as RuleKind)}
                options={KIND_ORDER.map((k) => ({ value: k, label: RULE_KINDS[k].label }))}
              />
            </Field>
            {kind === "check_failed" && (
              <div className="space-y-1.5">
                <Label>Minimum severity</Label>
                <Segmented<Severity>
                  ariaLabel="Minimum severity"
                  value={severity}
                  onChange={setSeverity}
                  options={[
                    { value: "error", label: "Errors only" },
                    { value: "warn", label: "Warnings and errors" },
                  ]}
                />
              </div>
            )}
            {kind === "score_below" && (
              <Field label="Threshold (percent)" htmlFor="rl-th" hint="Alert when a dataset's quality score falls below this.">
                <Input id="rl-th" inputMode="decimal" className="w-32" value={threshold} onChange={(e) => setThreshold(e.target.value)} />
              </Field>
            )}
            <Field label="Datasets" htmlFor="rl-scope">
              <SimpleSelect id="rl-scope" value={scope} onValueChange={(v) => setScope(v || "all")} options={[{ value: "all", label: "All datasets, including new ones" }, ...datasets]} />
            </Field>
            <div className="space-y-1.5">
              <Label>Notify</Label>
              {channels.length === 0 ? (
                <p className="rounded-xl bg-muted px-4 py-3 text-[12.5px] text-muted-foreground">
                  No channels yet. The rule still opens incidents; add a channel to be told about them.
                </p>
              ) : (
                <div className="flex flex-wrap gap-2">
                  {channels.map((c) => {
                    const on = chosen.includes(c.id);
                    const Icon = CHANNEL_ICON[c.kind] ?? BellIcon;
                    return (
                      <button
                        key={c.id}
                        type="button"
                        role="checkbox"
                        aria-checked={on}
                        onClick={() => setChosen((s) => (on ? s.filter((x) => x !== c.id) : [...s, c.id]))}
                        className={cn(
                          "inline-flex h-8 items-center gap-1.5 rounded-full bg-muted px-3 text-[12.5px] font-medium text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-2 focus-visible:outline-ring",
                          on && "bg-primary-soft text-primary",
                        )}
                      >
                        {on ? <CheckIcon className="size-3.5" /> : <Icon className="size-3.5" />}
                        {c.name}
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="flex items-start gap-3 rounded-xl bg-muted/70 px-3 py-2.5">
                <Switch checked={onResolve} onCheckedChange={setOnResolve} aria-label="Notify when resolved" className="mt-0.5" />
                <span>
                  <span className="block text-[13px] font-medium">Notify when resolved</span>
                  <span className="block text-[12px] text-muted-foreground">A second message when it clears.</span>
                </span>
              </label>
              <label className="flex items-start gap-3 rounded-xl bg-muted/70 px-3 py-2.5">
                <Switch checked={enabled} onCheckedChange={setEnabled} aria-label="Enabled" className="mt-0.5" />
                <span>
                  <span className="block text-[13px] font-medium">Enabled</span>
                  <span className="block text-[12px] text-muted-foreground">Paused rules open nothing.</span>
                </span>
              </label>
            </div>
            {error && <FieldError>{error}</FieldError>}
          </DialogBody>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={onClose} disabled={pending}>
              Cancel
            </Button>
            <Button type="submit" disabled={pending}>
              {pending ? "Saving..." : existing ? "Save rule" : "Add rule"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
