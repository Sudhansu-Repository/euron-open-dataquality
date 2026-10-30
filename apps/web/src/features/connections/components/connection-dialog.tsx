"use client";

import { CheckCircle2Icon, FileUpIcon, PlugZapIcon, XCircleIcon } from "lucide-react";
import * as React from "react";
import { toast } from "sonner";

import { Hint } from "@/components/hint";
import { Button } from "@/components/ui/button";
import { Dialog, DialogBody, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Field, FieldError } from "@/components/ui/label";
import { SimpleSelect } from "@/components/ui/select";
import { errorMessage } from "@/lib/api/errors";
import type { Connection, ConnectionTest, ServerConnection } from "@/lib/api/types";
import { cn } from "@/lib/cn";
import { formatBytes, formatDuration } from "@/lib/format";
import { CONNECTION_KINDS } from "@/lib/quality";

import { useCreateConnection, useCreateSqlite, useTestUnsaved, useUpdateConnection } from "../api";

import { KindBadge } from "./kind-badge";

type ServerKind = ServerConnection["kind"];
type Kind = ServerKind | "sqlite";
type SslMode = NonNullable<ServerConnection["ssl_mode"]>;

export const DEFAULT_PORT: Record<ServerKind, number> = { postgresql: 5432, mysql: 3306, mssql: 1433 };
const KINDS: Kind[] = ["postgresql", "mysql", "mssql", "sqlite"];
const SSL_OPTIONS: { value: SslMode; label: string }[] = [
  { value: "prefer", label: "Prefer (use TLS when offered)" },
  { value: "require", label: "Require TLS" },
  { value: "verify-full", label: "Require TLS and verify the certificate" },
  { value: "disable", label: "Disable (local networks only)" },
];

interface FormState {
  name: string;
  host: string;
  port: string;
  database: string;
  username: string;
  password: string;
  ssl: SslMode;
  schema: string;
  concurrency: string;
}

function initial(c?: Connection | null): FormState {
  return {
    name: c?.name ?? "",
    host: c?.host ?? "",
    port: c?.port != null ? String(c.port) : "",
    database: c?.database ?? "",
    username: c?.username ?? "",
    password: "",
    ssl: (c?.ssl_mode as SslMode | null) ?? "prefer",
    schema: c?.default_schema ?? "",
    concurrency: String(c?.max_concurrent_scans ?? 2),
  };
}

