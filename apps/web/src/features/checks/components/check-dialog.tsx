"use client";

import { ArrowLeftIcon, PlusIcon, Trash2Icon } from "lucide-react";
import * as React from "react";
import { toast } from "sonner";

import { Hint } from "@/components/hint";
import { Segmented } from "@/components/segmented";
import { Button } from "@/components/ui/button";
import { Dialog, DialogBody, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input, Textarea } from "@/components/ui/input";
import { Field, FieldError, Label } from "@/components/ui/label";
import { SimpleSelect } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { useDatasets } from "@/features/datasets/api";
import { TagInput } from "@/features/datasets/components/tag-input";
import type { DatasetColumn } from "@/features/datasets/use-columns";
import { errorMessage } from "@/lib/api/errors";
import type { Check, CheckType, Dataset, Dimension } from "@/lib/api/types";
import { cn } from "@/lib/cn";
import { CHECK_TYPES, DIMENSIONS, dimensionLabel } from "@/lib/quality";

import { useBulkCreateChecks, useCreateCheck, useUpdateCheck } from "../api";
import { type CheckForm, emptyForm, type ParamState, toCheckIn } from "../form";
import { COMPARE_OPS, PATTERN_PRESETS, SCHEMA_TYPES, TYPE_CHOICES } from "../params";

const TYPE_GROUPS: { label: string; types: CheckType[] }[] = [
  { label: "Missing and duplicate data", types: ["not_null", "unique", "duplicate_rows"] },
  { label: "Valid values", types: ["type", "range", "pattern", "accepted_values", "length", "outliers"] },
  { label: "Consistency", types: ["schema", "format_consistency", "compare", "referential"] },
  { label: "Freshness and volume", types: ["freshness", "row_count"] },
  { label: "Your own rule", types: ["custom_sql"] },
];

export type CheckDialogMode = { kind: "create"; initial?: CheckForm; origin?: "manual" | "ai" } | { kind: "edit"; check: Check; initial: CheckForm };

export function CheckDialog({
  pid,
  d,
  columns,
  mode,
  onClose,
}: {
  pid: string;
  d: Dataset;
  columns: DatasetColumn[];
  mode: CheckDialogMode | null;
  onClose: () => void;
}) {
  return (
    <Dialog open={!!mode} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-2xl">{mode && <CheckEditor key={mode.kind === "edit" ? mode.check.id : "new"} pid={pid} d={d} columns={columns} mode={mode} onClose={onClose} />}</DialogContent>
    </Dialog>
  );
}

