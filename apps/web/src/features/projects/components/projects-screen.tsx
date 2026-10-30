"use client";

import { ArrowRightIcon, BellRingIcon, CableIcon, DatabaseIcon, FolderPlusIcon, ScanSearchIcon } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import * as React from "react";
import { toast } from "sonner";

import { ErrorState } from "@/components/error-state";
import { PageHeader } from "@/components/page-header";
import { ScoreValue } from "@/components/quality";
import { Button } from "@/components/ui/button";
import { Chip } from "@/components/ui/chip";
import { Dialog, DialogBody, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input, Textarea } from "@/components/ui/input";
import { Field, FieldError } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { errorMessage } from "@/lib/api/errors";
import type { Project } from "@/lib/api/types";
import { formatNumber } from "@/lib/format";
import { scoreLabel } from "@/lib/quality";

import { useCreateProject, useProjects } from "../api";

const ROLE_TONE = { owner: "primary", editor: "info", viewer: "neutral" } as const;

export function ProjectsScreen() {
  const q = useProjects();
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const [open, setOpen] = React.useState(false);

  React.useEffect(() => {
    if (params.get("new") === "1") setOpen(true);
  }, [params]);

  function setDialog(next: boolean) {
    setOpen(next);
    if (!next && params.get("new")) router.replace(pathname, { scroll: false });
  }

  const projects = q.data ?? [];
  return (
    <>
      <PageHeader
        title="Projects"
        description="A project groups the connections, datasets, checks and alerts of one team or data product, with its own members."
        actions={
          projects.length > 0 && (
            <Button onClick={() => setDialog(true)}>
              <FolderPlusIcon />
              New project
            </Button>
          )
        }
      />
      {q.isPending ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3" aria-busy aria-label="Loading projects">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-40 rounded-[14px]" />
          ))}
        </div>
      ) : q.isError ? (
        <div className="surface">
          <ErrorState error={q.error} title="Projects could not be loaded" onRetry={() => void q.refetch()} />
        </div>
      ) : projects.length === 0 ? (
        <Onboarding onCreate={() => setDialog(true)} />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {projects.map((p) => (
            <ProjectCard key={p.id} project={p} />
          ))}
        </div>
      )}
      <NewProjectDialog open={open} onOpenChange={setDialog} />
    </>
  );
}

function ProjectCard({ project: p }: { project: Project }) {
  return (
    <Link
      href={`/projects/${p.id}`}
      className="surface group flex min-w-0 flex-col gap-4 p-5 transition-shadow outline-none hover:shadow-[var(--elev-3)] focus-visible:ring-2 focus-visible:ring-ring"
    >
      <div className="flex items-start gap-3">
        <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-primary-soft text-[15px] font-semibold text-primary">
          {p.name.slice(0, 1).toUpperCase()}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <h2 className="truncate text-[15px] font-semibold tracking-[-0.01em]">{p.name}</h2>
            {p.role && <Chip tone={ROLE_TONE[p.role]}>{p.role.charAt(0).toUpperCase() + p.role.slice(1)}</Chip>}
          </div>
          <p className="mt-0.5 line-clamp-2 text-[12.5px] leading-relaxed text-muted-foreground">
            {p.description || "No description yet."}
          </p>
        </div>
      </div>
      <div className="mt-auto flex items-start justify-between gap-3 rounded-xl bg-muted/70 px-4 py-3">
        <div>
          <div className="text-[11px] font-semibold tracking-[0.04em] text-subtle uppercase">Quality score</div>
          <ScoreValue score={p.score} className="text-[22px] leading-tight tracking-[-0.02em]" />
          <div className="text-[11.5px] text-muted-foreground">{scoreLabel(p.score)}</div>
        </div>
        <div className="text-right">
          <div className="text-[11px] font-semibold tracking-[0.04em] text-subtle uppercase">Datasets</div>
          <div className="tabular text-[22px] leading-tight font-semibold tracking-[-0.02em]">{formatNumber(p.datasets ?? 0)}</div>
          <div className="inline-flex items-center gap-1 text-[11.5px] font-medium text-primary">
            Open
            <ArrowRightIcon className="size-3 transition-transform group-hover:translate-x-0.5" />
          </div>
        </div>
      </div>
    </Link>
  );
}

