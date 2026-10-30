"use client";

import { usePathname } from "next/navigation";

import { useProjects } from "@/features/projects/api";
import { projectIdFrom } from "@/lib/nav";
import { useUiPrefs } from "@/lib/store";

/**
 * The project the nav points into: the one in the address, or on admin pages the last
 * project opened (while it still exists), so project links stay one click away.
 */
export function useNavProjectId(): string | null {
  const pathname = usePathname();
  const last = useUiPrefs((s) => s.lastProjectId);
  const { data: projects } = useProjects();
  const fromPath = projectIdFrom(pathname);
  if (fromPath) return fromPath;
  if (pathname.startsWith("/admin") && last && projects?.some((p) => p.id === last)) return last;
  return null;
}
