"use client";

import { useMutation } from "@tanstack/react-query";
import {
  ArrowLeftIcon,
  ArrowRightIcon,
  CableIcon,
  CodeIcon,
  FileUpIcon,
  GlobeIcon,
  KeyRoundIcon,
  SendIcon,
  TableIcon,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import * as React from "react";
import { toast } from "sonner";

import { CopyButton } from "@/components/copy-button";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { PageHeader } from "@/components/page-header";
import { RoleNote } from "@/components/role-note";
import { Button, buttonVariants } from "@/components/ui/button";
import { Input, Textarea } from "@/components/ui/input";
import { Field, FieldError, FieldHint } from "@/components/ui/label";
import { SimpleSelect } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { useConnections, useTables } from "@/features/connections/api";
import { useCurrentProject } from "@/features/projects/api";
import { useFirstScan } from "@/hooks/use-first-scan";
import { api, unwrap } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";
import type { Dataset, DatasetCreate, DatasetUpdate } from "@/lib/api/types";
import { cn } from "@/lib/cn";
import { formatBytes } from "@/lib/format";

import { useCreateDataset, useUploadFile } from "../api";

type Source = "table" | "query" | "file" | "rest" | "push";

const SOURCES: { id: Source; icon: LucideIcon; title: string; body: string }[] = [
  { id: "table", icon: TableIcon, title: "Database table", body: "A table or view in one of this project's connections." },
  { id: "query", icon: CodeIcon, title: "SQL query", body: "A read-only SELECT, checked as if it were a table." },
  { id: "file", icon: FileUpIcon, title: "Upload a file", body: "CSV, TSV, JSON, NDJSON, Parquet or Excel." },
  { id: "rest", icon: GlobeIcon, title: "REST API", body: "Records fetched from a JSON endpoint on every scan." },
  { id: "push", icon: SendIcon, title: "Push from your app", body: "Your code sends batches through the API and gets them validated." },
];

const FILE_ACCEPT = ".csv,.tsv,.txt,.json,.ndjson,.jsonl,.parquet,.xlsx,.xls";
const DELIMITERS = [
  { value: "auto", label: "Detect automatically" },
  { value: ",", label: "Comma ( , )" },
  { value: ";", label: "Semicolon ( ; )" },
  { value: "\t", label: "Tab" },
  { value: "|", label: "Pipe ( | )" },
];

function isSource(v: string | null): v is Source {
  return !!v && SOURCES.some((s) => s.id === v);
}

/** The local time zone, for a daily schedule that runs at the time people expect. */
function localZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}

/** "06:30" becomes the five-field cron "30 6 * * *". */
export function dailyCron(time: string): string | null {
  const m = /^(\d{1,2}):(\d{2})$/.exec(time);
  if (!m) return null;
  const h = Number(m[1]);
  const min = Number(m[2]);
  if (h > 23 || min > 59) return null;
  return `${min} ${h} * * *`;
}

/** Settings a file upload cannot carry (description, schedule), applied right after it. */
function usePatchDataset(pid: string) {
  return useMutation({
    mutationFn: ({ did, body }: { did: string; body: DatasetUpdate }) =>
      unwrap(api.PATCH("/api/v1/projects/{project_id}/datasets/{dataset_id}", { params: { path: { project_id: pid, dataset_id: did } }, body })),
  });
}

