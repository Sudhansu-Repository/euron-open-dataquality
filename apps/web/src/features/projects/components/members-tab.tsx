"use client";

import { Trash2Icon, UserPlusIcon, UsersIcon } from "lucide-react";
import * as React from "react";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { Surface, SurfaceHeader } from "@/components/surface";
import { TableSkeleton } from "@/components/table-skeleton";
import { Button } from "@/components/ui/button";
import { Chip } from "@/components/ui/chip";
import { Input } from "@/components/ui/input";
import { FieldError, FieldHint, Label } from "@/components/ui/label";
import { SimpleSelect } from "@/components/ui/select";
import { usePermissions } from "@/features/auth/api";
import { errorMessage } from "@/lib/api/errors";
import type { Member, ProjectRole } from "@/lib/api/types";
import { formatRelative, initials } from "@/lib/format";
import { PROJECT_ROLE_DESCRIPTION, PROJECT_ROLES } from "@/lib/roles";

import { useAddMember, useMembers, useRemoveMember, useUpdateMember } from "../api";

const label = (r: string) => r.charAt(0).toUpperCase() + r.slice(1);
const ROLE_OPTIONS = PROJECT_ROLES.map((r) => ({ value: r, label: label(r) }));
const ROLE_TONE = { owner: "primary", editor: "info", viewer: "neutral" } as const;

export function MembersTab({ pid, canOwn }: { pid: string; canOwn: boolean }) {
  const q = useMembers(pid);
  const { user } = usePermissions();
  const update = useUpdateMember(pid);
  const remove = useRemoveMember(pid);
  const [removing, setRemoving] = React.useState<Member | null>(null);
  const list = q.data ?? [];

  return (
    <div className="max-w-3xl space-y-4">
      {canOwn && <AddMember pid={pid} />}
      <Surface className="overflow-hidden">
        <SurfaceHeader title="Members" description="Instance admins see every project without being listed here." />
        {q.isPending ? (
          <TableSkeleton rows={4} cols={3} />
        ) : q.isError ? (
          <ErrorState compact error={q.error} title="Members could not be loaded" onRetry={() => void q.refetch()} />
        ) : list.length === 0 ? (
          <EmptyState compact icon={UsersIcon} title="No members" description="Add people by the email they sign in with. Each gets a role in this project." />
        ) : (
          <ul className="divide-y divide-hairline px-5 pb-2">
            {list.map((m) => {
              const self = m.user_id === user?.id;
              return (
                <li key={m.user_id} className="flex flex-wrap items-center gap-3 py-3 sm:flex-nowrap">
                  <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-primary-soft text-[11.5px] font-semibold text-primary">{initials(m.name)}</span>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-1.5 text-[13.5px] font-medium">
                      <span className="truncate">{m.name}</span>
                      {self && <Chip tone="primary">You</Chip>}
                    </div>
                    <div className="truncate text-[12px] text-muted-foreground">
                      {m.email}, added {formatRelative(m.created_at)}
                    </div>
                  </div>
                  {canOwn ? (
                    <div className="flex items-center gap-1.5">
                      <SimpleSelect
                        aria-label={`Role for ${m.name}`}
                        size="sm"
                        className="w-28"
                        value={m.role}
                        options={ROLE_OPTIONS}
                        onValueChange={(v) =>
                          v &&
                          v !== m.role &&
                          update.mutate(
                            { userId: m.user_id, role: v as ProjectRole },
                            { onSuccess: () => toast.success(`${m.name} is now ${label(v).toLowerCase()}.`), onError: (err) => toast.error(errorMessage(err)) },
                          )
                        }
                      />
                      <Button variant="subtle" size="icon-xs" aria-label={`Remove ${m.name}`} onClick={() => setRemoving(m)}>
                        <Trash2Icon />
                      </Button>
                    </div>
                  ) : (
                    <Chip tone={ROLE_TONE[m.role]}>{label(m.role)}</Chip>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </Surface>
      <Surface>
        <SurfaceHeader title="What each role can do" />
        <dl className="grid gap-2 px-5 pb-5 sm:grid-cols-3">
          {PROJECT_ROLES.map((r) => (
            <div key={r} className="rounded-xl bg-muted/70 px-4 py-3">
              <dt className="text-[13px] font-semibold">{label(r)}</dt>
              <dd className="mt-0.5 text-[12.5px] leading-relaxed text-muted-foreground">{PROJECT_ROLE_DESCRIPTION[r]}</dd>
            </div>
          ))}
        </dl>
      </Surface>
      <ConfirmDialog
        open={!!removing}
        onOpenChange={(o) => !o && setRemoving(null)}
        title={`Remove ${removing?.name ?? "this member"}?`}
        description="They lose access to this project at once. Their account and other projects are not affected."
        confirmLabel="Remove"
        pending={remove.isPending}
        onConfirm={() =>
          removing &&
          remove.mutate(removing.user_id, {
            onSuccess: () => {
              toast.success(`${removing.name} removed.`);
              setRemoving(null);
            },
            onError: (err) => {
              toast.error(errorMessage(err));
              setRemoving(null);
            },
          })
        }
      />
    </div>
  );
}

function AddMember({ pid }: { pid: string }) {
  const add = useAddMember(pid);
  const [email, setEmail] = React.useState("");
  const [role, setRole] = React.useState<ProjectRole>("editor");
  const [error, setError] = React.useState<string | null>(null);

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!/^\S+@\S+\.\S+$/.test(email.trim())) return setError("Enter the email address they sign in with.");
    setError(null);
    add.mutate(
      { email: email.trim(), role },
      {
        onSuccess: (m) => {
          toast.success(`${m.name} added as ${role}.`);
          setEmail("");
        },
        onError: (err) => setError(errorMessage(err)),
      },
    );
  }

  return (
    <Surface>
      <SurfaceHeader title="Add a member" description="They need an account on this server first. An admin creates accounts in Users." />
      <form onSubmit={submit} noValidate className="space-y-2 px-5 pb-5">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-end">
          <div className="flex min-w-0 flex-1 flex-col gap-1.5">
            <Label htmlFor="mb-email">Email</Label>
            <Input id="mb-email" type="email" placeholder="maya@company.com" value={email} onChange={(e) => setEmail(e.target.value)} />
          </div>
          <div className="flex flex-col gap-1.5 sm:w-32">
            <Label htmlFor="mb-role">Role</Label>
            <SimpleSelect id="mb-role" value={role} onValueChange={(v) => setRole((v || "editor") as ProjectRole)} options={ROLE_OPTIONS} />
          </div>
          <Button type="submit" disabled={add.isPending}>
            <UserPlusIcon />
            {add.isPending ? "Adding..." : "Add"}
          </Button>
        </div>
        {error ? <FieldError>{error}</FieldError> : <FieldHint>{label(role)}: {PROJECT_ROLE_DESCRIPTION[role]}</FieldHint>}
      </form>
    </Surface>
  );
}
