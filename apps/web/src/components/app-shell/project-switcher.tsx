"use client";

import { CheckIcon, ChevronsUpDownIcon, FolderPlusIcon, LayoutGridIcon } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import * as React from "react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useProjects } from "@/features/projects/api";
import { cn } from "@/lib/cn";
import { projectIdFrom } from "@/lib/nav";
import { useUiPrefs } from "@/lib/store";

import { useNavProjectId } from "./use-nav-project";

/** The current project, and a menu to switch to another one or create one. */
export function ProjectSwitcher({ collapsed = false, onNavigate }: { collapsed?: boolean; onNavigate?: () => void }) {
  const pathname = usePathname();
  const router = useRouter();
  const pathPid = projectIdFrom(pathname);
  const pid = useNavProjectId();
  const { data: projects } = useProjects();
  const setLast = useUiPrefs((s) => s.setLastProject);
  const current = projects?.find((p) => p.id === pid);

  React.useEffect(() => {
    if (pathPid) setLast(pathPid);
  }, [pathPid, setLast]);

  if (!projects) return <div className="h-11 animate-pulse rounded-xl bg-accent/60" aria-hidden />;
  if (!projects.length) {
    return (
      <Link
        href="/projects"
        onClick={onNavigate}
        className="flex h-11 items-center gap-2 rounded-xl bg-card px-3 text-[13px] font-medium text-primary shadow-[var(--elev-1)] hover:bg-accent focus-visible:outline-2 focus-visible:outline-ring"
      >
        <FolderPlusIcon className="size-4" />
        {!collapsed && "Create a project"}
      </Link>
    );
  }
  const letter = (current?.name ?? "?").slice(0, 1).toUpperCase();
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        aria-label="Switch project"
        className={cn(
          "flex h-11 w-full items-center gap-2.5 rounded-xl bg-card px-2 text-left shadow-[var(--elev-1)] outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring dark:bg-accent/60",
          collapsed && "justify-center px-0",
        )}
      >
        {current ? (
          <span className="flex size-7 shrink-0 items-center justify-center rounded-lg bg-primary text-[12px] font-semibold text-primary-foreground">{letter}</span>
        ) : (
          <span className="flex size-7 shrink-0 items-center justify-center rounded-lg bg-primary-soft text-primary">
            <LayoutGridIcon className="size-3.5" />
          </span>
        )}
        {!collapsed && (
          <>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-[13px] font-semibold text-foreground">{current?.name ?? "Choose a project"}</span>
              <span className="block truncate text-[11px] text-muted-foreground">{current ? `${current.datasets} datasets, ${current.role}` : `${projects.length} projects available`}</span>
            </span>
            <ChevronsUpDownIcon className="size-3.5 shrink-0 text-subtle" />
          </>
        )}
      </DropdownMenuTrigger>
      <DropdownMenuContent className="w-64" align="start">
        <DropdownMenuLabel>Projects</DropdownMenuLabel>
        {projects.map((p) => (
          <DropdownMenuItem
            key={p.id}
            onClick={() => {
              onNavigate?.();
              router.push(`/projects/${p.id}`);
            }}
          >
            <span className="flex size-5 items-center justify-center rounded-md bg-primary-soft text-[10px] font-semibold text-primary">{p.name.slice(0, 1).toUpperCase()}</span>
            <span className="flex-1 truncate">{p.name}</span>
            {p.id === pid && <CheckIcon className="size-3.5 text-primary" />}
          </DropdownMenuItem>
        ))}
        <DropdownMenuSeparator />
        <DropdownMenuItem
          onClick={() => {
            onNavigate?.();
            router.push("/projects");
          }}
        >
          <LayoutGridIcon />
          All projects
        </DropdownMenuItem>
        <DropdownMenuItem
          onClick={() => {
            onNavigate?.();
            router.push("/projects?new=1");
          }}
        >
          <FolderPlusIcon />
          New project
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
