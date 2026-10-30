"use client";

import { BellIcon, HashIcon, MailIcon, PlusIcon, SendIcon, ShieldCheckIcon, Trash2Icon, WebhookIcon, type LucideIcon } from "lucide-react";
import * as React from "react";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { CopyButton } from "@/components/copy-button";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { Segmented } from "@/components/segmented";
import { Surface, SurfaceHeader } from "@/components/surface";
import { TableSkeleton } from "@/components/table-skeleton";
import { Button } from "@/components/ui/button";
import { Chip } from "@/components/ui/chip";
import { Dialog, DialogBody, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input, Textarea } from "@/components/ui/input";
import { Field, FieldError } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { errorMessage } from "@/lib/api/errors";
import type { Channel, ChannelCreated, ChannelIn } from "@/lib/api/types";
import { CHANNEL_KINDS } from "@/lib/quality";

import { useChannels, useCreateChannel, useDeleteChannel, useTestChannel, useUpdateChannel } from "../api";

type Kind = ChannelIn["kind"];

export const CHANNEL_ICON: Record<string, LucideIcon> = { email: MailIcon, slack: HashIcon, webhook: WebhookIcon };

/** Recipients typed one per line or separated by commas. */
export function parseRecipients(raw: string): string[] {
  return Array.from(new Set(raw.split(/[\s,;]+/).map((r) => r.trim()).filter(Boolean)));
}

