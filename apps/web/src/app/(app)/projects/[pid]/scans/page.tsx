import type { Metadata } from "next";

import { ScansScreen } from "@/features/scans/components/scans-screen";

export const metadata: Metadata = { title: "Scans" };

export default function ScansPage() {
  return <ScansScreen />;
}