export function NewDatasetScreen() {
  const { pid, canEdit, project, query } = useCurrentProject();
  const params = useSearchParams();
  const router = useRouter();
  const initialSource = params.get("source");
  const [source, setSource] = React.useState<Source | null>(isSource(initialSource) ? initialSource : null);

  const header = (
    <PageHeader
      eyebrow={
        <Link href={`/projects/${pid}/datasets`} className="inline-flex items-center gap-1 text-[12.5px] font-medium text-muted-foreground hover:text-foreground">
          <ArrowLeftIcon className="size-3.5" />
          Datasets
        </Link>
      }
      title="Add a dataset"
      description="A dataset is anything DataQuality checks: a table, a query, a file, an API or records your app sends. Its first scan profiles every column and suggests checks."
    />
  );

  if (query.isPending) {
    return (
      <>
        {header}
        <Skeleton className="h-72 w-full rounded-[14px]" />
      </>
    );
  }
  if (query.isError) {
    return (
      <>
        {header}
        <div className="surface">
          <ErrorState error={query.error} title="This project could not be loaded" onRetry={() => void query.refetch()} />
        </div>
      </>
    );
  }
  if (!canEdit) {
    return (
      <>
        {header}
        <RoleNote>
          You are a viewer in {project?.name ?? "this project"}, so you can browse datasets and results but not add them. Ask an
          owner to make you an editor if you need to.
        </RoleNote>
        <Link href={`/projects/${pid}/datasets`} className={buttonVariants({ variant: "outline", className: "mt-4" })}>
          Back to datasets
        </Link>
      </>
    );
  }

  return (
    <>
      {header}
      <ol className="mb-5 flex items-center gap-2 text-[12.5px] font-medium" aria-label="Steps">
        <Step n={1} label="Choose a source" active={!source} done={!!source} onClick={source ? () => setSource(null) : undefined} />
        <span aria-hidden className="h-px w-6 bg-border" />
        <Step n={2} label="Describe it" active={!!source} />
      </ol>
      {!source ? (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {SOURCES.map((s) => (
            <button
              key={s.id}
              type="button"
              onClick={() => setSource(s.id)}
              className="surface group flex items-start gap-3.5 p-5 text-left transition-shadow outline-none hover:shadow-[var(--elev-3)] focus-visible:ring-2 focus-visible:ring-ring"
            >
              <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-primary-soft text-primary">
                <s.icon className="size-5" />
              </span>
              <span className="min-w-0 flex-1">
                <span className="flex items-center gap-1.5 text-[14px] font-semibold">
                  {s.title}
                  <ArrowRightIcon className="size-3.5 text-subtle opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100" />
                </span>
                <span className="mt-0.5 block text-[12.5px] leading-relaxed text-muted-foreground">{s.body}</span>
              </span>
            </button>
          ))}
        </div>
      ) : (
        <SourceForm key={source} pid={pid} source={source} onBack={() => setSource(null)} onDone={(path) => router.push(path)} />
      )}
    </>
  );
}

function Step({ n, label, active, done, onClick }: { n: number; label: string; active?: boolean; done?: boolean; onClick?: () => void }) {
  const inner = (
    <>
      <span
        className={cn(
          "flex size-5 items-center justify-center rounded-full text-[11px] font-semibold",
          active ? "bg-primary text-primary-foreground" : done ? "bg-primary-soft text-primary" : "bg-muted text-subtle",
        )}
      >
        {n}
      </span>
      <span className={active ? "text-foreground" : "text-muted-foreground"}>{label}</span>
    </>
  );
  return (
    <li className="flex items-center gap-2" aria-current={active ? "step" : undefined}>
      {onClick ? (
        <button type="button" onClick={onClick} className="flex items-center gap-2 rounded-md hover:underline focus-visible:outline-2 focus-visible:outline-ring">
          {inner}
        </button>
      ) : (
        inner
      )}
    </li>
  );
}

interface Common {
  name: string;
  description: string;
  scheduled: boolean;
  time: string;
}

