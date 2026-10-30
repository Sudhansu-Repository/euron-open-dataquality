import type { Metadata } from "next";
import { Suspense } from "react";

import { IncidentsScreen } from "@/features/alerts/components/incidents-screen";

export const metadata: Metadata = { title: "Incidents" };

export default function Page() {
  return (
    <Suspense>
      <IncidentsScreen />
    </Suspense>
  );
}
