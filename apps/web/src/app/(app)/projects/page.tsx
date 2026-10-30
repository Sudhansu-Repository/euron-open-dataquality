import type { Metadata } from "next";
import { Suspense } from "react";

import { ProjectsScreen } from "@/features/projects/components/projects-screen";

export const metadata: Metadata = { title: "Projects" };

export default function Page() {
  return (
    <Suspense>
      <ProjectsScreen />
    </Suspense>
  );
}
