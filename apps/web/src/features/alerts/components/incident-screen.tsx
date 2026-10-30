"use client";

import {
  ArrowLeftIcon,
  BellIcon,
  CheckCircle2Icon,
  CheckIcon,
  CircleDotIcon,
  EyeIcon,
  HistoryIcon,
  MailIcon,
  SparklesIcon,
  WebhookIcon,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import * as React from "react";
import { toast } from "sonner";

import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { PageHeader } from "@/components/page-header";
import { IncidentStatusChip, SeverityChip } from "@/components/quality";
import { Surface, SurfaceHeader } from "@/components/surface";
import { Button } from "@/components/ui/button";
import { Chip } from "@/components/ui/chip";
import { Skeleton } from "@/components/ui/skeleton";
import { useChannels } from "@/features/alerts/api";
import { useCurrentProject } from "@/features/projects/api";
import { ApiError, errorMessage } from "@/lib/api/errors";
import type { Explanation, IncidentDetail } from "@/lib/api/types";
import { cn } from "@/lib/cn";
import { formatDateTime, formatNumber, formatRelative } from "@/lib/format";
import { notificationTone, ruleKindLabel } from "@/lib/quality";

import { useAcknowledgeIncident, useExplainIncident, useIncident, useResolveIncident } from "../api";

/** One incident (route /projects/[pid]/incidents/[iid]). */
export function IncidentScreen() {
  const { pid, canEdit } = useCurrentProject();
  const { iid } = useParams<{ iid: string }>();
  const q = useIncident(pid, iid);
  const back = (
    <Link href={`/projects/${pid}/incidents`} className="inline-flex items-center gap-1 text-[12.5px] font-medium text-muted-foreground hover:text-foreground">
      <ArrowLeftIcon className="size-3.5" />
      Incidents
    </Link>
  );

  if (q.isPending) {
    return (
      <>
        <div className="mb-6">{back}</div>
        <Skeleton className="mb-6 h-12 w-2/3" />
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
          <Skeleton className="h-72 rounded-[14px]" />
          <Skeleton className="h-72 rounded-[14px]" />
        </div>
      </>
    );
  }
  if (q.isError) {
    return (
      <>
        <div className="mb-6">{back}</div>
        <div className="surface">
          <ErrorState error={q.error} title="This incident could not be loaded" onRetry={() => void q.refetch()} />
        </div>
      </>
    );
  }
  return <IncidentView pid={pid} incident={q.data} canEdit={canEdit} back={back} />;
}

function IncidentView({ pid, incident: i, canEdit, back }: { pid: string; incident: IncidentDetail; canEdit: boolean; back: React.ReactNode }) {
  const ack = useAcknowledgeIncident(pid);
  const resolve = useResolveIncident(pid);
  const busy = ack.isPending || resolve.isPending;

  function act(kind: "ack" | "resolve") {
    const m = kind === "ack" ? ack : resolve;
    m.mutate(i.id, {
      onSuccess: () =>
        toast.success(kind === "ack" ? "Acknowledged. The team can see someone is on it." : "Resolved. A later scan that shows the problem opens a new incident."),
      onError: (err) => toast.error(errorMessage(err)),
    });
  }

  return (
    <>
      <PageHeader
        eyebrow={back}
        title={i.title}
        description={
          <span className="flex flex-wrap items-center gap-2">
            <SeverityChip severity={i.severity} />
            <IncidentStatusChip status={i.status} />
            <span>
              Seen in {formatNumber(i.occurrences)} {i.occurrences === 1 ? "scan" : "scans"}, last {formatRelative(i.last_seen_at)}
            </span>
          </span>
        }
        actions={
          canEdit &&
          i.status !== "resolved" && (
            <>
              {i.status === "open" && (
                <Button variant="outline" onClick={() => act("ack")} disabled={busy}>
                  <EyeIcon />
                  {ack.isPending ? "Acknowledging..." : "Acknowledge"}
                </Button>
              )}
              <Button onClick={() => act("resolve")} disabled={busy}>
                <CheckIcon />
                {resolve.isPending ? "Resolving..." : "Resolve"}
              </Button>
            </>
          )
        }
      />
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="min-w-0 space-y-4">
          <Surface>
            <SurfaceHeader title="What happened" />
            <div className="px-5 pb-5">
              <p className="text-[14px] leading-relaxed">{i.detail || i.title}</p>
              {i.resolution && (
                <p className="mt-3 rounded-xl bg-pass-soft px-4 py-3 text-[13px] text-pass">
                  <span className="font-semibold">Resolution: </span>
                  {i.resolution}
                </p>
              )}
            </div>
          </Surface>
          <Explain pid={pid} iid={i.id} />
          <Notifications pid={pid} incident={i} />
        </div>
        <div className="space-y-4">
          <Surface>
            <SurfaceHeader title="Timeline" />
            <ol className="px-5 pb-5">
              <TimelineItem icon={CircleDotIcon} tone="danger" label="Opened" at={i.opened_at} />
              <TimelineItem icon={EyeIcon} tone="warning" label="Acknowledged" at={i.acknowledged_at} />
              <TimelineItem icon={CheckCircle2Icon} tone="success" label="Resolved" at={i.resolved_at} last />
            </ol>
          </Surface>
          <Surface>
            <SurfaceHeader title="Details" />
            <dl className="divide-y divide-hairline px-5 pb-3 text-[13px]">
              <Fact label="Rule">
                <span className="font-medium">{i.rule_name ?? "Alert rule"}</span>
                <span className="block text-[12px] text-muted-foreground">{ruleKindLabel(i.rule_kind)}</span>
              </Fact>
              <Fact label="Dataset">
                <Link href={`/projects/${pid}/datasets/${i.dataset_id}`} className="font-medium text-primary hover:underline">
                  {i.dataset_name ?? "Open dataset"}
                </Link>
              </Fact>
              <Fact label="First scan">
                {i.first_scan_id ? (
                  <Link href={`/projects/${pid}/scans/${i.first_scan_id}`} className="inline-flex items-center gap-1 font-medium text-primary hover:underline">
                    <HistoryIcon className="size-3.5" />
                    View scan
                  </Link>
                ) : (
                  <span className="text-muted-foreground">n/a</span>
                )}
              </Fact>
              <Fact label="Last scan">
                {i.last_scan_id ? (
                  <Link href={`/projects/${pid}/scans/${i.last_scan_id}`} className="inline-flex items-center gap-1 font-medium text-primary hover:underline">
                    <HistoryIcon className="size-3.5" />
                    View scan
                  </Link>
                ) : (
                  <span className="text-muted-foreground">n/a</span>
                )}
              </Fact>
              <Fact label="Last seen">{formatDateTime(i.last_seen_at)}</Fact>
            </dl>
          </Surface>
        </div>
      </div>
    </>
  );
}

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4 py-2.5">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0 text-right">{children}</dd>
    </div>
  );
}

