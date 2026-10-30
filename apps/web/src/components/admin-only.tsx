import { ShieldIcon } from "lucide-react";
import Link from "next/link";

import { EmptyState } from "@/components/empty-state";
import { Surface } from "@/components/surface";
import { Button } from "@/components/ui/button";

/** Shown to people whose role does not open this page. */
export function AdminOnly({ what }: { what: string }) {
  return (
    <Surface>
      <EmptyState
        icon={ShieldIcon}
        title="Admins only"
        description={`${what} is for instance admins. Ask an admin if you need access.`}
        action={
          <Button variant="outline" size="sm" nativeButton={false} render={<Link href="/projects" />}>
            Back to your projects
          </Button>
        }
      />
    </Surface>
  );
}