function SourceForm({ pid, source, onBack, onDone }: { pid: string; source: Source; onBack: () => void; onDone: (path: string) => void }) {
  const create = useCreateDataset(pid);
  const upload = useUploadFile(pid);
  const patch = usePatchDataset(pid);
  const first = useFirstScan(pid);
  const params = useSearchParams();
  const [common, setCommon] = React.useState<Common>({ name: "", description: "", scheduled: false, time: "06:00" });
  const [connectionId, setConnectionId] = React.useState(params.get("connection") ?? "");
  const [table, setTable] = React.useState("");
  const [sql, setSql] = React.useState("");
  const [file, setFile] = React.useState<File | null>(null);
  const [sheet, setSheet] = React.useState("");
  const [delimiter, setDelimiter] = React.useState("auto");
  const [url, setUrl] = React.useState("");
  const [recordsPath, setRecordsPath] = React.useState("");
  const [auth, setAuth] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const [pushed, setPushed] = React.useState<Dataset | null>(null);
  const nameTouched = React.useRef(false);

  const setName = (v: string, auto = false) => {
    if (!auto) nameTouched.current = true;
    if (auto && nameTouched.current) return;
    setCommon((c) => ({ ...c, name: v }));
  };
  const pending = create.isPending || upload.isPending || patch.isPending || first.isPending;
  const meta = SOURCES.find((s) => s.id === source) as (typeof SOURCES)[number];

  function schedule(): Pick<DatasetCreate, "schedule_cron" | "schedule_tz" | "schedule_enabled"> | string {
    if (!common.scheduled) return {};
    const cron = dailyCron(common.time);
    if (!cron) return "Pick a time of day for the daily scan, like 06:00.";
    return { schedule_cron: cron, schedule_tz: localZone(), schedule_enabled: true };
  }

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const sched = schedule();
    if (typeof sched === "string") return setError(sched);
    const description = common.description.trim() || null;

    if (source === "file") {
      if (!file) return setError("Choose a file to upload.");
      setError(null);
      upload.mutate(
        { file, name: common.name.trim() || undefined, sheet: sheet.trim() || undefined, delimiter: delimiter === "auto" ? undefined : delimiter },
        {
          onSuccess: (d) => {
            const extra: DatasetUpdate = { ...sched, ...(description ? { description } : {}) };
            if (Object.keys(extra).length) {
              patch.mutate(
                { did: d.id, body: extra },
                { onSettled: () => void first.start(d), onError: (err) => toast.error(`The file was added, but its settings were not saved: ${errorMessage(err)}`) },
              );
            } else {
              void first.start(d);
            }
          },
          onError: (err) => setError(errorMessage(err)),
        },
      );
      return;
    }

    const name = common.name.trim();
    if (!name) return setError("Name the dataset, the way people on your team would call it.");
    let body: DatasetCreate;
    if (source === "table") {
      if (!connectionId) return setError("Choose a connection.");
      if (!table) return setError("Choose a table or view.");
      const [schema, tableName] = JSON.parse(table) as [string | null, string];
      body = { name, kind: "table", connection_id: connectionId, schema_name: schema, table_name: tableName };
    } else if (source === "query") {
      if (!connectionId) return setError("Choose a connection.");
      if (!sql.trim()) return setError("Write the SELECT query to check.");
      body = { name, kind: "query", connection_id: connectionId, query_sql: sql.trim() };
    } else if (source === "rest") {
      if (!/^https?:\/\//i.test(url.trim())) return setError("Enter the full address, starting with https:// (or http:// on a local network).");
      body = {
        name,
        kind: "rest",
        rest: { url: url.trim(), records_path: recordsPath.trim() || null },
        ...(auth.trim() ? { rest_headers: { Authorization: auth.trim() } } : {}),
      };
    } else {
      body = { name, kind: "push" };
    }
    setError(null);
    create.mutate(
      { ...body, description, ...(source === "push" ? {} : sched) },
      {
        onSuccess: (d) => {
          if (source === "push") {
            toast.success(`${d.name} is ready to receive records.`);
            setPushed(d);
          } else {
            void first.start(d);
          }
        },
        onError: (err) => setError(errorMessage(err)),
      },
    );
  }

  if (pushed) return <PushReady pid={pid} dataset={pushed} onOpen={() => onDone(`/projects/${pid}/datasets/${pushed.id}`)} />;

  return (
    <form onSubmit={submit} noValidate className="surface max-w-3xl">
      <div className="flex items-center gap-3 px-5 pt-5 pb-4 sm:px-6">
        <span className="flex size-9 items-center justify-center rounded-xl bg-primary-soft text-primary">
          <meta.icon className="size-4.5" />
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="text-[15px] font-semibold tracking-[-0.01em]">{meta.title}</h2>
          <p className="text-[12.5px] text-muted-foreground">{meta.body}</p>
        </div>
        <Button type="button" variant="subtle" size="sm" onClick={onBack} disabled={pending}>
          Change
        </Button>
      </div>
      <div className="space-y-5 px-5 pb-6 sm:px-6">
        {(source === "table" || source === "query") && (
          <ConnectionFields
            pid={pid}
            source={source}
            connectionId={connectionId}
            onConnection={(id) => {
              setConnectionId(id);
              setTable("");
            }}
            table={table}
            onTable={(key, label) => {
              setTable(key);
              setName(label, true);
            }}
          />
        )}
        {source === "query" && (
          <Field
            label="Query"
            htmlFor="nd-sql"
            hint="A single SELECT (WITH is fine). Anything that could change data is refused before it reaches the database."
          >
            <Textarea
              id="nd-sql"
              spellCheck={false}
              className="min-h-36 font-mono text-[12.5px]"
              placeholder={"SELECT order_id, customer_id, total, created_at\nFROM orders\nWHERE created_at >= CURRENT_DATE - 30"}
              value={sql}
              onChange={(e) => setSql(e.target.value)}
            />
          </Field>
        )}
        {source === "file" && (
          <FileFields
            file={file}
            onFile={(f) => {
              setFile(f);
              if (f) setName(f.name.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " "), true);
            }}
            sheet={sheet}
            onSheet={setSheet}
            delimiter={delimiter}
            onDelimiter={setDelimiter}
            uploading={upload.isPending}
          />
        )}
        {source === "rest" && (
          <>
            <Field label="URL" htmlFor="nd-url" hint="Fetched with GET on every scan. It must answer with JSON.">
              <Input id="nd-url" type="url" inputMode="url" placeholder="https://api.example.com/v1/orders" value={url} onChange={(e) => setUrl(e.target.value)} />
            </Field>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Records path" htmlFor="nd-path" hint="Where the list of records sits in the response, like data.items. Empty when the response is the list.">
                <Input id="nd-path" className="font-mono text-[13px]" placeholder="data.items" value={recordsPath} onChange={(e) => setRecordsPath(e.target.value)} />
              </Field>
              <Field
                label="Authorization header"
                htmlFor="nd-auth"
                hint="Optional, like Bearer abc123. Stored sealed and never shown again."
              >
                <div className="relative">
                  <KeyRoundIcon className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-faint" />
                  <Input id="nd-auth" type="password" autoComplete="off" className="pl-9" value={auth} onChange={(e) => setAuth(e.target.value)} />
                </div>
              </Field>
            </div>
          </>
        )}
        {source === "push" && (
          <p className="rounded-xl bg-muted px-4 py-3 text-[13px] leading-relaxed text-muted-foreground">
            Your application sends batches of records to an endpoint; each batch is stored as the newest version, scanned, and
            the result comes back in the same response. After you name it, you get the endpoint and a ready-to-run example.
          </p>
        )}

        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Name" htmlFor="nd-name" hint={source === "file" ? "Optional. Defaults to the file name." : undefined}>
            <Input id="nd-name" maxLength={120} value={common.name} onChange={(e) => setName(e.target.value)} />
          </Field>
          <Field label="Description" htmlFor="nd-desc" hint="Optional. What it holds and who owns it.">
            <Input id="nd-desc" maxLength={2000} value={common.description} onChange={(e) => setCommon((c) => ({ ...c, description: e.target.value }))} />
          </Field>
        </div>

        {source !== "push" && (
          <div className="flex flex-wrap items-center gap-x-4 gap-y-3 rounded-xl bg-muted/70 px-4 py-3">
            <label className="flex min-w-0 flex-1 items-start gap-3">
              <Switch checked={common.scheduled} onCheckedChange={(v) => setCommon((c) => ({ ...c, scheduled: v }))} aria-label="Scan every day" className="mt-0.5" />
              <span>
                <span className="block text-[13px] font-medium">Scan every day</span>
                <span className="block text-[12px] text-muted-foreground">
                  {common.scheduled ? `At this time, ${localZone()} time. Change it later in the dataset's settings.` : "Off: scans run when you or your CI start them."}
                </span>
              </span>
            </label>
            {common.scheduled && (
              <Input
                type="time"
                aria-label="Time of the daily scan"
                className="w-32"
                value={common.time}
                onChange={(e) => setCommon((c) => ({ ...c, time: e.target.value }))}
              />
            )}
          </div>
        )}

        {error && <FieldError>{error}</FieldError>}
      </div>
      <div className="flex flex-col-reverse gap-2 rounded-b-[14px] bg-muted/50 px-5 py-3.5 sm:flex-row sm:items-center sm:justify-between sm:px-6">
        <FieldHint>{source === "push" ? "Nothing is scanned until your app sends a first batch." : "Next: the first scan profiles it and suggests checks."}</FieldHint>
        <div className="flex flex-col-reverse gap-2 sm:flex-row">
          <Button type="button" variant="ghost" onClick={onBack} disabled={pending}>
            Back
          </Button>
          <Button type="submit" disabled={pending}>
            {pending
              ? source === "file" && upload.isPending
                ? "Uploading..."
                : first.isPending
                  ? "Starting the first scan..."
                  : "Adding..."
              : source === "push"
                ? "Create push dataset"
                : "Add and scan"}
            {!pending && <ArrowRightIcon />}
          </Button>
        </div>
      </div>
    </form>
  );
}

