"use client";

import { LockIcon, Trash2Icon } from "lucide-react";
import { useRouter } from "next/navigation";
import * as React from "react";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { Surface, SurfaceHeader } from "@/components/surface";
import { Button } from "@/components/ui/button";
import { Input, Textarea } from "@/components/ui/input";
import { Field, FieldHint } from "@/components/ui/label";
import { SimpleSelect } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { errorMessage } from "@/lib/api/errors";
import type { Dataset, DatasetUpdate } from "@/lib/api/types";
import { cn } from "@/lib/cn";
import { formatDateTime, formatRelative } from "@/lib/format";

import { useDeleteDataset, useUpdateDataset } from "../api";
import { describeCron, restOptions } from "../meta";
import { useDatasetColumns } from "../use-columns";
import { TagInput } from "./tag-input";

const PRESETS = [
  { label: "Hourly", cron: "0 * * * *" },
  { label: "Daily 06:00", cron: "0 6 * * *" },
  { label: "Weekly Monday 06:00", cron: "0 6 * * 1" },
];

const COMMON_ZONES = [
  "UTC",
  "Asia/Kolkata",
  "Asia/Dubai",
  "Asia/Singapore",
  "Asia/Tokyo",
  "Australia/Sydney",
  "Europe/London",
  "Europe/Berlin",
  "Europe/Paris",
  "America/New_York",
  "America/Chicago",
  "America/Denver",
  "America/Los_Angeles",
  "America/Sao_Paulo",
  "Africa/Johannesburg",
];

function browserZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}

interface Form {
  name: string;
  description: string;
  query_sql: string;
  filter_sql: string;
  masked_columns: string[];
  tags: string[];
  profile_enabled: boolean;
  scan_timeout_s: string;
  schedule_enabled: boolean;
  schedule_cron: string;
  schedule_tz: string;
  rest_url: string;
  rest_records_path: string;
  rest_headers: string;
}

function initial(d: Dataset): Form {
  const rest = restOptions(d);
  return {
    name: d.name,
    description: d.description,
    query_sql: d.query_sql ?? "",
    filter_sql: d.filter_sql ?? "",
    masked_columns: d.masked_columns,
    tags: d.tags,
    profile_enabled: d.profile_enabled,
    scan_timeout_s: String(d.scan_timeout_s),
    schedule_enabled: d.schedule_enabled,
    schedule_cron: d.schedule_cron ?? "",
    // A dataset that was never scheduled starts in this browser's zone.
    schedule_tz: d.schedule_cron ? d.schedule_tz : browserZone(),
    rest_url: rest.url,
    rest_records_path: rest.records_path,
    rest_headers: "",
  };
}

function parseHeaders(text: string): Record<string, string> | string {
  const out: Record<string, string> = {};
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    if (!line) continue;
    const i = line.indexOf(":");
    if (i <= 0) return `"${line}" is not a header. Write one per line as Name: value.`;
    out[line.slice(0, i).trim()] = line.slice(i + 1).trim();
  }
  return out;
}

const same = (a: string[], b: string[]) => a.length === b.length && a.every((v, i) => v === b[i]);

