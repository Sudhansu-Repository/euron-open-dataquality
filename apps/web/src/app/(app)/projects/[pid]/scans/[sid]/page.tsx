import type { Metadata } from "next";

import { ScanScreen } from "@/features/scans/components/scan-screen";

export const metadata: Metadata = { title: "Scan" };

export default async function ScanPage({ params }: { params: Promise<{ sid: string }> }) {
  const { sid } = await params;
  return <ScanScreen sid={sid} />;
}
