"use client";

import { ActivityIcon, DatabaseIcon, FolderIcon, HistoryIcon, HourglassIcon, ListOrderedIcon, UsersIcon, type LucideIcon } from "lucide-react";

import { AdminOnly } from "@/components/admin-only";
import { ErrorState } from "@/components/error-state";
import { PageHeader } from "@/components/page-header";
import { Stat } from "@/components/stat";
import { Surface, SurfaceHeader } from "@/components/surface";
import { Chip } from "@/components/ui/chip";
import { Skeleton } from "@/components/ui/skeleton";
import { usePermissions } from "@/features/auth/api";
import { formatDuration, formatNumber } from "@/lib/format";

import { useSystemInfo } from "../api";

function Row({ label, icon: Icon, value }: { label: string; icon?: LucideIcon; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4 py-2.5 text-[13px]">
      <span className="inline-flex items-center gap-1.5 text-muted-foreground">
        {Icon && <Icon className="size-3.5" aria-hidden />}
        {label}
      </span>
      <span className="text-right font-medium">{value}</span>
    </div>
  );
}

const STORAGE: Record<string, string> = { s3: "S3", local: "Local disk" };
const KEYS: Record<string, string> = { kms: "KMS", local: "Local master key" };
const CACHE: Record<string, string> = { redis: "Redis", memory: "In process", local: "In process" };
const MAIL: Record<string, string> = { log: "Written to the log (not sent)", smtp: "SMTP", ses: "Amazon SES" };

export function SystemScreen() {
  const { user, admin } = usePermissions();
  const info = useSystemInfo();
  const d = info.data;
  const q = d?.queue;
  // Scans waiting more than two minutes usually mean the worker is down or saturated.
  const stuck = q && (q.oldest_queued_s ?? 0) > 120;

  if (user && !admin) return <AdminOnly what="System status" />;
  return (
    <>
      <PageHeader title="System" description="The scan queue and how this deployment is configured. Refreshes every 15 seconds." />
      {stuck && (
        <div role="status" className="mb-4 rounded-xl bg-warning-soft px-4 py-3 text-[13px] leading-relaxed text-warning">
          The oldest scan has waited {formatDuration((q?.oldest_queued_s ?? 0) * 1000)}. Check that the worker service is running
          (<code className="rounded bg-card/60 px-1 font-mono text-[12px]">make ps</code>), or lower the concurrent-scan limit of a busy
          connection.
        </div>
      )}
      {info.isError ? (
        <div className="surface">
          <ErrorState error={info.error} title="System details could not be read" onRetry={() => void info.refetch()} />
        </div>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Stat label="Queued scans" icon={ListOrderedIcon} value={q ? formatNumber(q.queued) : ""} loading={!q} detail="Waiting for a worker" />
            <Stat label="Running" icon={ActivityIcon} value={q ? formatNumber(q.running) : ""} loading={!q} detail="Querying sources now" />
            <Stat
              label="Oldest waiting"
              icon={HourglassIcon}
              value={q ? (q.oldest_queued_s == null ? "None" : formatDuration(q.oldest_queued_s * 1000)) : ""}
              tone={stuck ? "warn" : "default"}
              loading={!q}
              detail="Time the next scan has queued"
            />
            <Stat label="Scans run" icon={HistoryIcon} value={d ? formatNumber(d.scans) : ""} loading={!d} detail="Across all projects" />
          </div>
          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            <Surface>
              <SurfaceHeader title="Deployment" description="Where files live, how secrets are sealed, and what this server talks to." />
              <div className="divide-y divide-hairline px-5 pb-3">
                {d ? (
                  <>
                    <Row label="Version" value={`v${d.version}`} />
                    <Row label="Environment" value={<Chip tone={d.environment === "production" ? "primary" : "neutral"}>{d.environment}</Chip>} />
                    <Row label="Uploaded files" value={STORAGE[d.storage] ?? d.storage} />
                    <Row label="Secret sealing" value={KEYS[d.key_mode] ?? d.key_mode} />
                    <Row label="Cache" value={CACHE[d.cache] ?? d.cache} />
                    <Row label="Mail" value={MAIL[d.mail] ?? d.mail} />
                    <Row label="Redis" value={d.redis ? <Chip tone="success" dot>Connected</Chip> : <Chip tone="warning" dot>Unreachable</Chip>} />
                  </>
                ) : (
                  <div className="space-y-3 py-3">
                    {Array.from({ length: 6 }).map((_, i) => (
                      <Skeleton key={i} className="h-4 w-full" />
                    ))}
                  </div>
                )}
              </div>
            </Surface>
            <Surface>
              <SurfaceHeader title="Contents" description="What this server holds." />
              <div className="divide-y divide-hairline px-5 pb-3">
                {d ? (
                  <>
                    <Row label="Projects" icon={FolderIcon} value={formatNumber(d.projects)} />
                    <Row label="Datasets" icon={DatabaseIcon} value={formatNumber(d.datasets)} />
                    <Row label="Users" icon={UsersIcon} value={formatNumber(d.users)} />
                    <Row label="Scans" icon={HistoryIcon} value={formatNumber(d.scans)} />
                  </>
                ) : (
                  <div className="space-y-3 py-3">
                    {Array.from({ length: 4 }).map((_, i) => (
                      <Skeleton key={i} className="h-4 w-full" />
                    ))}
                  </div>
                )}
              </div>
            </Surface>
          </div>
        </>
      )}
    </>
  );
}