function CheckEditor({ pid, d, columns, mode, onClose }: { pid: string; d: Dataset; columns: DatasetColumn[]; mode: CheckDialogMode; onClose: () => void }) {
  const editing = mode.kind === "edit";
  const [step, setStep] = React.useState<"type" | "form">(editing || mode.initial ? "form" : "type");
  const [f, setF] = React.useState<CheckForm>(() => mode.initial ?? emptyForm());
  const [error, setError] = React.useState("");
  const create = useCreateCheck(pid, d.id);
  const bulk = useBulkCreateChecks(pid, d.id);
  const update = useUpdateCheck(pid, d.id);
  const pending = create.isPending || update.isPending || bulk.isPending;
  const meta = CHECK_TYPES[f.type];
  const colType = columns.find((c) => c.name === f.column)?.type;

  const set = <K extends keyof CheckForm>(k: K, v: CheckForm[K]) => {
    setF((prev) => ({ ...prev, [k]: v }));
    setError("");
  };
  const setP = <K extends keyof ParamState>(k: K, v: ParamState[K]) => {
    setF((prev) => ({ ...prev, p: { ...prev.p, [k]: v } }));
    setError("");
  };

  function pickType(t: CheckType) {
    setF((prev) => {
      const next = { ...prev, type: t };
      if (t === "schema" && !prev.p.schema_columns.length && columns.length) {
        next.p = { ...prev.p, schema_columns: columns.map((c) => ({ name: c.name, type: c.type, required: true })) };
      }
      return next;
    });
    setStep("form");
  }

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const body = toCheckIn(f, meta.needsColumn, colType);
    if (typeof body === "string") {
      setError(body);
      return;
    }
    const done = (msg: string) => {
      toast.success(msg);
      onClose();
    };
    const fail = (err: unknown) => setError(errorMessage(err));
    if (mode.kind === "edit") {
      const { type: _type, name, ...rest } = body;
      update.mutate({ checkId: mode.check.id, body: { ...rest, ...(name ? { name } : {}) } }, { onSuccess: () => done("Check saved. It applies from the next scan."), onError: fail });
    } else if (mode.origin === "ai") {
      bulk.mutate({ checks: [body], origin: "ai" }, { onSuccess: () => done("Check added. It runs on the next scan."), onError: fail });
    } else {
      create.mutate(body, { onSuccess: () => done("Check added. It runs on the next scan."), onError: fail });
    }
  }

  if (step === "type") {
    return (
      <>
        <DialogHeader>
          <DialogTitle>Add a check</DialogTitle>
          <DialogDescription>Pick what to verify. Every check runs inside the source on each scan and counts the rows that fail it.</DialogDescription>
        </DialogHeader>
        <DialogBody className="space-y-5">
          {TYPE_GROUPS.map((g) => (
            <div key={g.label}>
              <div className="mb-2 text-[11px] font-semibold tracking-[0.04em] text-subtle uppercase">{g.label}</div>
              <div className="grid gap-2 sm:grid-cols-2">
                {g.types.map((t) => (
                  <button
                    key={t}
                    type="button"
                    onClick={() => pickType(t)}
                    className="rounded-xl bg-muted/60 px-3.5 py-3 text-left transition-colors hover:bg-primary-soft focus-visible:outline-2 focus-visible:outline-ring"
                  >
                    <div className="text-[13px] font-semibold">{CHECK_TYPES[t].label}</div>
                    <div className="mt-0.5 text-xs leading-snug text-muted-foreground">{CHECK_TYPES[t].description}</div>
                  </button>
                ))}
              </div>
            </div>
          ))}
        </DialogBody>
      </>
    );
  }

  const columnOptions = columns.map((c) => ({ value: c.name, label: `${c.name}  (${c.type})` }));

  return (
    <form onSubmit={submit} className="flex min-h-0 flex-1 flex-col">
      <DialogHeader>
        <DialogTitle>{editing ? `Edit ${mode.check.name}` : `${meta.label} check`}</DialogTitle>
        <DialogDescription>{meta.description}</DialogDescription>
      </DialogHeader>
      <DialogBody className="space-y-4">
        {!editing && !mode.initial && (
          <button type="button" onClick={() => setStep("type")} className="-mt-1 inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
            <ArrowLeftIcon className="size-3" /> Pick another type
          </button>
        )}
        {(meta.needsColumn || f.type === "unique") && (
          <Field label="Column" htmlFor="ck-col">
            <ColumnPicker id="ck-col" value={f.column} onChange={(v) => set("column", v)} options={columnOptions} />
          </Field>
        )}

        <ParamFields f={f} setP={setP} columns={columns} columnOptions={columnOptions} currentDatasetId={d.id} pid={pid} />

        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Name" htmlFor="ck-name" hint="Optional. A name is built from the type and column.">
            <Input id="ck-name" value={f.name} onChange={(e) => set("name", e.target.value)} maxLength={200} placeholder="Email looks valid" />
          </Field>
          <Field label="Severity" labelExtra={<Hint term="severity" />}>
            <Segmented
              ariaLabel="Severity"
              value={f.severity}
              onChange={(v) => set("severity", v)}
              options={[
                { value: "error", label: "Error" },
                { value: "warn", label: "Warning" },
              ]}
            />
          </Field>
        </div>

        <details className="group rounded-xl bg-muted/50 px-4 py-3" open={!!(f.tol_count || f.tol_percent || f.filter_sql || f.dimension)}>
          <summary className="cursor-pointer text-[13px] font-medium select-none">Tolerance, filter and dimension</summary>
          <div className="mt-3 space-y-4">
            <div>
              <Label className="mb-1.5">
                Tolerance <Hint term="tolerance" />
              </Label>
              <div className="grid grid-cols-2 gap-3">
                <Input aria-label="Allowed failing rows" inputMode="numeric" value={f.tol_count} onChange={(e) => set("tol_count", e.target.value)} placeholder="Rows, e.g. 10" className="tabular" />
                <Input aria-label="Allowed failing percent" inputMode="decimal" value={f.tol_percent} onChange={(e) => set("tol_percent", e.target.value)} placeholder="Percent, e.g. 0.5" className="tabular" />
              </div>
              <p className="mt-1.5 text-xs text-muted-foreground">Leave both empty to fail on any failing row. With both set, the check passes only within both.</p>
            </div>
            <Field label="Filter" htmlFor="ck-filter" hint="An SQL condition: only matching rows are checked, for example status = 'paid'.">
              <Input id="ck-filter" value={f.filter_sql} onChange={(e) => set("filter_sql", e.target.value)} className="font-mono text-[12.5px]" placeholder="country = 'IN'" />
            </Field>
            <Field label="Dimension" htmlFor="ck-dim" hint="Which part of the score this check counts toward. The default fits most checks.">
              <SimpleSelect
                id="ck-dim"
                value={f.dimension || "default"}
                onValueChange={(v) => set("dimension", v === "default" ? "" : (v as Dimension))}
                options={[{ value: "default", label: "Default for this type" }, ...DIMENSIONS.map((x) => ({ value: x, label: dimensionLabel(x) }))]}
              />
            </Field>
          </div>
        </details>

        {error && <FieldError className="rounded-lg bg-danger-soft px-3 py-2 text-[13px]">{error}</FieldError>}
      </DialogBody>
      <DialogFooter>
        <Button type="button" variant="ghost" onClick={onClose} disabled={pending}>
          Cancel
        </Button>
        <Button type="submit" disabled={pending}>
          {pending ? "Saving..." : editing ? "Save check" : "Add check"}
        </Button>
      </DialogFooter>
    </form>
  );
}