function ConnectionFields({
  pid,
  source,
  connectionId,
  onConnection,
  table,
  onTable,
}: {
  pid: string;
  source: "table" | "query";
  connectionId: string;
  onConnection: (id: string) => void;
  table: string;
  onTable: (key: string, label: string) => void;
}) {
  const connections = useConnections(pid);
  const tables = useTables(pid, source === "table" && connectionId ? connectionId : undefined);

  if (connections.isPending) return <Skeleton className="h-16 w-full" />;
  if (connections.isError) return <ErrorState compact error={connections.error} title="Connections could not be loaded" onRetry={() => void connections.refetch()} />;
  if (!connections.data.length) {
    return (
      <div className="rounded-xl bg-muted">
        <EmptyState
          compact
          icon={CableIcon}
          title="No connection yet"
          description="Tables and queries are read through a connection to your database. Add one first, then come back here."
          action={
            <Link href={`/projects/${pid}/connections`} className={buttonVariants({ size: "sm" })}>
              Add a connection
            </Link>
          }
        />
      </div>
    );
  }
  const tableOptions = (tables.data ?? []).map((t) => ({
    value: JSON.stringify([t.schema_name, t.name]),
    label: (
      <span className="font-mono text-[12.5px]">
        {t.schema_name ? <span className="text-muted-foreground">{t.schema_name}.</span> : null}
        {t.name}
        {t.kind.toLowerCase().includes("view") ? <span className="ml-1.5 font-sans text-[11px] text-subtle">view</span> : null}
      </span>
    ),
  }));
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <Field label="Connection" htmlFor="nd-conn">
        <SimpleSelect
          id="nd-conn"
          value={connectionId}
          onValueChange={onConnection}
          placeholder="Choose a connection"
          options={connections.data.map((c) => ({ value: c.id, label: c.name }))}
        />
      </Field>
      {source === "table" && (
        <Field
          label="Table or view"
          htmlFor="nd-table"
          error={tables.isError ? errorMessage(tables.error) : undefined}
          hint={connectionId && tables.data ? `${tables.data.length} tables and views visible to this login.` : undefined}
        >
          <SimpleSelect
            id="nd-table"
            value={table}
            disabled={!connectionId || tables.isPending}
            onValueChange={(v) => v && onTable(v, (JSON.parse(v) as [string | null, string])[1])}
            placeholder={!connectionId ? "Choose a connection first" : tables.isPending ? "Loading tables..." : "Choose a table"}
            options={tableOptions}
          />
        </Field>
      )}
    </div>
  );
}

