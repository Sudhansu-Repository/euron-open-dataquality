"use client";

import { FileCode2Icon, ListChecksIcon, MoreHorizontalIcon, PencilIcon, PlusIcon, Trash2Icon, WandSparklesIcon } from "lucide-react";
import * as React from "react";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { ResultChip } from "@/components/quality";
import { Segmented } from "@/components/segmented";
import { Surface } from "@/components/surface";
import { TableSkeleton } from "@/components/table-skeleton";
import { Button } from "@/components/ui/button";
import { Chip } from "@/components/ui/chip";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Switch } from "@/components/ui/switch";
import { useDatasetColumns } from "@/features/datasets/use-columns";
import { errorMessage } from "@/lib/api/errors";
import type { Check, Dataset } from "@/lib/api/types";
import { cn } from "@/lib/cn";
import { checkTypeLabel, dimensionLabel } from "@/lib/quality";

import { useChecks, useDeleteCheck, useUpdateCheck } from "../api";
import { fromCheck } from "../form";
import { describeParams, describeTolerance } from "../params";
import { CheckDialog, type CheckDialogMode } from "./check-dialog";
import { DraftDialog } from "./draft-dialog";
import { SuggestionsPanel } from "./suggestions-panel";
import { YamlDialog } from "./yaml-dialog";

type Filter = "all" | "failing" | "off";

export function ChecksTab({ pid, d, canEdit }: { pid: string; d: Dataset; canEdit: boolean }) {
  const q = useChecks(pid, d.id);
  const { columns } = useDatasetColumns(pid, d);
  const [dialog, setDialog] = React.useState<CheckDialogMode | null>(null);
  const [draftOpen, setDraftOpen] = React.useState(false);
  const [yamlOpen, setYamlOpen] = React.useState(false);
  const [filter, setFilter] = React.useState<Filter>("all");
  const [deleting, setDeleting] = React.useState<Check | null>(null);
  const del = useDeleteCheck(pid, d.id);

  const all = q.data ?? [];
  const failing = all.filter((c) => c.last && c.last.status !== "pass");
  const off = all.filter((c) => !c.enabled);
  const rows = filter === "failing" ? failing : filter === "off" ? off : all;

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <Segmented
          ariaLabel="Show checks"
          value={filter}
          onChange={setFilter}
          className="w-full sm:w-auto"
          options={[
            { value: "all", label: `All ${all.length}` },
            { value: "failing", label: `Failing ${failing.length}` },
            { value: "off", label: `Off ${off.length}` },
          ]}
        />
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" size="sm" onClick={() => setYamlOpen(true)}>
            <FileCode2Icon />
            Checks as code
          </Button>
          {canEdit && (
            <>
              <Button variant="outline" size="sm" onClick={() => setDraftOpen(true)}>
                <WandSparklesIcon />
                Describe a check
              </Button>
              <Button size="sm" onClick={() => setDialog({ kind: "create" })}>
                <PlusIcon />
                Add check
              </Button>
            </>
          )}
        </div>
      </div>

      {canEdit && <SuggestionsPanel pid={pid} d={d} />}

      <Surface className="overflow-hidden">
        {q.isPending ? (
          <div className="pt-3">
            <TableSkeleton rows={8} cols={5} />
          </div>
        ) : q.isError && !q.data ? (
          <ErrorState error={q.error} title="Could not load checks" onRetry={() => void q.refetch()} />
        ) : all.length === 0 ? (
          <EmptyState
            icon={ListChecksIcon}
            title="No checks yet"
            description="A check is one rule the data must follow, like 'email is never empty' or 'amount is between 0 and 100000'. Scans run every enabled check and score the dataset on the results."
            action={
              canEdit ? (
                <Button onClick={() => setDialog({ kind: "create" })}>
                  <PlusIcon />
                  Add the first check
                </Button>
              ) : undefined
            }
          />
        ) : rows.length === 0 ? (
          <EmptyState
            compact
            icon={ListChecksIcon}
            title={filter === "failing" ? "No failing checks" : "Every check is on"}
            description={filter === "failing" ? "Every check passed in the latest scan." : "Checks you switch off stay here and are skipped by scans."}
            action={
              <Button variant="outline" size="sm" onClick={() => setFilter("all")}>
                Show all checks
              </Button>
            }
          />
        ) : (
          <ul>
            {rows.map((c) => (
              <CheckRow
                key={c.id}
                pid={pid}
                did={d.id}
                c={c}
                canEdit={canEdit}
                onEdit={() => setDialog({ kind: "edit", check: c, initial: fromCheck(c) })}
                onDelete={() => setDeleting(c)}
              />
            ))}
          </ul>
        )}
      </Surface>

      <CheckDialog pid={pid} d={d} columns={columns} mode={dialog} onClose={() => setDialog(null)} />
      <DraftDialog
        pid={pid}
        d={d}
        open={draftOpen}
        onOpenChange={setDraftOpen}
        onEdit={(form) => {
          setDraftOpen(false);
          setDialog({ kind: "create", initial: form, origin: "ai" });
        }}
      />
      <YamlDialog pid={pid} d={d} open={yamlOpen} onOpenChange={setYamlOpen} canEdit={canEdit} />
      <ConfirmDialog
        open={!!deleting}
        onOpenChange={(o) => !o && setDeleting(null)}
        title={`Delete ${deleting?.name ?? "check"}?`}
        description="Scans stop running it. Past results stay in the scan history."
        confirmLabel="Delete check"
        pending={del.isPending}
        onConfirm={() =>
          deleting &&
          del.mutate(deleting.id, {
            onSuccess: () => {
              toast.success("Check deleted");
              setDeleting(null);
            },
            onError: (err) => toast.error(errorMessage(err)),
          })
        }
      />
    </div>
  );
}