function ColumnPicker({ id, value, onChange, options, placeholder = "Pick a column" }: { id?: string; value: string; onChange: (v: string) => void; options: { value: string; label: string }[]; placeholder?: string }) {
  if (!options.length) {
    return <Input id={id} value={value} onChange={(e) => onChange(e.target.value)} className="font-mono" placeholder="column_name" />;
  }
  const opts = value && !options.some((o) => o.value === value) ? [{ value, label: value }, ...options] : options;
  return <SimpleSelect id={id} value={value} onValueChange={onChange} options={opts} placeholder={placeholder} />;
}

function ParamFields({
  f,
  setP,
  columns,
  columnOptions,
  currentDatasetId,
  pid,
}: {
  f: CheckForm;
  setP: <K extends keyof ParamState>(k: K, v: ParamState[K]) => void;
  columns: DatasetColumn[];
  columnOptions: { value: string; label: string }[];
  currentDatasetId: string;
  pid: string;
}) {
  const p = f.p;
  const names = columns.map((c) => c.name);
  switch (f.type) {
    case "not_null":
      return (
        <ToggleRow id="pp-empty" label="Blank text counts as missing" hint="An empty or whitespace-only value fails like a NULL." checked={p.empty_is_null} onChange={(v) => setP("empty_is_null", v)} />
      );
    case "unique":
      return (
        <Field label="Together with (optional)" hint="Extra key columns: the combination must be unique, like (order_id, line_no).">
          <TagInput value={p.key_columns} onChange={(v) => setP("key_columns", v)} suggestions={names.filter((n) => n !== f.column)} mono placeholder="Add a column" />
        </Field>
      );
    case "duplicate_rows":
      return (
        <Field label="Compare only these columns (optional)" hint="Empty compares every column, so only exact copies count.">
          <TagInput value={p.key_columns} onChange={(v) => setP("key_columns", v)} suggestions={names} mono placeholder="All columns" />
        </Field>
      );
    case "schema":
      return <SchemaEditor p={p} setP={setP} columns={columns} />;
    case "type":
      return (
        <Field label="Values must parse as">
          <SimpleSelect value={p.value_type} onValueChange={(v) => setP("value_type", v)} options={TYPE_CHOICES.map((t) => ({ value: t, label: t }))} />
        </Field>
      );
    case "range":
      return (
        <>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Minimum" htmlFor="pp-min">
              <Input id="pp-min" value={p.min} onChange={(e) => setP("min", e.target.value)} placeholder="0" className="tabular" />
            </Field>
            <Field label="Maximum" htmlFor="pp-max">
              <Input id="pp-max" value={p.max} onChange={(e) => setP("max", e.target.value)} placeholder="100" className="tabular" />
            </Field>
          </div>
          <ToggleRow id="pp-incl" label="Include the limits" hint="On: 0 and 100 themselves pass. Dates work too, like 2020-01-01." checked={p.inclusive} onChange={(v) => setP("inclusive", v)} />
        </>
      );
    case "pattern":
      return (
        <>
          <Segmented
            ariaLabel="Pattern source"
            value={p.pattern_mode}
            onChange={(v) => setP("pattern_mode", v)}
            options={[
              { value: "preset", label: "Common format" },
              { value: "regex", label: "Regular expression" },
            ]}
          />
          {p.pattern_mode === "preset" ? (
            <Field label="Format" hint={`Example: ${PATTERN_PRESETS[p.preset]?.example ?? ""}`}>
              <SimpleSelect value={p.preset} onValueChange={(v) => setP("preset", v)} options={Object.entries(PATTERN_PRESETS).map(([k, v]) => ({ value: k, label: v.label }))} />
            </Field>
          ) : (
            <Field label="Regular expression" htmlFor="pp-re" hint="The whole value must match. Use explicit classes like [0-9] and [A-Za-z], which work the same in every database.">
              <Input id="pp-re" value={p.regex} onChange={(e) => setP("regex", e.target.value)} className="font-mono" placeholder="[A-Z]{2}-[0-9]{4}" />
            </Field>
          )}
        </>
      );
    case "accepted_values":
      return (
        <>
          <Field label="Allowed values" hint="Press Enter after each value.">
            <TagInput value={p.values} onChange={(v) => setP("values", v)} placeholder="paid, shipped, cancelled" />
          </Field>
          <ToggleRow id="pp-case" label="Case sensitive" hint="Off: Paid and paid are the same value." checked={p.case_sensitive} onChange={(v) => setP("case_sensitive", v)} />
        </>
      );
    case "length":
    case "row_count":
      return (
        <div className="grid grid-cols-2 gap-3">
          <Field label={f.type === "length" ? "Minimum characters" : "Minimum rows"} htmlFor="pp-min">
            <Input id="pp-min" inputMode="numeric" value={p.min} onChange={(e) => setP("min", e.target.value)} className="tabular" placeholder={f.type === "length" ? "1" : "1000"} />
          </Field>
          <Field label={f.type === "length" ? "Maximum characters" : "Maximum rows"} htmlFor="pp-max">
            <Input id="pp-max" inputMode="numeric" value={p.max} onChange={(e) => setP("max", e.target.value)} className="tabular" placeholder={f.type === "length" ? "255" : "Optional"} />
          </Field>
        </div>
      );
    case "freshness":
      return (
        <Field label="Maximum age in hours" htmlFor="pp-age" hint="The newest value in the column must be younger than this. 24 means data from the last day.">
          <Input id="pp-age" inputMode="decimal" value={p.max_age_hours} onChange={(e) => setP("max_age_hours", e.target.value)} className="w-40 tabular" />
        </Field>
      );
    case "referential":
      return <ReferentialFields p={p} setP={setP} pid={pid} currentDatasetId={currentDatasetId} />;
    case "compare":
      return (
        <div className="grid grid-cols-[7rem_1fr] gap-3">
          <Field label="Must be">
            <SimpleSelect value={p.op} onValueChange={(v) => setP("op", v)} options={COMPARE_OPS.map((o) => ({ value: o, label: o }))} />
          </Field>
          <Field label="Other column">
            <ColumnPicker value={p.other} onChange={(v) => setP("other", v)} options={columnOptions.filter((o) => o.value !== f.column)} />
          </Field>
        </div>
      );
    case "format_consistency":
      return (
        <Field label="Share with the most common shape (%)" htmlFor="pp-share" labelExtra={<Hint term="shape" />} hint="95 means at least 95% of values must look alike, like 999999 for a PIN code.">
          <Input id="pp-share" inputMode="decimal" value={p.min_share} onChange={(e) => setP("min_share", e.target.value)} className="w-32 tabular" />
        </Field>
      );
    case "outliers":
      return (
        <Field label="Standard deviations from the mean" htmlFor="pp-z" hint="Values further out fail. 3 flags roughly the most extreme 0.3% of normal data.">
          <Input id="pp-z" inputMode="decimal" value={p.z} onChange={(e) => setP("z", e.target.value)} className="w-32 tabular" />
        </Field>
      );
    case "custom_sql":
      return (
        <Field label="Query returning failing rows" htmlFor="pp-sql" hint="One read-only SELECT. Write {table} for this dataset; every row it returns counts as a failure.">
          <Textarea id="pp-sql" value={p.sql} onChange={(e) => setP("sql", e.target.value)} rows={5} className="font-mono text-[12.5px]" />
        </Field>
      );
  }
}