export function ChannelsSection({ pid, canEdit }: { pid: string; canEdit: boolean }) {
  const q = useChannels(pid);
  const [adding, setAdding] = React.useState(false);
  const [created, setCreated] = React.useState<ChannelCreated | null>(null);
  const [deleting, setDeleting] = React.useState<Channel | null>(null);
  const del = useDeleteChannel(pid);
  const list = q.data ?? [];

  return (
    <Surface className="overflow-hidden">
      <SurfaceHeader
        title="Channels"
        description="Where notifications go: email recipients, a Slack channel, or your own endpoint."
        action={
          canEdit &&
          list.length > 0 && (
            <Button size="sm" onClick={() => setAdding(true)}>
              <PlusIcon />
              Add channel
            </Button>
          )
        }
      />
      {q.isPending ? (
        <TableSkeleton rows={3} cols={3} />
      ) : q.isError ? (
        <ErrorState compact error={q.error} title="Channels could not be loaded" onRetry={() => void q.refetch()} />
      ) : list.length === 0 ? (
        <EmptyState
          compact
          icon={BellIcon}
          title="No channels yet"
          description="A channel is where an alert is delivered. Add one, then point alert rules at it."
          action={
            canEdit ? (
              <Button size="sm" onClick={() => setAdding(true)}>
                <PlusIcon />
                Add a channel
              </Button>
            ) : undefined
          }
        />
      ) : (
        <ul className="divide-y divide-hairline px-5 pb-2">
          {list.map((c) => (
            <ChannelRow key={c.id} pid={pid} channel={c} canEdit={canEdit} onDelete={() => setDeleting(c)} />
          ))}
        </ul>
      )}
      <AddChannelDialog
        pid={pid}
        open={adding}
        onOpenChange={setAdding}
        onCreated={(c) => {
          setAdding(false);
          if (c.signing_secret) setCreated(c);
        }}
      />
      <SecretDialog channel={created} onClose={() => setCreated(null)} />
      <ConfirmDialog
        open={!!deleting}
        onOpenChange={(o) => !o && setDeleting(null)}
        title={`Delete ${deleting?.name ?? "this channel"}?`}
        description="Rules that use it stop notifying through it. Notifications already sent stay in each incident's history."
        confirmLabel="Delete channel"
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

function ChannelRow({ pid, channel: c, canEdit, onDelete }: { pid: string; channel: Channel; canEdit: boolean; onDelete: () => void }) {
  const update = useUpdateChannel(pid);
  const test = useTestChannel(pid);
  const Icon = CHANNEL_ICON[c.kind] ?? BellIcon;

  function sendTest() {
    test.mutate(c.id, {
      onSuccess: (r) => (r.ok === false ? toast.error(r.message || "The test was not delivered.") : toast.success(r.message || `Test sent to ${c.name}.`)),
      onError: (err) => toast.error(errorMessage(err)),
    });
  }

  return (
    <li className="flex flex-wrap items-center gap-3 py-3 sm:flex-nowrap">
      <span className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-primary-soft text-primary">
        <Icon className="size-4" />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="truncate text-[13.5px] font-medium">{c.name}</span>
          <Chip tone="neutral">{CHANNEL_KINDS[c.kind] ?? c.kind}</Chip>
        </div>
        <div className="truncate font-mono text-[12px] text-muted-foreground">{c.target_hint}</div>
      </div>
      <div className="flex items-center gap-2">
        {canEdit ? (
          <>
            <Button variant="outline" size="xs" onClick={sendTest} disabled={test.isPending || !c.enabled} title={c.enabled ? undefined : "Enable the channel to test it"}>
              <SendIcon />
              {test.isPending ? "Sending..." : "Send test"}
            </Button>
            <Switch
              checked={c.enabled}
              aria-label={c.enabled ? `Disable ${c.name}` : `Enable ${c.name}`}
              onCheckedChange={(on) =>
                update.mutate(
                  { id: c.id, body: { enabled: on } },
                  { onSuccess: () => toast.success(on ? `${c.name} enabled.` : `${c.name} paused. Rules skip it until you enable it.`), onError: (err) => toast.error(errorMessage(err)) },
                )
              }
            />
            <Button variant="subtle" size="icon-xs" aria-label={`Delete ${c.name}`} onClick={onDelete}>
              <Trash2Icon />
            </Button>
          </>
        ) : (
          <Chip tone={c.enabled ? "success" : "neutral"} dot>
            {c.enabled ? "Enabled" : "Paused"}
          </Chip>
        )}
      </div>
    </li>
  );
}

function AddChannelDialog({
  pid,
  open,
  onOpenChange,
  onCreated,
}: {
  pid: string;
  open: boolean;
  onOpenChange: (o: boolean) => void;
  onCreated: (c: ChannelCreated) => void;
}) {
  const create = useCreateChannel(pid);
  const [kind, setKind] = React.useState<Kind>("email");
  const [name, setName] = React.useState("");
  const [recipients, setRecipients] = React.useState("");
  const [url, setUrl] = React.useState("");
  const [secret, setSecret] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!open) return;
    setKind("email");
    setName("");
    setRecipients("");
    setUrl("");
    setSecret("");
    setError(null);
  }, [open]);

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return setError("Name the channel, like Data team or #data-alerts.");
    let body: ChannelIn;
    if (kind === "email") {
      const list = parseRecipients(recipients);
      if (!list.length) return setError("Add at least one email address.");
      const bad = list.find((r) => !/^\S+@\S+\.\S+$/.test(r));
      if (bad) return setError(`"${bad}" is not an email address.`);
      body = { name: name.trim(), kind, recipients: list };
    } else {
      if (!/^https?:\/\//i.test(url.trim())) return setError("Enter the full URL, starting with https://.");
      body = { name: name.trim(), kind, url: url.trim(), ...(kind === "webhook" && secret ? { secret } : {}) };
    }
    setError(null);
    create.mutate(body, {
      onSuccess: (c) => {
        toast.success(`${c.name} added. Send a test to check it arrives.`);
        onCreated(c);
      },
      onError: (err) => setError(errorMessage(err)),
    });
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !create.isPending && onOpenChange(o)}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add a channel</DialogTitle>
          <DialogDescription>Addresses and URLs are stored sealed. Only a short hint is shown afterwards.</DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="flex min-h-0 flex-col" noValidate>
          <DialogBody className="space-y-4">
            <Segmented<Kind>
              ariaLabel="Channel kind"
              value={kind}
              onChange={(k) => {
                setKind(k);
                setError(null);
              }}
              options={[
                { value: "email", label: "Email" },
                { value: "slack", label: "Slack" },
                { value: "webhook", label: "Webhook" },
              ]}
            />
            <Field label="Name" htmlFor="ch-name">
              <Input id="ch-name" maxLength={120} placeholder={kind === "slack" ? "#data-alerts" : kind === "webhook" ? "Incident bridge" : "Data team"} value={name} onChange={(e) => setName(e.target.value)} />
            </Field>
            {kind === "email" && (
              <Field label="Recipients" htmlFor="ch-rcpt" hint="One per line, or separated by commas.">
                <Textarea id="ch-rcpt" placeholder={"data-team@example.com\noncall@example.com"} value={recipients} onChange={(e) => setRecipients(e.target.value)} />
              </Field>
            )}
            {kind === "slack" && (
              <Field label="Incoming webhook URL" htmlFor="ch-url" hint="In Slack: Apps, Incoming Webhooks, Add to a channel. It starts with https://hooks.slack.com/.">
                <Input id="ch-url" type="url" placeholder="https://hooks.slack.com/services/..." value={url} onChange={(e) => setUrl(e.target.value)} />
              </Field>
            )}
            {kind === "webhook" && (
              <>
                <Field label="URL" htmlFor="ch-url" hint="Receives a JSON POST for every incident opened or resolved.">
                  <Input id="ch-url" type="url" placeholder="https://hooks.example.com/dataquality" value={url} onChange={(e) => setUrl(e.target.value)} />
                </Field>
                <Field label="Signing secret" htmlFor="ch-secret" hint="Optional. Leave empty and one is generated for you, shown once.">
                  <Input id="ch-secret" type="password" autoComplete="off" value={secret} onChange={(e) => setSecret(e.target.value)} />
                </Field>
              </>
            )}
            {error && <FieldError>{error}</FieldError>}
          </DialogBody>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={create.isPending}>
              {create.isPending ? "Adding..." : "Add channel"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function SecretDialog({ channel, onClose }: { channel: ChannelCreated | null; onClose: () => void }) {
  const secret = channel?.signing_secret ?? "";
  return (
    <Dialog open={!!channel} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Save the signing secret</DialogTitle>
          <DialogDescription>This is the only time it is shown. Store it with the service that receives the webhook.</DialogDescription>
        </DialogHeader>
        <DialogBody className="space-y-4">
          <div className="flex items-center gap-2 rounded-xl bg-muted p-2 pl-3">
            <code className="min-w-0 flex-1 truncate font-mono text-[12.5px]">{secret}</code>
            <CopyButton value={secret} />
          </div>
          <div className="flex gap-2.5 text-[12.5px] leading-relaxed text-muted-foreground">
            <ShieldCheckIcon className="mt-0.5 size-4 shrink-0 text-primary" aria-hidden />
            <p>
              Every request carries <code className="font-mono text-foreground">X-DQ-Signature: t=&lt;unix time&gt;,v1=&lt;hex&gt;</code>. To verify,
              compute the HMAC-SHA256 of <code className="font-mono text-foreground">&lt;t&gt;.&lt;raw body&gt;</code> with this secret, compare it to
              v1 in constant time, and reject a t older than five minutes.
            </p>
          </div>
        </DialogBody>
        <DialogFooter>
          <Button onClick={onClose}>I saved it</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
