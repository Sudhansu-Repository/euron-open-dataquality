import { AlertTriangleIcon, CheckCircle2Icon, CircleDashedIcon, CircleDotIcon, EyeIcon, InfoIcon, Loader2Icon, MinusCircleIcon, XCircleIcon } from "lucide-react";

import { Chip } from "@/components/ui/chip";
import { cn } from "@/lib/cn";
import { formatPercent } from "@/lib/format";
import {
  incidentStatusLabel,
  incidentStatusTone,
  resultLabel,
  resultTone,
  scanStatusTone,
  scoreLabel,
  scoreTone,
  severityLabel,
  severityTone,
  type Tone,
} from "@/lib/quality";

const TONE_TEXT: Record<Tone, string> = {
  success: "text-pass",
  warning: "text-warn",
  danger: "text-fail",
  neutral: "text-muted-foreground",
  info: "text-info",
  primary: "text-primary",
};

/** A check result: icon and word, never color alone. */
export function ResultChip({ status, severity }: { status: string; severity: string }) {
  const tone = resultTone(status, severity);
  const Icon = status === "pass" ? CheckCircle2Icon : status === "error" ? MinusCircleIcon : severity === "warn" ? AlertTriangleIcon : XCircleIcon;
  return (
    <Chip tone={tone}>
      <Icon />
      {resultLabel(status, severity)}
    </Chip>
  );
}

const SCAN_LABEL: Record<string, string> = {
  queued: "Queued",
  running: "Running",
  succeeded: "Done",
  failed: "Failed",
  cancelled: "Cancelled",
};

export function ScanStatusChip({ status }: { status: string }) {
  const Icon = status === "running" ? Loader2Icon : status === "queued" ? CircleDashedIcon : status === "succeeded" ? CheckCircle2Icon : status === "failed" ? XCircleIcon : MinusCircleIcon;
  return (
    <Chip tone={scanStatusTone(status)}>
      <Icon className={cn(status === "running" && "animate-spin")} />
      {SCAN_LABEL[status] ?? status}
    </Chip>
  );
}

/** A quality score as a number in its tone, with the tone's word for screen readers. */
export function ScoreValue({ score, className }: { score: number | null | undefined; className?: string }) {
  return (
    <span className={cn("tabular font-semibold", TONE_TEXT[scoreTone(score)], className)} title={scoreLabel(score)}>
      {score == null ? "n/a" : formatPercent(score)}
      <span className="sr-only"> ({scoreLabel(score)})</span>
    </span>
  );
}

/** A score as a chip: "98.4% Healthy". */
export function ScoreChip({ score }: { score: number | null | undefined }) {
  return (
    <Chip tone={scoreTone(score)}>
      {score == null ? "Not scanned" : `${formatPercent(score)} ${scoreLabel(score)}`}
    </Chip>
  );
}

export function toneText(tone: Tone): string {
  return TONE_TEXT[tone];
}

/** An incident's severity: icon and word. */
export function SeverityChip({ severity }: { severity: string }) {
  const tone = severityTone(severity);
  const Icon = tone === "danger" ? XCircleIcon : tone === "warning" ? AlertTriangleIcon : InfoIcon;
  return (
    <Chip tone={tone}>
      <Icon />
      {severityLabel(severity)}
    </Chip>
  );
}

export function IncidentStatusChip({ status }: { status: string }) {
  const Icon = status === "resolved" ? CheckCircle2Icon : status === "acknowledged" ? EyeIcon : CircleDotIcon;
  return (
    <Chip tone={incidentStatusTone(status)}>
      <Icon />
      {incidentStatusLabel(status)}
    </Chip>
  );
}