function ToggleRow({ id, label, hint, checked, onChange }: { id: string; label: string; hint: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <div className="flex items-start justify-between gap-4 rounded-lg bg-muted/50 px-3.5 py-2.5">
      <div>
        <label htmlFor={id} className="text-[13px] font-medium">
          {label}
        </label>
        <p className="mt-0.5 text-xs text-muted-foreground">{hint}</p>
      </div>
      <Switch id={id} checked={checked} onCheckedChange={onChange} />
    </div>
  );
}

function ReferentialFields({ p, setP, pid, currentDatasetId }: { p: ParamState; setP: <K extends keyof ParamState>(k: K, v: ParamState[K]) => void; pid: string; currentDatasetId: string }) {
  const ds = useDatasets(pid);
  const others = (ds.data ?? []).filter((x) => x.id !== currentDatasetId);
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <Field label="Other dataset" hint="It must come from the same source (connection, or files loaded together).">
        {others.length ? (
          <SimpleSelect
            value={p.ref_dataset}
            onValueChange={(v) => setP("ref_dataset", v)}
            options={[...(p.ref_dataset && !others.some((o) => o.name === p.ref_dataset) ? [{ value: p.ref_dataset, label: p.ref_dataset }] : []), ...others.map((o) => ({ value: o.name, label: o.name }))]}
            placeholder="Pick a dataset"
          />
        ) : (
          <Input value={p.ref_dataset} onChange={(e) => setP("ref_dataset", e.target.value)} placeholder="Dataset name or id" />
        )}
      </Field>
      <Field label="Column in that dataset" htmlFor="pp-refcol">
        <Input id="pp-refcol" value={p.ref_column} onChange={(e) => setP("ref_column", e.target.value)} className="font-mono" placeholder="customer_id" />
      </Field>
    </div>
  );
}

