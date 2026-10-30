import type { Metadata } from "next";

import { DatasetScreen } from "@/features/datasets/components/dataset-screen";

export const metadata: Metadata = { title: "Dataset" };

export default async function DatasetPage({ params }: { params: Promise<{ did: string }> }) {
  const { did } = await params;
  return <DatasetScreen did={did} />;
}
