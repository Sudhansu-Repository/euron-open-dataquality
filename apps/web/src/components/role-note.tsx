import { EyeIcon } from "lucide-react";
import * as React from "react";

import { cn } from "@/lib/cn";

/**
 * A calm line telling someone why they see a page without its controls: their project
 * role lets them look, and who can change it.
 */
export function RoleNote({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <div role="note" className={cn("flex items-start gap-2.5 rounded-xl bg-muted px-4 py-3 text-[13px] leading-relaxed text-muted-foreground", className)}>
      <EyeIcon className="mt-0.5 size-4 shrink-0 text-subtle" aria-hidden />
      <div>{children}</div>
    </div>
  );
}
