import type { Metadata } from "next";
import { Suspense } from "react";

import { ConnectionsScreen } from "@/features/connections/components/connections-screen";

export const metadata: Metadata = { title: "Connections" };

export default function Page() {
  return (
    <Suspense>
      <ConnectionsScreen />
    </Suspense>
  );
}
