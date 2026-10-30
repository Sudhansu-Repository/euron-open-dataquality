import type { Metadata } from "next";
import { Suspense } from "react";

import { NewDatasetScreen } from "@/features/datasets/components/new-dataset-screen";

export const metadata: Metadata = { title: "New dataset" };

export default function Page() {
  return (
    <Suspense>
      <NewDatasetScreen />
    </Suspense>
  );
}