const STEPS = [
  {
    icon: CableIcon,
    title: "Connect or upload",
    body: "Point at a PostgreSQL, MySQL, SQL Server or SQLite database, upload a CSV, Excel or Parquet file, or read a JSON API.",
  },
  {
    icon: ScanSearchIcon,
    title: "Scan and accept suggested checks",
    body: "The first scan profiles every column inside your source and proposes checks: not null, unique, ranges, formats.",
  },
  {
    icon: BellRingIcon,
    title: "Get alerts",
    body: "Schedule scans and hear about a failing check, a falling score or an unusual change by email, Slack or webhook.",
  },
];

function Onboarding({ onCreate }: { onCreate: () => void }) {
  return (
    <div className="surface overflow-hidden">
      <div className="px-6 pt-8 pb-6 text-center sm:px-10">
        <div className="mx-auto mb-4 flex size-12 items-center justify-center rounded-2xl bg-primary-soft text-primary">
          <DatabaseIcon className="size-6" />
        </div>
        <h2 className="text-[19px] font-semibold tracking-[-0.02em]">Know your data is right before anyone else finds out it is not</h2>
        <p className="mx-auto mt-2 max-w-xl text-[13.5px] leading-relaxed text-muted-foreground">
          DataQuality profiles and checks your data where it lives, keeps a score per dataset, and tells you when something
          breaks. Start with a project: it holds your connections, datasets and alerts.
        </p>
      </div>
      <ol className="grid gap-3 px-6 pb-6 sm:px-10 md:grid-cols-3">
        {STEPS.map((s, i) => (
          <li key={s.title} className="rounded-xl bg-muted/70 p-4">
            <div className="flex items-center gap-2.5">
              <span className="flex size-7 items-center justify-center rounded-lg bg-card text-[12px] font-semibold text-primary shadow-[var(--elev-1)]">
                {i + 1}
              </span>
              <s.icon className="size-4 text-subtle" aria-hidden />
            </div>
            <div className="mt-3 text-[13.5px] font-semibold">{s.title}</div>
            <p className="mt-1 text-[12.5px] leading-relaxed text-muted-foreground">{s.body}</p>
          </li>
        ))}
      </ol>
      <div className="flex justify-center bg-muted/40 px-6 py-5">
        <Button size="lg" onClick={onCreate}>
          <FolderPlusIcon />
          Create your first project
        </Button>
      </div>
    </div>
  );
}

function NewProjectDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const create = useCreateProject();
  const router = useRouter();
  const [name, setName] = React.useState("");
  const [description, setDescription] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (open) {
      setName("");
      setDescription("");
      setError(null);
    }
  }, [open]);

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return setError("Name the project, for example the team or data product it covers.");
    create.mutate(
      { name: name.trim(), description: description.trim() },
      {
        onSuccess: (p) => {
          toast.success(`${p.name} is ready. Add a connection or a dataset next.`);
          onOpenChange(false);
          router.push(`/projects/${p.id}`);
        },
        onError: (err) => setError(errorMessage(err)),
      },
    );
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !create.isPending && onOpenChange(o)}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>New project</DialogTitle>
          <DialogDescription>You become its owner and can add members afterwards.</DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="flex min-h-0 flex-col" noValidate>
          <DialogBody className="space-y-4">
            <Field label="Name" htmlFor="np-name">
              <Input id="np-name" autoFocus maxLength={120} placeholder="Retail analytics" value={name} onChange={(e) => setName(e.target.value)} />
            </Field>
            <Field label="Description" htmlFor="np-desc" hint="Optional. What this project watches, and who to ask about it.">
              <Textarea id="np-desc" maxLength={2000} value={description} onChange={(e) => setDescription(e.target.value)} />
            </Field>
            {error && <FieldError>{error}</FieldError>}
          </DialogBody>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={create.isPending}>
              {create.isPending ? "Creating..." : "Create project"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
