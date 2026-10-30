import type { Metadata } from "next";
import { Suspense } from "react";

import { ProjectSettingsScreen } from "@/features/projects/components/project-settings-screen";

export const metadata: Metadata = { title: "Project settings" };

export default function Page() {
  return (
    <Suspense>
      <ProjectSettingsScreen />
    </Suspense>
  );
}
