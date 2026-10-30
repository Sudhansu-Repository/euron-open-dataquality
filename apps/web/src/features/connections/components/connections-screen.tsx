"use client";

import {
  CableIcon,
  CheckCircle2Icon,
  CircleDashedIcon,
  DatabaseIcon,
  MoreHorizontalIcon,
  PencilIcon,
  PlugZapIcon,
  PlusIcon,
  TableIcon,
  Trash2Icon,
  XCircleIcon,
} from "lucide-react";
import * as React from "react";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { PageHeader } from "@/components/page-header";
import { RoleNote } from "@/components/role-note";
import { Button } from "@/components/ui/button";
import { Chip } from "@/components/ui/chip";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Skeleton } from "@/components/ui/skeleton";
import { useCurrentProject } from "@/features/projects/api";
import { errorMessage } from "@/lib/api/errors";
import type { Connection } from "@/lib/api/types";
import { formatBytes, formatNumber, formatRelative } from "@/lib/format";
import { CONNECTION_KINDS } from "@/lib/quality";

import { useConnections, useDeleteConnection, useTestConnection } from "../api";

import { ConnectionDialog, shortVersion } from "./connection-dialog";
import { KindBadge } from "./kind-badge";
import { TableBrowser } from "./table-browser";

export function ConnectionsScreen() {
  const { pid, canEdit, project } = useCurrentProject();
  const q = useConnections(pid);
  const [adding, setAdding] = React.useState(false);
  const [editing, setEditing] = React.useState<Connection | null>(null);
  const [browsing, setBrowsing] = React.useState<Connection | null>(null);
  const [deleting, setDeleting] = React.useState<Connection | null>(null);
  const del = useDeleteConnection(pid);

  function confirmDelete() {
    if (!deleting) return;
    del.mutate(deleting.id, {
      onSuccess: () => {
        toast.success(`${deleting.name} deleted.`);
        setDeleting(null);
      },
      onError: (err) => {
        toast.error(errorMessage(err));
        setDeleting(null);
      },
    });
  }

  const list = q.data ?? [];
  return (
    <>
      <PageHeader
        title="Connections"
        description="Databases this project reads from. Checks run inside them as read-only SELECTs, so rows never leave the source; only counts and a few failing samples come back."
        actions={
          canEdit &&
          list.length > 0 && (
            <Button onClick={() => setAdding(true)}>
              <PlusIcon />
              Add connection
            </Button>
          )
        }
      />
      {project && !canEdit && (
        <RoleNote className="mb-4">You are a viewer in {project.name}: you can see connections and their tables. Editors and owners add and change them.</RoleNote>
      )}
      {q.isPending ? (
        <div className="space-y-3" aria-busy aria-label="Loading connections">
          {Array.from({ length: 2 }).map((_, i) => (
            <Skeleton key={i} className="h-28 w-full rounded-[14px]" />
          ))}
        </div>
      ) : q.isError ? (
        <div className="surface">
          <ErrorState error={q.error} title="Connections could not be loaded" onRetry={() => void q.refetch()} />
        </div>
      ) : list.length === 0 ? (
        <div className="surface">
          <EmptyState
            icon={CableIcon}
            title="No connections yet"
            description="A connection lets DataQuality check tables and queries in PostgreSQL, MySQL, MariaDB, SQL Server or a SQLite file, right where the data lives. Files and APIs need no connection: add them as datasets."
            action={
              canEdit ? (
                <Button onClick={() => setAdding(true)}>
                  <PlusIcon />
                  Add a connection
                </Button>
              ) : undefined
            }
          />
        </div>
      ) : (
        <div className="space-y-3">
          {list.map((c) => (
            <ConnectionRow
              key={c.id}
              pid={pid}
              connection={c}
              canEdit={canEdit}
              onBrowse={() => setBrowsing(c)}
              onEdit={() => setEditing(c)}
              onDelete={() => setDeleting(c)}
            />
          ))}
        </div>
      )}

      <ConnectionDialog pid={pid} open={adding || !!editing} editing={editing} onOpenChange={(o) => {
          if (o) return;
          setAdding(false);
          setEditing(null);
        }}
      />
      <TableBrowser pid={pid} connection={browsing} canEdit={canEdit} onOpenChange={(o) => !o && setBrowsing(null)} />
      <ConfirmDialog
        open={!!deleting}
        onOpenChange={(o) => !o && setDeleting(null)}
        title={`Delete ${deleting?.name ?? "this connection"}?`}
        description={
          deleting?.datasets
            ? `${formatNumber(deleting.datasets)} datasets use it. Delete or move those datasets first; the API refuses to orphan them.`
            : "Its stored password is destroyed. Datasets added later need a new connection."
        }
        confirmLabel="Delete connection"
        pending={del.isPending}
        onConfirm={confirmDelete}
      />
    </>
  );
}

