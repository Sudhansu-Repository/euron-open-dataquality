"use client";

import { EyeIcon, PlusIcon, SearchIcon, TableIcon } from "lucide-react";
import * as React from "react";
import { toast } from "sonner";

import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { Button } from "@/components/ui/button";
import { Chip } from "@/components/ui/chip";
import { Input } from "@/components/ui/input";
import { Sheet, SheetBody, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { useCreateDataset } from "@/features/datasets/api";
import { useFirstScan } from "@/hooks/use-first-scan";
import { errorMessage } from "@/lib/api/errors";
import type { Connection, SourceTable } from "@/lib/api/types";

import { useTables } from "../api";

/** The tables and views a connection can see, each one a click away from being a dataset. */
export function TableBrowser({
  pid,
  connection,
  onOpenChange,
  canEdit,
}: {
  pid: string;
  connection: Connection | null;
  onOpenChange: (open: boolean) => void;
  canEdit: boolean;
}) {
  return (
    <Sheet open={!!connection} onOpenChange={onOpenChange}>
      <SheetContent>
        <SheetHeader>
          <SheetTitle>{connection?.name ?? "Tables"}</SheetTitle>
          <SheetDescription>
            {canEdit ? "Add a table or view as a dataset. Its first scan profiles it and suggests checks." : "Tables and views this connection can read."}
          </SheetDescription>
        </SheetHeader>
        {connection && <TableList pid={pid} connection={connection} canEdit={canEdit} />}
      </SheetContent>
    </Sheet>
  );
}

function TableList({ pid, connection, canEdit }: { pid: string; connection: Connection; canEdit: boolean }) {
  const q = useTables(pid, connection.id);
  const create = useCreateDataset(pid);
  const first = useFirstScan(pid);
  const [search, setSearch] = React.useState("");
  const [busy, setBusy] = React.useState<string | null>(null);

  const term = search.trim().toLowerCase();
  const rows = (q.data ?? []).filter((t) => !term || `${t.schema_name ?? ""}.${t.name}`.toLowerCase().includes(term));

  function add(t: SourceTable) {
    const key = `${t.schema_name ?? ""}.${t.name}`;
    setBusy(key);
    create.mutate(
      { name: t.name, kind: "table", connection_id: connection.id, schema_name: t.schema_name, table_name: t.name },
      {
        onSuccess: (d) => void first.start(d),
        onError: (err) => {
          toast.error(errorMessage(err));
          setBusy(null);
        },
      },
    );
  }

  return (
    <SheetBody className="flex flex-col gap-3">
      <div className="relative">
        <SearchIcon className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-faint" />
        <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search tables" aria-label="Search tables" className="pl-9" />
      </div>
      {q.isPending ? (
        <div className="space-y-2" aria-busy aria-label="Loading tables">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-12 w-full rounded-xl" />
          ))}
        </div>
      ) : q.isError ? (
        <ErrorState compact error={q.error} title="The tables could not be listed" onRetry={() => void q.refetch()} />
      ) : !q.data?.length ? (
        <EmptyState
          compact
          icon={TableIcon}
          title="No tables visible"
          description="This login sees no tables or views. Grant it SELECT on the tables to check, then reopen this list."
        />
      ) : !rows.length ? (
        <EmptyState compact icon={SearchIcon} title="No table matches" description={`Nothing is named like "${search}".`} action={<Button variant="outline" size="sm" onClick={() => setSearch("")}>Clear search</Button>} />
      ) : (
        <ul className="flex flex-col gap-1.5">
          {rows.map((t) => {
            const key = `${t.schema_name ?? ""}.${t.name}`;
            const view = t.kind.toLowerCase().includes("view");
            return (
              <li key={key} className="flex items-center gap-3 rounded-xl bg-muted/60 px-3 py-2.5">
                <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-card text-subtle shadow-[var(--elev-1)]">
                  {view ? <EyeIcon className="size-4" /> : <TableIcon className="size-4" />}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="truncate font-mono text-[13px] font-medium">{t.name}</div>
                  <div className="flex items-center gap-1.5 text-[11.5px] text-muted-foreground">
                    {t.schema_name && <span className="truncate">{t.schema_name}</span>}
                    <Chip tone={view ? "info" : "neutral"}>{view ? "View" : "Table"}</Chip>
                  </div>
                </div>
                {canEdit && (
                  <Button size="xs" variant="outline" onClick={() => add(t)} disabled={busy !== null}>
                    <PlusIcon />
                    {busy === key ? "Adding..." : "Add as dataset"}
                  </Button>
                )}
              </li>
            );
          })}
        </ul>
      )}
      {q.data && q.data.length > 0 && (
        <p className="text-[12px] text-muted-foreground">
          {rows.length} of {q.data.length} tables and views
        </p>
      )}
    </SheetBody>
  );
}
