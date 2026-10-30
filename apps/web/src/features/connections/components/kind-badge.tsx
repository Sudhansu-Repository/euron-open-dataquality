import { cn } from "@/lib/cn";

const SHORT: Record<string, string> = { postgresql: "PG", mysql: "My", mssql: "MS", sqlite: "SQ" };
const TONE: Record<string, string> = {
  postgresql: "bg-primary-soft text-primary",
  mysql: "bg-warn-soft text-warn",
  mssql: "bg-fail-soft text-fail",
  sqlite: "bg-pass-soft text-pass",
};

/** A small lettered tile for a database kind (no vendor logos). */
export function KindBadge({ kind, className }: { kind: string; className?: string }) {
  return (
    <span
      aria-hidden
      className={cn(
        "flex size-9 shrink-0 items-center justify-center rounded-xl font-mono text-[12px] font-semibold tracking-tight",
        TONE[kind] ?? "bg-muted text-muted-foreground",
        className,
      )}
    >
      {SHORT[kind] ?? "DB"}
    </span>
  );
}