function SchemaEditor({ p, setP, columns }: { p: ParamState; setP: <K extends keyof ParamState>(k: K, v: ParamState[K]) => void; columns: DatasetColumn[] }) {
  const rows = p.schema_columns;
  const update = (i: number, patch: Partial<(typeof rows)[number]>) => setP("schema_columns", rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Label>Expected columns</Label>
        {columns.length > 0 && (
          <Button type="button" variant="subtle" size="xs" onClick={() => setP("schema_columns", columns.map((c) => ({ name: c.name, type: c.type, required: true })))}>
            Fill from the latest scan
          </Button>
        )}
      </div>
      <ul className="max-h-64 space-y-1.5 overflow-y-auto pr-1">
        {rows.map((r, i) => (
          <li key={i} className="grid grid-cols-[minmax(0,1fr)_7.5rem_auto_auto] items-center gap-2">
            <Input aria-label={`Column ${i + 1} name`} value={r.name} onChange={(e) => update(i, { name: e.target.value })} className="h-8 font-mono text-[12.5px]" />
            <SimpleSelect aria-label={`Column ${i + 1} type`} size="sm" value={r.type} onValueChange={(v) => update(i, { type: v })} options={SCHEMA_TYPES.map((t) => ({ value: t, label: t }))} />
            <label className={cn("flex items-center gap-1.5 text-xs", r.required ? "text-foreground" : "text-muted-foreground")}>
              <Switch checked={r.required} onCheckedChange={(v) => update(i, { required: v })} aria-label={`Column ${i + 1} required`} />
              <span className="hidden sm:inline">Required</span>
            </label>
            <Button type="button" variant="subtle" size="icon-xs" aria-label={`Remove column ${i + 1}`} onClick={() => setP("schema_columns", rows.filter((_, j) => j !== i))}>
              <Trash2Icon />
            </Button>
          </li>
        ))}
      </ul>
      <Button type="button" variant="outline" size="xs" onClick={() => setP("schema_columns", [...rows, { name: "", type: "any", required: true }])}>
        <PlusIcon /> Add column
      </Button>
      <ToggleRow id="pp-extra" label="Allow other columns" hint="Off: a column not in this list fails the check." checked={p.allow_extra} onChange={(v) => setP("allow_extra", v)} />
    </div>
  );
}
