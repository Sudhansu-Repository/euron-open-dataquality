import { Hint } from "@/components/hint";
import { ScoreValue } from "@/components/quality";
import { cn } from "@/lib/cn";
import { formatPercent } from "@/lib/format";
import { DIMENSIONS, dimensionLabel, scoreLabel, scoreTone } from "@/lib/quality";

const FILL: Record<string, string> = {
  success: "bg-primary",
  warning: "bg-warn",
  danger: "bg-fail",
  neutral: "bg-faint",
};

/**
 * One horizontal meter per quality dimension, 0 to 100. The fill carries the score's
 * state (blue when healthy, amber when it needs attention, red when poor); the value and
 * its word sit beside it, so the state never relies on color alone.
 */
export function DimensionBars({ scores, className }: { scores: Record<string, number | null | undefined>; className?: string }) {
  return (
    <ul className={cn("space-y-3.5", className)}>
      {DIMENSIONS.map((d) => {
        const v = scores[d];
        const has = v != null;
        const tone = scoreTone(v);
        return (
          <li key={d} className="grid grid-cols-[minmax(0,7.5rem)_1fr_auto] items-center gap-3">
            <span className="flex min-w-0 items-center gap-1 text-[13px] text-foreground">
              <span className="truncate">{dimensionLabel(d)}</span>
              <Hint term={d} />
            </span>
            {has ? (
              <div
                className="h-2 overflow-hidden rounded-full bg-muted"
                role="meter"
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={v}
                aria-label={`${dimensionLabel(d)} ${formatPercent(v)}, ${scoreLabel(v)}`}
                title={`${dimensionLabel(d)}: ${formatPercent(v)} (${scoreLabel(v)})`}
              >
                <div className={cn("h-full rounded-full transition-[width] duration-500", FILL[tone])} style={{ width: `${Math.max(1.5, Math.min(100, v))}%` }} />
              </div>
            ) : (
              <div className="h-2 rounded-full bg-muted/60" aria-hidden />
            )}
            <span className="w-[5.5rem] text-right text-[13px]">
              {has ? <ScoreValue score={v} className="tabular" /> : <span className="text-xs text-faint">no checks yet</span>}
            </span>
          </li>
        );
      })}
    </ul>
  );
}