const TONE_CLASS = { danger: "bg-fail-soft text-fail", warning: "bg-warn-soft text-warn", success: "bg-pass-soft text-pass" } as const;

function TimelineItem({ icon: Icon, tone, label, at, last = false }: { icon: LucideIcon; tone: keyof typeof TONE_CLASS; label: string; at: string | null; last?: boolean }) {
  return (
    <li className="relative flex gap-3 pb-4 last:pb-0">
      {!last && <span aria-hidden className="absolute top-8 bottom-0 left-[13px] w-px bg-border" />}
      <span className={cn("flex size-7 shrink-0 items-center justify-center rounded-full", at ? TONE_CLASS[tone] : "bg-muted text-faint")}>
        <Icon className="size-3.5" />
      </span>
      <div className="pt-0.5">
        <div className={cn("text-[13px] font-medium", !at && "text-muted-foreground")}>{label}</div>
        <div className="text-[12px] text-muted-foreground">{at ? (/ago|now/.test(formatRelative(at)) ? `${formatDateTime(at)}, ${formatRelative(at)}` : formatDateTime(at)) : "Not yet"}</div>
      </div>
    </li>
  );
}

function Explain({ pid, iid }: { pid: string; iid: string }) {
  const explain = useExplainIncident(pid);
  const [result, setResult] = React.useState<Explanation | null>(null);
  const [off, setOff] = React.useState(false);

  function run() {
    explain.mutate(iid, {
      onSuccess: setResult,
      onError: (err) => {
        if (err instanceof ApiError && err.code === "ai_disabled") setOff(true);
        else toast.error(errorMessage(err));
      },
    });
  }

  return (
    <Surface>
      <SurfaceHeader
        title={
          <span className="inline-flex items-center gap-1.5">
            <SparklesIcon className="size-4 text-primary" />
            Explain
          </span>
        }
        description="Optional: the AI assistant reads the incident and its scan results and suggests likely causes."
        action={
          !off && (
            <Button variant="outline" size="sm" onClick={run} disabled={explain.isPending}>
              <SparklesIcon />
              {explain.isPending ? "Thinking..." : result ? "Explain again" : "Explain"}
            </Button>
          )
        }
      />
      <div className="px-5 pb-5">
        {off ? (
          <p className="rounded-xl bg-muted px-4 py-3 text-[13px] leading-relaxed text-muted-foreground">
            The AI assistant is off on this server, so nothing was sent anywhere. An admin can enable it in Instance settings with
            any OpenAI-compatible endpoint, including a local model.
          </p>
        ) : explain.isPending ? (
          <div className="space-y-2" aria-busy aria-label="Writing an explanation">
            <Skeleton className="h-3.5 w-full" />
            <Skeleton className="h-3.5 w-11/12" />
            <Skeleton className="h-3.5 w-3/4" />
          </div>
        ) : result ? (
          <div>
            <p className="text-[13.5px] leading-relaxed whitespace-pre-line">{result.explanation}</p>
            <p className="mt-3 text-[11.5px] text-subtle">Written by {result.model}. Check it against the scan before acting on it.</p>
          </div>
        ) : (
          <p className="text-[13px] text-muted-foreground">Ask for an explanation when the cause is not obvious from the failing checks.</p>
        )}
      </div>
    </Surface>
  );
}

