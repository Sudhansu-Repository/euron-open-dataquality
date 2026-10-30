import { cn } from "@/lib/cn";

/** The DataQuality mark: a pair of code braces around a check, in the accent colour. */
export function BrandMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" aria-hidden className={cn("size-7", className)}>
      <rect width="32" height="32" rx="9" className="fill-primary" />
      <path
        d="M11.5 9.5c-1.7 0-2.5.8-2.5 2.4v1.9c0 1.1-.5 1.7-1.6 2.2 1.1.5 1.6 1.1 1.6 2.2v1.9c0 1.6.8 2.4 2.5 2.4M20.5 9.5c1.7 0 2.5.8 2.5 2.4v1.9c0 1.1.5 1.7 1.6 2.2-1.1.5-1.6 1.1-1.6 2.2v1.9c0 1.6-.8 2.4-2.5 2.4"
        fill="none"
        className="stroke-primary-foreground"
        strokeWidth="1.8"
        strokeLinecap="round"
      />
      <path d="m12.8 16.2 2.2 2.2 4.2-4.6" fill="none" className="stroke-primary-foreground" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function BrandLogo({ collapsed = false, className }: { collapsed?: boolean; className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-2", className)}>
      <BrandMark />
      {!collapsed && <span className="text-[15px] font-semibold tracking-[-0.02em]">DataQuality</span>}
    </span>
  );
}
