import type { Metadata } from "next";

import { SystemScreen } from "@/features/admin/components/system-screen";

export const metadata: Metadata = { title: "System" };

export default function SystemPage() {
  return <SystemScreen />;
}