function FileFields({
  file,
  onFile,
  sheet,
  onSheet,
  delimiter,
  onDelimiter,
  uploading,
}: {
  file: File | null;
  onFile: (f: File | null) => void;
  sheet: string;
  onSheet: (v: string) => void;
  delimiter: string;
  onDelimiter: (v: string) => void;
  uploading: boolean;
}) {
  const input = React.useRef<HTMLInputElement>(null);
  const [over, setOver] = React.useState(false);
  const ext = file?.name.split(".").pop()?.toLowerCase() ?? "";
  const excel = ext === "xlsx" || ext === "xls";
  const delimited = ext === "csv" || ext === "tsv" || ext === "txt";
  return (
    <div className="space-y-4">
      <input ref={input} type="file" accept={FILE_ACCEPT} className="sr-only" tabIndex={-1} aria-hidden onChange={(e) => onFile(e.target.files?.[0] ?? null)} />
      <button
        type="button"
        disabled={uploading}
        onClick={() => input.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setOver(false);
          onFile(e.dataTransfer.files?.[0] ?? null);
        }}
        className={cn(
          "relative flex w-full flex-col items-center gap-2 overflow-hidden rounded-xl bg-muted px-4 py-9 text-center transition-colors hover:bg-accent focus-visible:outline-2 focus-visible:outline-ring disabled:cursor-progress",
          over && "bg-primary-soft ring-2 ring-primary/50",
        )}
      >
        <span className="flex size-11 items-center justify-center rounded-xl bg-card text-primary shadow-[var(--elev-1)]">
          <FileUpIcon className="size-5" />
        </span>
        {file ? (
          <span className="text-[13.5px] font-medium">
            {file.name} <span className="font-normal text-muted-foreground">({formatBytes(file.size)})</span>
          </span>
        ) : (
          <span className="text-[13.5px] font-medium">Drop a file here, or click to choose one</span>
        )}
        <span className="text-[12px] text-muted-foreground">CSV, TSV, JSON, NDJSON, Parquet or Excel. {file ? "Click to pick a different file." : ""}</span>
        {uploading && (
          <span className="absolute inset-x-0 bottom-0 h-1 overflow-hidden bg-primary-soft" role="progressbar" aria-label="Uploading">
            <span className="block h-full w-1/3 animate-[dq-indeterminate_1.2s_ease-in-out_infinite] rounded-full bg-primary" />
          </span>
        )}
      </button>
      {uploading && <p className="text-[12.5px] text-muted-foreground" role="status">Uploading and reading the file. Large files take a moment.</p>}
      {(excel || delimited) && (
        <div className="grid gap-4 sm:grid-cols-2">
          {excel && (
            <Field label="Sheet" htmlFor="nd-sheet" hint="Optional. The first sheet when empty.">
              <Input id="nd-sheet" placeholder="Sheet1" value={sheet} onChange={(e) => onSheet(e.target.value)} />
            </Field>
          )}
          {delimited && (
            <Field label="Delimiter" htmlFor="nd-delim">
              <SimpleSelect id="nd-delim" value={delimiter} onValueChange={(v) => onDelimiter(v || "auto")} options={DELIMITERS} />
            </Field>
          )}
        </div>
      )}
    </div>
  );
}