/** Only the fields that changed, so a save never rewrites what someone else just edited. */
function diff(d: Dataset, f: Form): DatasetUpdate | string {
  const o = initial(d);
  const body: DatasetUpdate = {};
  if (f.name.trim() !== o.name) body.name = f.name.trim();
  if (f.description !== o.description) body.description = f.description;
  if (d.kind === "query" && f.query_sql !== o.query_sql) body.query_sql = f.query_sql;
  if (f.filter_sql !== o.filter_sql) body.filter_sql = f.filter_sql.trim() || null;
  if (!same(f.masked_columns, o.masked_columns)) body.masked_columns = f.masked_columns;
  if (!same(f.tags, o.tags)) body.tags = f.tags;
  if (f.profile_enabled !== o.profile_enabled) body.profile_enabled = f.profile_enabled;
  if (f.scan_timeout_s !== o.scan_timeout_s) {
    const n = Number(f.scan_timeout_s);
    if (!Number.isInteger(n) || n < 10 || n > 86_400) return "The scan timeout is a whole number of seconds from 10 to 86400.";
    body.scan_timeout_s = n;
  }
  if (f.schedule_enabled && !f.schedule_cron.trim()) return "Pick a preset or write a cron expression for the schedule.";
  if (f.schedule_enabled !== o.schedule_enabled) body.schedule_enabled = f.schedule_enabled;
  if (f.schedule_cron.trim() !== (d.schedule_cron ?? "")) body.schedule_cron = f.schedule_cron.trim() || null;
  if (f.schedule_tz !== d.schedule_tz && (f.schedule_enabled || f.schedule_cron)) body.schedule_tz = f.schedule_tz;
  if (d.kind === "rest") {
    if (f.rest_url !== o.rest_url || f.rest_records_path !== o.rest_records_path) {
      body.rest = { url: f.rest_url.trim(), records_path: f.rest_records_path.trim() || null };
    }
    if (f.rest_headers.trim()) {
      const h = parseHeaders(f.rest_headers);
      if (typeof h === "string") return h;
      body.rest_headers = h;
    }
  }
  return body;
}

function Section({ title, description, children }: { title: string; description?: string; children: React.ReactNode }) {
  return (
    <Surface>
      <SurfaceHeader title={title} description={description} />
      <div className="space-y-4 px-5 pb-5">{children}</div>
    </Surface>
  );
}

function SwitchRow({ label, hint, checked, onChange, disabled, id }: { label: string; hint: string; checked: boolean; onChange: (v: boolean) => void; disabled?: boolean; id: string }) {
  return (
    <div className="flex items-start justify-between gap-4 rounded-lg bg-muted/50 px-3.5 py-3">
      <div>
        <label htmlFor={id} className="text-[13px] font-medium">
          {label}
        </label>
        <FieldHint className="mt-0.5">{hint}</FieldHint>
      </div>
      <Switch id={id} checked={checked} onCheckedChange={onChange} disabled={disabled} />
    </div>
  );
}

