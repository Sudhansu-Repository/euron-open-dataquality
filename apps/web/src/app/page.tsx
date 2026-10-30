"use client";

import { useRouter } from "next/navigation";
import * as React from "react";

import { BrandMark } from "@/components/brand";
import { useMe } from "@/features/auth/api";
import { useProjects } from "@/features/projects/api";
import { useUiPrefs } from "@/lib/store";

/** The front door: the last project you opened, your first project, or the project list. */
export default function Home() {
  const router = useRouter();
  const me = useMe();
  const projects = useProjects();
  const last = useUiPrefs((s) => s.lastProjectId);

  React.useEffect(() => {
    void useUiPrefs.persist.rehydrate();
  }, []);

  React.useEffect(() => {
    if (me.data === null) {
      router.replace("/login");
      return;
    }
    if (!projects.data) return;
    const target = projects.data.find((p) => p.id === last) ?? projects.data[0];
    router.replace(target ? `/projects/${target.id}` : "/projects");
  }, [me.data, projects.data, last, router]);

  return (
    <div className="flex min-h-dvh items-center justify-center bg-background" aria-busy>
      <div className="flex flex-col items-center gap-3 text-muted-foreground">
        <BrandMark className="size-10 animate-pulse" />
        <span className="text-[13px]">Opening DataQuality...</span>
      </div>
    </div>
  );
}