function channelIcon(kind: string | undefined): LucideIcon {
  if (kind === "email") return MailIcon;
  if (kind === "webhook" || kind === "slack") return WebhookIcon;
  return BellIcon;
}

function Notifications({ pid, incident }: { pid: string; incident: IncidentDetail }) {
  const channels = useChannels(pid);
  const list = incident.notifications ?? [];
  const kindOf = (id: string) => channels.data?.find((c) => c.id === id)?.kind;
  return (
    <Surface className="overflow-hidden">
      <SurfaceHeader title="Notifications" description="Who was told, and whether it arrived. Failed deliveries are retried with backoff." />
      {list.length === 0 ? (
        <EmptyState
          compact
          icon={BellIcon}
          title="No notifications"
          description="The rule that opened this incident has no channels, or they were disabled. Add channels to the rule on the Alerts page."
          action={
            <Link href={`/projects/${pid}/alerts`} className="text-[13px] font-medium text-primary hover:underline">
              Open Alerts
            </Link>
          }
        />
      ) : (
        <ul className="divide-y divide-hairline px-5 pb-2">
          {list.map((n) => {
            const Icon = channelIcon(kindOf(n.channel_id));
            return (
              <li key={n.id} className="flex items-start gap-3 py-3">
                <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-muted text-subtle">
                  <Icon className="size-4" />
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2 text-[13px]">
                    <span className="font-medium">{n.channel_name ?? "Channel"}</span>
                    <Chip tone="neutral">{n.event === "resolved" ? "Resolved" : "Opened"}</Chip>
                  </div>
                  <div className="text-[12px] text-muted-foreground">
                    {n.sent_at ? `Sent ${formatDateTime(n.sent_at)}` : `Queued ${formatDateTime(n.created_at)}`}
                    {n.attempts > 1 ? `, ${n.attempts} attempts` : ""}
                  </div>
                  {n.last_error && <div className="mt-1 text-[12px] break-words text-fail">{n.last_error}</div>}
                </div>
                <Chip tone={notificationTone(n.status)} className="capitalize">
                  {n.status}
                </Chip>
              </li>
            );
          })}
        </ul>
      )}
    </Surface>
  );
}