export function DatasetSettings({ pid, d, canEdit }: { pid: string; d: Dataset; canEdit: boolean }) {
  const router = useRouter();
  const update = useUpdateDataset(pid, d.id);
  const del = useDeleteDataset(pid);
  const { columns } = useDatasetColumns(pid, d);
  const [f, setF] = React.useState<Form>(() => initial(d));
  const [error, setError] = React.useState("");
  const [confirm, setConfirm] = React.useState(false);
  const ro = !canEdit;

  const set = <K extends keyof Form>(k: K, v: Form[K]) => {
    setF((prev) => ({ ...prev, [k]: v }));
    setError("");
  };

  const pending = diff(d, f);
  const dirty = typeof pending === "string" || Object.keys(pending).length > 0;

  const zones = React.useMemo(() => {
    const set = new Set([browserZone(), d.schedule_tz, ...COMMON_ZONES]);
    return [...set].map((z) => ({ value: z, label: z.replace(/_/g, " ") }));
  }, [d.schedule_tz]);

  function save(e: React.FormEvent) {
    e.preventDefault();
    const body = diff(d, f);
    if (typeof body === "string") {
      setError(body);
      return;
    }
    update.mutate(body, {
      onSuccess: (next) => {
        setF(initial(next));
        toast.success("Dataset settings saved");
      },
      onError: (err) => setError(errorMessage(err)),
    });
  }

  const cronWords = describeCron(f.schedule_cron);

  return (
    <form onSubmit={save} className="space-y-5">
      {ro && (
        <div className="flex items-center gap-2 rounded-xl bg-muted/70 px-4 py-3 text-[13px] text-muted-foreground">
          <LockIcon className="size-4 shrink-0" />
          You can view these settings. Editors and owners of this project can change them.
        </div>
      )}

      <Section title="General">
        <Field label="Name" htmlFor="ds-name">
          <Input id="ds-name" value={f.name} onChange={(e) => set("name", e.target.value)} disabled={ro} maxLength={200} required />
        </Field>
        <Field label="Description" htmlFor="ds-desc" hint="What this data is and who relies on it.">
          <Textarea id="ds-desc" value={f.description} onChange={(e) => set("description", e.target.value)} disabled={ro} rows={2} />
        </Field>
        <Field label="Tags" htmlFor="ds-tags" hint="Up to 20 short labels, for search and grouping.">
          <TagInput id="ds-tags" value={f.tags} onChange={(v) => set("tags", v)} disabled={ro} placeholder="finance, daily, pii" />
        </Field>
      </Section>

      <Section title="What gets scanned" description="Narrow the rows, hide sensitive values, and set how long a scan may take.">
        {d.kind === "query" && (
          <Field label="Query" htmlFor="ds-sql" hint="One read-only SELECT. DataQuality runs it inside the source as a subquery.">
            <Textarea id="ds-sql" value={f.query_sql} onChange={(e) => set("query_sql", e.target.value)} disabled={ro} rows={5} className="font-mono text-[12.5px]" />
          </Field>
        )}
        <Field label="Row filter" htmlFor="ds-filter" hint="An SQL condition applied to every scan, for example created_at > now() - interval '30 days'. Leave empty to scan every row.">
          <Input id="ds-filter" value={f.filter_sql} onChange={(e) => set("filter_sql", e.target.value)} disabled={ro} className="font-mono text-[12.5px]" placeholder="status <> 'test'" />
        </Field>
        <Field label="Masked columns" htmlFor="ds-mask" hint="Their values show as [masked] in previews, failing-row samples and the profile. Checks still run on the real values.">
          <TagInput id="ds-mask" value={f.masked_columns} onChange={(v) => set("masked_columns", v)} disabled={ro} suggestions={columns.map((c) => c.name)} mono placeholder="phone, pan" />
        </Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Scan timeout (seconds)" htmlFor="ds-timeout" hint="A scan that runs longer is stopped and marked failed.">
            <Input id="ds-timeout" type="number" min={10} max={86400} inputMode="numeric" value={f.scan_timeout_s} onChange={(e) => set("scan_timeout_s", e.target.value)} disabled={ro} className="tabular" />
          </Field>
        </div>
        <SwitchRow
          id="ds-profile"
          label="Profile columns on every scan"
          hint="Keeps the Profile tab current and feeds anomaly detection. Turn off for very large tables to save time."
          checked={f.profile_enabled}
          onChange={(v) => set("profile_enabled", v)}
          disabled={ro}
        />
      </Section>

      <Section title="Schedule" description="Scan automatically at set times, in the time zone you choose.">
        <SwitchRow
          id="ds-sched"
          label="Scan on a schedule"
          hint={d.schedule_enabled && d.next_run_at ? `Next run ${formatDateTime(d.next_run_at)} (${formatRelative(d.next_run_at)}).` : "Off: scans run only when someone starts one, or on push."}
          checked={f.schedule_enabled}
          onChange={(v) => {
            set("schedule_enabled", v);
            if (v && !f.schedule_cron) set("schedule_cron", "0 6 * * *");
          }}
          disabled={ro}
        />
        {f.schedule_enabled && (
          <>
            <div className="flex flex-wrap gap-1.5" role="group" aria-label="Schedule presets">
              {PRESETS.map((p) => (
                <button
                  key={p.cron}
                  type="button"
                  disabled={ro}
                  aria-pressed={f.schedule_cron === p.cron}
                  onClick={() => set("schedule_cron", p.cron)}
                  className={cn(
                    "h-7 rounded-full px-3 text-[12.5px] font-medium transition-colors focus-visible:outline-2 focus-visible:outline-ring",
                    f.schedule_cron === p.cron ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground hover:bg-accent hover:text-foreground",
                  )}
                >
                  {p.label}
                </button>
              ))}
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Cron expression" htmlFor="ds-cron" hint={cronWords && cronWords !== f.schedule_cron ? cronWords : "Minute, hour, day of month, month, day of week."}>
                <Input id="ds-cron" value={f.schedule_cron} onChange={(e) => set("schedule_cron", e.target.value)} disabled={ro} className="font-mono" placeholder="0 6 * * *" />
              </Field>
              <Field label="Time zone" htmlFor="ds-tz">
                <SimpleSelect id="ds-tz" value={f.schedule_tz} onValueChange={(v) => set("schedule_tz", v)} options={zones} disabled={ro} />
              </Field>
            </div>
          </>
        )}
      </Section>

      {d.kind === "rest" && (
        <Section title="REST endpoint" description="Where the records are fetched from on each scan.">
          <Field label="URL" htmlFor="ds-url">
            <Input id="ds-url" type="url" value={f.rest_url} onChange={(e) => set("rest_url", e.target.value)} disabled={ro} className="font-mono text-[12.5px]" />
          </Field>
          <Field label="Records path" htmlFor="ds-path" hint="Dotted path to the list of records in the response, like data.items. Empty when the response is the list itself.">
            <Input id="ds-path" value={f.rest_records_path} onChange={(e) => set("rest_records_path", e.target.value)} disabled={ro} className="font-mono text-[12.5px]" placeholder="data.items" />
          </Field>
          {!ro && (
            <Field
              label="Request headers"
              htmlFor="ds-headers"
              hint={d.has_secret ? "Headers are stored sealed and never shown. Enter new ones to replace them, one per line as Name: value." : "One per line as Name: value, for example Authorization: Bearer ... They are stored sealed."}
            >
              <Textarea id="ds-headers" value={f.rest_headers} onChange={(e) => set("rest_headers", e.target.value)} rows={3} className="font-mono text-[12.5px]" placeholder={d.has_secret ? "Leave empty to keep the current headers" : "Authorization: Bearer token"} />
            </Field>
          )}
        </Section>
      )}

      {canEdit && (dirty || !!error) && (
        <div className="sticky bottom-3 z-10 flex flex-col gap-2 rounded-xl bg-card/95 px-4 py-3 shadow-[var(--elev-3)] backdrop-blur sm:flex-row sm:items-center sm:justify-between">
          <p className={cn("text-[13px]", error ? "font-medium text-danger" : "text-muted-foreground")} role={error ? "alert" : undefined}>
            {error || "You have unsaved changes."}
          </p>
          <div className="flex gap-2">
            <Button type="button" variant="ghost" size="sm" disabled={!dirty || update.isPending} onClick={() => setF(initial(d))}>
              Discard
            </Button>
            <Button type="submit" size="sm" disabled={!dirty || update.isPending}>
              {update.isPending ? "Saving..." : "Save changes"}
            </Button>
          </div>
        </div>
      )}

      {canEdit && (
        <div className="rounded-[14px] bg-danger-soft/60 p-5">
          <h2 className="text-[14px] font-semibold text-danger">Delete this dataset</h2>
          <p className="mt-1 max-w-2xl text-[13px] text-muted-foreground">
            Removes the dataset with its checks, scan history, profiles, incidents and uploaded versions. The source data itself is never touched. This cannot be undone.
          </p>
          <Button type="button" variant="destructive" size="sm" className="mt-3" onClick={() => setConfirm(true)}>
            <Trash2Icon />
            Delete dataset
          </Button>
        </div>
      )}

      <ConfirmDialog
        open={confirm}
        onOpenChange={setConfirm}
        title={`Delete ${d.name}?`}
        description="Its checks, scan history, profiles and incidents are deleted with it. The data in the source stays as it is."
        confirmLabel="Delete dataset"
        pending={del.isPending}
        onConfirm={() =>
          del.mutate(d.id, {
            onSuccess: () => {
              toast.success(`Deleted ${d.name}`);
              router.push(`/projects/${pid}/datasets`);
            },
            onError: (err) => toast.error(errorMessage(err)),
          })
        }
      />
    </form>
  );
}