function target(c: Connection): string {
  if (c.kind === "sqlite") return `${c.file_name ?? "database file"}${c.file_size != null ? `, ${formatBytes(c.file_size)}` : ""}`;
  return `${c.host ?? "?"}${c.port ? `:${c.port}` : ""}/${c.database ?? ""}`;
}

function ConnectionRow({
  pid,
  connection: c,
  canEdit,
  onBrowse,
  onEdit,
  onDelete,
}: {
  pid: string;
  connection: Connection;
  canEdit: boolean;
  onBrowse: () => void;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const test = useTestConnection(pid);

  function runTest() {
    test.mutate(c.id, {
      onSuccess: (r) => (r.ok ? toast.success(`${c.name}: ${r.message}`) : toast.error(`${c.name}: ${r.message}`)),
      onError: (err) => toast.error(errorMessage(err)),
    });
  }

  const status =
    c.last_test_ok == null ? (
      <Chip tone="neutral">
        <CircleDashedIcon />
        Not tested
      </Chip>
    ) : c.last_test_ok ? (
      <Chip tone="success">
        <CheckCircle2Icon />
        Connected
      </Chip>
    ) : (
      <Chip tone="danger">
        <XCircleIcon />
        Failing
      </Chip>
    );

  return (
    <section aria-label={c.name} className="surface flex flex-col gap-4 p-4 sm:p-5 md:flex-row md:items-center">
      <div className="flex min-w-0 flex-1 items-start gap-3.5">
        <KindBadge kind={c.kind} className="size-10" />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="truncate text-[14.5px] font-semibold tracking-[-0.01em]">{c.name}</h2>
            {status}
          </div>
          <div className="mt-0.5 flex flex-wrap items-center gap-x-2 text-[12.5px] text-muted-foreground">
            <span>{CONNECTION_KINDS[c.kind] ?? c.kind}</span>
            <span aria-hidden className="text-faint">/</span>
            <span className="min-w-0 truncate font-mono text-[12px]">{target(c)}</span>
          </div>
          <div className="mt-1.5 text-[12px] text-subtle">
            {c.last_tested_at ? (
              <>
                Tested {formatRelative(c.last_tested_at)}
                {c.last_test_message ? `: ${c.last_test_message}` : ""}
              </>
            ) : (
              "Never tested"
            )}
          </div>
        </div>
      </div>
      <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1 text-[12px] md:w-52 md:shrink-0">
        <dt className="text-subtle">Server</dt>
        <dd className="truncate text-right font-medium md:text-left" title={c.server_version ?? undefined}>
          {shortVersion(c.server_version) || "n/a"}
        </dd>
        <dt className="text-subtle">Datasets</dt>
        <dd className="tabular text-right font-medium md:text-left">{formatNumber(c.datasets ?? 0)}</dd>
      </dl>
      <div className="flex shrink-0 items-center gap-2">
        <Button variant="outline" size="sm" onClick={onBrowse}>
          <TableIcon />
          Tables
        </Button>
        {canEdit && (
          <>
            <Button variant="outline" size="sm" onClick={runTest} disabled={test.isPending}>
              <PlugZapIcon />
              {test.isPending ? "Testing..." : "Test"}
            </Button>
            <DropdownMenu>
              <DropdownMenuTrigger render={<Button variant="subtle" size="icon-sm" aria-label={`More actions for ${c.name}`} />}>
                <MoreHorizontalIcon />
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-44">
                {c.kind !== "sqlite" && (
                  <DropdownMenuItem onClick={onEdit}>
                    <PencilIcon />
                    Edit
                  </DropdownMenuItem>
                )}
                <DropdownMenuItem onClick={onBrowse}>
                  <DatabaseIcon />
                  Add a dataset
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem variant="destructive" onClick={onDelete}>
                  <Trash2Icon />
                  Delete
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </>
        )}
      </div>
    </section>
  );
}