function PushReady({ pid, dataset, onOpen }: { pid: string; dataset: Dataset; onOpen: () => void }) {
  const [origin, setOrigin] = React.useState("");
  React.useEffect(() => setOrigin(window.location.origin), []);
  const endpoint = `${origin}/api/v1/projects/${pid}/datasets/${dataset.id}/records`;
  const curl = [
    `curl -X POST "${endpoint}?wait=30" \\`,
    `  -H "X-API-Key: $DQ_API_KEY" \\`,
    `  -H "Content-Type: application/json" \\`,
    `  -d '{"records": [{"order_id": 1, "email": "asha@example.com", "total": 42.5}]}'`,
  ].join("\n");
  return (
    <div className="surface max-w-3xl">
      <div className="px-5 pt-5 pb-4 sm:px-6">
        <h2 className="text-[15px] font-semibold tracking-[-0.01em]">{dataset.name} is ready for records</h2>
        <p className="mt-1 text-[13px] leading-relaxed text-muted-foreground">
          Send a batch of records as JSON. Each batch becomes the newest version, is scanned against the dataset&apos;s checks, and
          the response carries the result (wait up to 120 seconds for it). The first batch also profiles the data, so checks
          are suggested from it.
        </p>
      </div>
      <div className="space-y-4 px-5 pb-6 sm:px-6">
        <div>
          <div className="mb-1.5 flex items-center justify-between gap-2">
            <span className="text-[12px] font-semibold tracking-[0.04em] text-subtle uppercase">Endpoint</span>
            <CopyButton value={endpoint} />
          </div>
          <code className="block overflow-x-auto rounded-lg bg-muted px-3 py-2 font-mono text-[12px] whitespace-nowrap">POST {endpoint}</code>
        </div>
        <div>
          <div className="mb-1.5 flex items-center justify-between gap-2">
            <span className="text-[12px] font-semibold tracking-[0.04em] text-subtle uppercase">Example</span>
            <CopyButton value={curl} />
          </div>
          <pre className="overflow-x-auto rounded-xl bg-code-bg px-4 py-3 font-mono text-[12px] leading-relaxed text-code-fg">{curl}</pre>
        </div>
        <p className="text-[12.5px] leading-relaxed text-muted-foreground">
          The call needs an API key with the <span className="font-medium text-foreground">push</span> scope.{" "}
          <Link href={`/projects/${pid}/settings?tab=api-keys`} className="font-medium text-primary underline-offset-2 hover:underline">
            Create one in project settings
          </Link>{" "}
          (owners), then set it as DQ_API_KEY.
        </p>
      </div>
      <div className="flex justify-end rounded-b-[14px] bg-muted/50 px-5 py-3.5 sm:px-6">
        <Button onClick={onOpen}>
          Open the dataset
          <ArrowRightIcon />
        </Button>
      </div>
    </div>
  );
}
