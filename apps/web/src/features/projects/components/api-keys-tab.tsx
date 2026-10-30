"use client";

import { CheckIcon, KeyRoundIcon, PlusIcon, TriangleAlertIcon } from "lucide-react";
import * as React from "react";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { CopyButton } from "@/components/copy-button";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { Surface, SurfaceHeader } from "@/components/surface";
import { TableSkeleton } from "@/components/table-skeleton";
import { Button } from "@/components/ui/button";
import { Chip } from "@/components/ui/chip";
import { Dialog, DialogBody, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Field, FieldError, Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { errorMessage } from "@/lib/api/errors";
import type { ApiKey, ApiKeyCreated, Scope } from "@/lib/api/types";
import { cn } from "@/lib/cn";
import { formatDate, formatRelative } from "@/lib/format";

import { useApiKeys, useCreateApiKey, useRevokeApiKey } from "../api";

export const SCOPES: { value: Scope; label: string; description: string }[] = [
  { value: "read", label: "Read", description: "Read datasets, checks, scans and incidents." },
  { value: "scan", label: "Scan", description: "Start scans and wait for their result, for CI gates." },
  { value: "push", label: "Push", description: "Send records to push datasets." },
  { value: "manage", label: "Manage", description: "Change datasets and checks, for checks-as-code." },
];

/** How a key is shown after creation: only its prefix is stored. */
export function maskedKey(prefix: string): string {
  return `dq_${prefix}_...`;
}

export function ApiKeysTab({ pid }: { pid: string }) {
  const q = useApiKeys(pid);
  const revoke = useRevokeApiKey(pid);
  const [creating, setCreating] = React.useState(false);
  const [created, setCreated] = React.useState<ApiKeyCreated | null>(null);
  const [revoking, setRevoking] = React.useState<ApiKey | null>(null);
  const list = q.data ?? [];

  return (
    <div className="space-y-4">
      <Surface className="overflow-hidden">
        <SurfaceHeader
          title="API keys"
          description="For CI pipelines, the dq command line and apps that push records. Each key belongs to this project only."
          action={
            list.length > 0 && (
              <Button size="sm" onClick={() => setCreating(true)}>
                <PlusIcon />
                Create key
              </Button>
            )
          }
        />
        {q.isPending ? (
          <TableSkeleton rows={3} cols={4} />
        ) : q.isError ? (
          <ErrorState compact error={q.error} title="API keys could not be loaded" onRetry={() => void q.refetch()} />
        ) : list.length === 0 ? (
          <EmptyState
            compact
            icon={KeyRoundIcon}
            title="No API keys"
            description="Create a key to gate a deploy on a scan, run checks from your CI, or let an app push records for validation."
            action={
              <Button size="sm" onClick={() => setCreating(true)}>
                <PlusIcon />
                Create a key
              </Button>
            }
          />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Key</TableHead>
                <TableHead className="hidden sm:table-cell">Scopes</TableHead>
                <TableHead className="hidden md:table-cell">Last used</TableHead>
                <TableHead className="text-right">Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {list.map((k) => (
                <TableRow key={k.id} className={cn(k.revoked_at && "opacity-55")}>
                  <TableCell>
                    <div className="font-medium">{k.name}</div>
                    <div className="font-mono text-[11.5px] text-muted-foreground">{maskedKey(k.prefix)}</div>
                    <div className="mt-1 flex flex-wrap gap-1 sm:hidden">
                      {k.scopes.map((s) => (
                        <Chip key={s} tone="neutral">
                          {s}
                        </Chip>
                      ))}
                    </div>
                  </TableCell>
                  <TableCell className="hidden sm:table-cell">
                    <div className="flex flex-wrap gap-1">
                      {k.scopes.map((s) => (
                        <Chip key={s} tone="neutral">
                          {s}
                        </Chip>
                      ))}
                    </div>
                  </TableCell>
                  <TableCell className="hidden text-muted-foreground md:table-cell">
                    {k.last_used_at ? formatRelative(k.last_used_at) : "Never"}
                    <div className="text-[11px] text-subtle">Created {formatDate(k.created_at)}</div>
                  </TableCell>
                  <TableCell className="text-right">
                    {k.revoked_at ? (
                      <Chip tone="neutral">Revoked {formatDate(k.revoked_at)}</Chip>
                    ) : (
                      <Button variant="destructive-soft" size="xs" onClick={() => setRevoking(k)}>
                        Revoke
                      </Button>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Surface>
      <CreateKeyDialog
        pid={pid}
        open={creating}
        onOpenChange={setCreating}
        onCreated={(k) => {
          setCreating(false);
          setCreated(k);
        }}
      />
      <KeyCreatedDialog pid={pid} created={created} onClose={() => setCreated(null)} />
      <ConfirmDialog
        open={!!revoking}
        onOpenChange={(o) => !o && setRevoking(null)}
        title={`Revoke ${revoking?.name ?? "this key"}?`}
        description="Anything using it gets 401 from the next request on. This cannot be undone; create a new key to replace it."
        confirmLabel="Revoke key"
        pending={revoke.isPending}
        onConfirm={() =>
          revoking &&
          revoke.mutate(revoking.id, {
            onSuccess: () => {
              toast.success(`${revoking.name} revoked.`);
              setRevoking(null);
            },
            onError: (err) => toast.error(errorMessage(err)),
          })
        }
      />
    </div>
  );
}

function CreateKeyDialog({ pid, open, onOpenChange, onCreated }: { pid: string; open: boolean; onOpenChange: (o: boolean) => void; onCreated: (k: ApiKeyCreated) => void }) {
  const create = useCreateApiKey(pid);
  const [name, setName] = React.useState("");
  const [scopes, setScopes] = React.useState<Scope[]>(["read", "scan"]);
  const [error, setError] = React.useState<string | null>(null);
  React.useEffect(() => {
    if (!open) return;
    setName("");
    setScopes(["read", "scan"]);
    setError(null);
  }, [open]);

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return setError("Name the key after where it is used, like 'GitHub Actions'.");
    if (!scopes.length) return setError("Pick at least one scope.");
    setError(null);
    create.mutate({ name: name.trim(), scopes }, { onSuccess: onCreated, onError: (err) => setError(errorMessage(err)) });
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !create.isPending && onOpenChange(o)}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Create an API key</DialogTitle>
          <DialogDescription>Give it only the scopes it needs. The key is shown once, right after this.</DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="flex min-h-0 flex-col" noValidate>
          <DialogBody className="space-y-4">
            <Field label="Name" htmlFor="ak-name">
              <Input id="ak-name" maxLength={120} placeholder="GitHub Actions" value={name} onChange={(e) => setName(e.target.value)} />
            </Field>
            <div className="space-y-1.5">
              <Label>Scopes</Label>
              <div className="grid gap-2 sm:grid-cols-2">
                {SCOPES.map((s) => {
                  const on = scopes.includes(s.value);
                  return (
                    <button
                      key={s.value}
                      type="button"
                      role="checkbox"
                      aria-checked={on}
                      onClick={() => setScopes((cur) => (on ? cur.filter((x) => x !== s.value) : [...cur, s.value]))}
                      className={cn(
                        "flex items-start gap-2.5 rounded-xl bg-muted px-3 py-2.5 text-left transition-colors hover:bg-accent focus-visible:outline-2 focus-visible:outline-ring",
                        on && "bg-primary-soft hover:bg-primary-soft",
                      )}
                    >
                      <span className={cn("mt-0.5 flex size-4 shrink-0 items-center justify-center rounded ring-1 ring-input", on && "bg-primary text-primary-foreground ring-primary")}>
                        {on && <CheckIcon className="size-3" strokeWidth={3} />}
                      </span>
                      <span>
                        <span className="block text-[13px] font-medium">{s.label}</span>
                        <span className="block text-[12px] leading-snug text-muted-foreground">{s.description}</span>
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>
            {error && <FieldError>{error}</FieldError>}
          </DialogBody>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={create.isPending}>
              {create.isPending ? "Creating..." : "Create key"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function Snippet({ title, code }: { title: string; code: string }) {
  return (
    <div>
      <div className="mb-1.5 flex items-center justify-between gap-2">
        <span className="text-[12px] font-semibold tracking-[0.04em] text-subtle uppercase">{title}</span>
        <CopyButton value={code} />
      </div>
      <pre className="overflow-x-auto rounded-xl bg-code-bg px-4 py-3 font-mono text-[12px] leading-relaxed text-code-fg">{code}</pre>
    </div>
  );
}

function KeyCreatedDialog({ pid, created, onClose }: { pid: string; created: ApiKeyCreated | null; onClose: () => void }) {
  const [origin, setOrigin] = React.useState("");
  React.useEffect(() => setOrigin(window.location.origin), []);
  const key = created?.key ?? "";
  const curl = `curl -X POST -H "X-API-Key: ${key}" \\\n  "${origin}/api/v1/projects/${pid}/datasets/<dataset id>/scans?wait=120"`;
  const cli = `DQ_URL=${origin} DQ_API_KEY=${key} DQ_PROJECT=${pid} \\\n  dq scan <dataset> --fail-on error`;
  return (
    <Dialog open={!!created} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Copy your new key</DialogTitle>
          <DialogDescription>{created?.name}: this is the only time the full key is shown. Store it as a secret in your CI.</DialogDescription>
        </DialogHeader>
        <DialogBody className="space-y-4">
          <div className="flex items-center gap-2 rounded-xl bg-muted p-2 pl-3">
            <code className="min-w-0 flex-1 truncate font-mono text-[12.5px]">{key}</code>
            <CopyButton value={key} variant="default" />
          </div>
          <p className="flex items-start gap-2 text-[12.5px] text-warn">
            <TriangleAlertIcon className="mt-0.5 size-4 shrink-0" aria-hidden />
            Anyone with this key can do what its scopes allow in this project. Revoke it here if it leaks.
          </p>
          <Snippet title="Scan from CI with curl" code={curl} />
          <Snippet title="Or with the dq command line" code={cli} />
          <p className="text-[12px] leading-relaxed text-muted-foreground">
            With --fail-on error the command exits non-zero when an error check fails, so the pipeline stops before bad data
            ships. Find a dataset&apos;s id in its address bar.
          </p>
        </DialogBody>
        <DialogFooter>
          <Button onClick={onClose}>Done</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