const ORIGIN_LABEL: Record<string, string> = { suggested: "Suggested", ai: "Drafted with AI", yaml: "From YAML" };

function CheckRow({ pid, did, c, canEdit, onEdit, onDelete }: { pid: string; did: string; c: Check; canEdit: boolean; onEdit: () => void; onDelete: () => void }) {
  const update = useUpdateCheck(pid, did);
  const params = describeParams(c.type, c.params);
  const tol = describeTolerance(c.tolerance);
  return (
    <li className={cn("flex flex-col gap-3 border-b border-hairline px-5 py-3.5 last:border-0 md:flex-row md:items-center md:gap-5", !c.enabled && "opacity-60")}>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span className="text-[13.5px] font-medium">{c.name}</span>
          {c.severity === "warn" && <Chip tone="warning">Warning</Chip>}
          {ORIGIN_LABEL[c.origin] && <span className="text-[11px] text-subtle">{ORIGIN_LABEL[c.origin]}</span>}
        </div>
        <div className="mt-0.5 flex flex-wrap gap-x-1.5 text-xs text-muted-foreground">
          <span className="font-medium text-foreground/80">{checkTypeLabel(c.type)}</span>
          {c.column && <span className="font-mono text-[11.5px]">{c.column}</span>}
          {params && <span>{params}</span>}
          {tol && <span>· tolerates {tol}</span>}
          {c.filter_sql && (
            <span className="max-w-[260px] truncate" title={c.filter_sql}>
              · where <span className="font-mono">{c.filter_sql}</span>
            </span>
          )}
          <span className="text-subtle">· {dimensionLabel(c.dimension)}</span>
        </div>
      </div>
      <div className="flex items-center gap-3 md:w-[300px] md:shrink-0">
        <div className="min-w-0 flex-1">
          {c.last ? (
            <div className="flex flex-col items-start gap-1 md:items-end">
              <ResultChip status={c.last.status} severity={c.severity} />
              <span className="max-w-full truncate text-[11.5px] text-muted-foreground tabular md:text-right" title={c.last.message}>
                {c.last.message}
              </span>
            </div>
          ) : (
            <span className="text-xs text-faint md:block md:text-right">Not run yet</span>
          )}
        </div>
        {canEdit && (
          <>
            <Switch
              checked={c.enabled}
              aria-label={c.enabled ? `Turn off ${c.name}` : `Turn on ${c.name}`}
              disabled={update.isPending}
              onCheckedChange={(v) =>
                update.mutate(
                  { checkId: c.id, body: { enabled: v } },
                  { onSuccess: () => toast.success(v ? "Check turned on" : "Check turned off. Scans skip it."), onError: (err) => toast.error(errorMessage(err)) },
                )
              }
            />
            <DropdownMenu>
              <DropdownMenuTrigger render={<Button variant="subtle" size="icon-sm" aria-label={`Actions for ${c.name}`} />}>
                <MoreHorizontalIcon />
              </DropdownMenuTrigger>
              <DropdownMenuContent>
                <DropdownMenuItem onClick={onEdit}>
                  <PencilIcon />
                  Edit
                </DropdownMenuItem>
                <DropdownMenuItem variant="destructive" onClick={onDelete}>
                  <Trash2Icon />
                  Delete
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </>
        )}
      </div>
    </li>
  );
}
