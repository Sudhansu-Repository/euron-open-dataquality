import type { Metadata } from "next";
import { Suspense } from "react";

import { IncidentScreen } from "@/features/alerts/components/incident-screen";

export const metadata: Metadata = { title: "Incident" };

export default function Page() {
  return (
    <Suspense>
      <IncidentScreen />
    </Suspense>
  );
}