/** Add a connection (any kind), or edit a server connection (kind fixed). */
export function ConnectionDialog({
  pid,
  open,
  onOpenChange,
  editing,
}: {
  pid: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  editing?: Connection | null;
}) {
  const create = useCreateConnection(pid);
  const createSqlite = useCreateSqlite(pid);
  const update = useUpdateConnection(pid);
  const test = useTestUnsaved(pid);
  const [kind, setKind] = React.useState<Kind>("postgresql");
  const [f, setF] = React.useState<FormState>(initial());
  const [file, setFile] = React.useState<File | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [result, setResult] = React.useState<ConnectionTest | null>(null);
  const resetTest = test.reset;

  React.useEffect(() => {
    if (!open) return;
    setKind((editing?.kind as Kind | undefined) ?? "postgresql");
    setF(initial(editing));
    setFile(null);
    setError(null);
    setResult(null);
    resetTest();
  }, [open, editing, resetTest]);

  const set = <K extends keyof FormState>(key: K, value: FormState[K]) => {
    setF((s) => ({ ...s, [key]: value }));
    setResult(null);
  };
  const pending = create.isPending || createSqlite.isPending || update.isPending;
  const serverKind = kind === "sqlite" ? null : kind;
  const isEdit = !!editing;

  function body(): ServerConnection | string {
    if (!serverKind) return "Choose a database kind.";
    if (!f.name.trim()) return "Name the connection, for example Warehouse or Shop replica.";
    if (!f.host.trim()) return "Enter the host name or IP address of the database server.";
    if (!f.database.trim()) return "Enter the database to connect to.";
    if (!f.username.trim()) return "Enter the login name. A read-only login is best.";
    const port = f.port.trim() ? Number(f.port) : DEFAULT_PORT[serverKind];
    if (!Number.isInteger(port) || port < 1 || port > 65535) return "The port must be a whole number from 1 to 65535.";
    const conc = Number(f.concurrency);
    if (!Number.isInteger(conc) || conc < 1 || conc > 16) return "Concurrent scans must be a whole number from 1 to 16.";
    return {
      name: f.name.trim(),
      kind: serverKind,
      host: f.host.trim(),
      port,
      database: f.database.trim(),
      username: f.username.trim(),
      password: f.password || null,
      ssl_mode: f.ssl,
      default_schema: f.schema.trim() || null,
      max_concurrent_scans: conc,
    };
  }

  function runTest() {
    const b = body();
    if (typeof b === "string") return setError(b);
    setError(null);
    test.mutate(b, { onSuccess: setResult, onError: (e) => setError(errorMessage(e)) });
  }

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (kind === "sqlite") {
      if (!f.name.trim()) return setError("Name the connection.");
      if (!file) return setError("Choose a SQLite database file (.db, .sqlite or .sqlite3).");
      setError(null);
      createSqlite.mutate(
        { name: f.name.trim(), file },
        {
          onSuccess: (c) => {
            toast.success(`${c.name} is connected. Browse its tables to add datasets.`);
            onOpenChange(false);
          },
          onError: (err) => setError(errorMessage(err)),
        },
      );
      return;
    }
    const b = body();
    if (typeof b === "string") return setError(b);
    setError(null);
    if (editing) {
      const { kind: _kind, password, ...rest } = b;
      update.mutate(
        { cid: editing.id, body: { ...rest, ...(password ? { password } : {}) } },
        {
          onSuccess: (c) => {
            toast.success(`${c.name} saved.`);
            onOpenChange(false);
          },
          onError: (err) => setError(errorMessage(err)),
        },
      );
      return;
    }
    create.mutate(b, {
      onSuccess: (c) => {
        toast.success(c.last_test_ok === false ? `${c.name} saved, but the last test failed. Test it again from the list.` : `${c.name} is connected.`);
        onOpenChange(false);
      },
      onError: (err) => setError(errorMessage(err)),
    });
  }

  const canTest = !!serverKind && (!isEdit || !!f.password);

  return (
    <Dialog open={open} onOpenChange={(o) => !pending && onOpenChange(o)}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>{isEdit ? `Edit ${editing?.name}` : "Add a connection"}</DialogTitle>
          <DialogDescription>
            {isEdit
              ? "Leave the password empty to keep the current one."
              : "Checks run inside this database: rows are counted there, and only failing samples come back."}
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="flex min-h-0 flex-col" noValidate>
          <DialogBody className="space-y-5">
            {!isEdit && (
              <div role="radiogroup" aria-label="Database kind" className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                {KINDS.map((k) => (
                  <button
                    key={k}
                    type="button"
                    role="radio"
                    aria-checked={kind === k}
                    onClick={() => {
                      setKind(k);
                      setResult(null);
                      setError(null);
                    }}
                    className={cn(
                      "flex flex-col items-center gap-2 rounded-xl bg-muted px-2 py-3 text-[12.5px] font-medium text-muted-foreground transition-[color,background-color,box-shadow] hover:text-foreground focus-visible:outline-2 focus-visible:outline-ring",
                      kind === k && "bg-primary-soft text-foreground ring-2 ring-primary/50",
                    )}
                  >
                    <KindBadge kind={k} />
                    <span className="text-center leading-tight">{k === "sqlite" ? "SQLite file" : CONNECTION_KINDS[k]}</span>
                  </button>
                ))}
              </div>
            )}

            <Field label="Name" htmlFor="cn-name">
              <Input id="cn-name" maxLength={120} placeholder={kind === "sqlite" ? "Local sample" : "Warehouse"} value={f.name} onChange={(e) => set("name", e.target.value)} />
            </Field>

            {kind === "sqlite" ? (
              <SqliteFile file={file} onFile={setFile} />
            ) : (
              <>
                <div className="grid gap-4 sm:grid-cols-[minmax(0,1fr)_7rem]">
                  <Field label="Host" htmlFor="cn-host">
                    <Input id="cn-host" autoComplete="off" placeholder="db.internal" value={f.host} onChange={(e) => set("host", e.target.value)} />
                  </Field>
                  <Field label="Port" htmlFor="cn-port">
                    <Input id="cn-port" inputMode="numeric" placeholder={serverKind ? String(DEFAULT_PORT[serverKind]) : ""} value={f.port} onChange={(e) => set("port", e.target.value)} />
                  </Field>
                </div>
                <div className="grid gap-4 sm:grid-cols-2">
                  <Field label="Database" htmlFor="cn-db">
                    <Input id="cn-db" autoComplete="off" value={f.database} onChange={(e) => set("database", e.target.value)} />
                  </Field>
                  <Field label="Default schema" htmlFor="cn-schema" hint="Optional. Where unqualified tables are looked up.">
                    <Input id="cn-schema" autoComplete="off" placeholder={kind === "postgresql" ? "public" : kind === "mssql" ? "dbo" : ""} value={f.schema} onChange={(e) => set("schema", e.target.value)} />
                  </Field>
                </div>
                <div className="grid gap-4 sm:grid-cols-2">
                  <Field label="Username" htmlFor="cn-user">
                    <Input id="cn-user" autoComplete="off" value={f.username} onChange={(e) => set("username", e.target.value)} />
                  </Field>
                  <Field
                    label="Password"
                    htmlFor="cn-pw"
                    hint={isEdit ? (editing?.has_password ? "A password is stored. Type to replace it." : "No password stored.") : "Stored sealed, never shown again."}
                  >
                    <Input id="cn-pw" type="password" autoComplete="new-password" value={f.password} onChange={(e) => set("password", e.target.value)} />
                  </Field>
                </div>
                <div className="grid gap-4 sm:grid-cols-[minmax(0,1fr)_9rem]">
                  <Field label="SSL" htmlFor="cn-ssl">
                    <SimpleSelect id="cn-ssl" value={f.ssl} onValueChange={(v) => set("ssl", (v || "prefer") as SslMode)} options={SSL_OPTIONS} />
                  </Field>
                  <Field
                    label="Concurrent scans"
                    htmlFor="cn-conc"
                    labelExtra={<Hint text="How many scans may query this database at the same time. Keep it low on a busy production server; more scans wait in the queue." />}
                  >
                    <Input id="cn-conc" inputMode="numeric" value={f.concurrency} onChange={(e) => set("concurrency", e.target.value)} />
                  </Field>
                </div>
              </>
            )}

            <div className="flex items-start gap-2.5 rounded-xl bg-muted px-4 py-3 text-[12.5px] leading-relaxed text-muted-foreground">
              <PlugZapIcon className="mt-0.5 size-4 shrink-0 text-subtle" aria-hidden />
              <span>
                Use a read-only login. DataQuality only ever runs SELECT statements, in a read-only session where the database
                supports one. <Hint term="readOnly" className="ml-0.5 inline-flex align-[-2px]" />
              </span>
            </div>

            {result && <TestResultLine result={result} />}
            {error && <FieldError>{error}</FieldError>}
          </DialogBody>
          <DialogFooter className="sm:justify-between">
            {serverKind ? (
              <Button type="button" variant="outline" onClick={runTest} disabled={!canTest || test.isPending || pending} title={canTest ? undefined : "Type the password to test the changed settings"}>
                <PlugZapIcon />
                {test.isPending ? "Testing..." : "Test connection"}
              </Button>
            ) : (
              <span />
            )}
            <div className="flex flex-col-reverse gap-2 sm:flex-row">
              <Button type="button" variant="ghost" onClick={() => onOpenChange(false)} disabled={pending}>
                Cancel
              </Button>
              <Button type="submit" disabled={pending}>
                {pending ? (kind === "sqlite" ? "Uploading..." : "Saving...") : isEdit ? "Save changes" : kind === "sqlite" ? "Upload and connect" : "Save connection"}
              </Button>
            </div>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function TestResultLine({ result }: { result: ConnectionTest }) {
  return (
    <div
      role="status"
      className={cn(
        "flex items-start gap-2.5 rounded-xl px-4 py-3 text-[13px] leading-relaxed",
        result.ok ? "bg-pass-soft text-pass" : "bg-fail-soft text-fail",
      )}
    >
      {result.ok ? <CheckCircle2Icon className="mt-0.5 size-4 shrink-0" /> : <XCircleIcon className="mt-0.5 size-4 shrink-0" />}
      <div className="min-w-0">
        <div className="font-medium">{result.message}</div>
        <div className="text-[12px] opacity-80">
          {[result.server_version ? shortVersion(result.server_version) : null, `${formatDuration(result.ms)}`].filter(Boolean).join(", ")}
        </div>
      </div>
    </div>
  );
}

/** "PostgreSQL 16.10 on aarch64-unknown-linux..." becomes "PostgreSQL 16.10". */
export function shortVersion(v: string | null | undefined): string {
  if (!v) return "";
  const cut = v.split(/\s+on\s+|,|\(/)[0] ?? v;
  return cut.trim().split(/\s+/).slice(0, 3).join(" ");
}

function SqliteFile({ file, onFile }: { file: File | null; onFile: (f: File | null) => void }) {
  const input = React.useRef<HTMLInputElement>(null);
  const [over, setOver] = React.useState(false);
  return (
    <div>
      <input
        ref={input}
        type="file"
        accept=".db,.sqlite,.sqlite3,application/vnd.sqlite3,application/x-sqlite3"
        className="sr-only"
        tabIndex={-1}
        aria-hidden
        onChange={(e) => onFile(e.target.files?.[0] ?? null)}
      />
      <button
        type="button"
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
          "flex w-full flex-col items-center gap-2 rounded-xl bg-muted px-4 py-6 text-center transition-colors hover:bg-accent focus-visible:outline-2 focus-visible:outline-ring",
          over && "bg-primary-soft ring-2 ring-primary/50",
        )}
      >
        <FileUpIcon className="size-5 text-primary" aria-hidden />
        {file ? (
          <span className="text-[13px] font-medium">
            {file.name} <span className="font-normal text-muted-foreground">({formatBytes(file.size)})</span>
          </span>
        ) : (
          <span className="text-[13px] font-medium">Drop a SQLite file here, or click to choose one</span>
        )}
        <span className="text-[12px] text-muted-foreground">.db, .sqlite or .sqlite3. The file is stored and opened read-only.</span>
      </button>
    </div>
  );
}
