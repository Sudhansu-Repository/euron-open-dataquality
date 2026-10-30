"use client";

import { KeyRoundIcon, SlidersHorizontalIcon, Trash2Icon, UsersIcon } from "lucide-react";
import { useRouter } from "next/navigation";
import * as React from "react";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { ErrorState } from "@/components/error-state";
import { Hint } from "@/components/hint";
import { PageHeader } from "@/components/page-header";
import { RoleNote } from "@/components/role-note";
import { Surface, SurfaceHeader } from "@/components/surface";
import { Button } from "@/components/ui/button";
import { Input, Textarea } from "@/components/ui/input";
import { Field, FieldError } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { errorMessage } from "@/lib/api/errors";
import type { Project } from "@/lib/api/types";
import { useUiPrefs } from "@/lib/store";
import { useTabParam } from "@/lib/use-tab-param";

import { useCurrentProject, useDeleteProject, useUpdateProject } from "../api";

import { ApiKeysTab } from "./api-keys-tab";
import { MembersTab } from "./members-tab";

const TABS = ["general", "members", "api-keys"] as const;

export function ProjectSettingsScreen() {
  const { pid, project, canOwn, query } = useCurrentProject();
  const [rawTab, setTab] = useTabParam("general", TABS);
  // API keys are an owner's tool; everyone else lands on General.
  const tab = rawTab === "api-keys" && project && !canOwn ? "general" : rawTab;

  return (
    <>
      <PageHeader title="Project settings" description="How this project scans and keeps results, who works in it, and the keys your pipelines use." />
      {query.isPending ? (
        <Skeleton className="h-96 w-full rounded-[14px]" />
      ) : query.isError ? (
        <div className="surface">
          <ErrorState error={query.error} title="Project settings could not be loaded" onRetry={() => void query.refetch()} />
        </div>
      ) : (
        <Tabs value={tab} onValueChange={(v) => setTab(String(v))}>
          <TabsList>
            <TabsTrigger value="general">
              <SlidersHorizontalIcon />
              General
            </TabsTrigger>
            <TabsTrigger value="members">
              <UsersIcon />
              Members
            </TabsTrigger>
            {canOwn && (
              <TabsTrigger value="api-keys">
                <KeyRoundIcon />
                API keys
              </TabsTrigger>
            )}
          </TabsList>
          <TabsContent value="general">
            <GeneralTab key={query.data.id} project={query.data} canOwn={canOwn} />
          </TabsContent>
          <TabsContent value="members">
            <MembersTab pid={pid} canOwn={canOwn} />
          </TabsContent>
          {canOwn && (
            <TabsContent value="api-keys">
              <ApiKeysTab pid={pid} />
            </TabsContent>
          )}
        </Tabs>
      )}
    </>
  );
}

function GeneralTab({ project: p, canOwn }: { project: Project; canOwn: boolean }) {
  const update = useUpdateProject(p.id);
  const [name, setName] = React.useState(p.name);
  const [description, setDescription] = React.useState(p.description);
  const [sample, setSample] = React.useState(String(p.sample_size));
  const [retention, setRetention] = React.useState(String(p.retention_days));
  const [sensitivity, setSensitivity] = React.useState(String(p.anomaly_sensitivity));
  const [aiSamples, setAiSamples] = React.useState(p.ai_allow_samples);
  const [error, setError] = React.useState<string | null>(null);
  const ro = !canOwn;

  function save(e: React.FormEvent) {
    e.preventDefault();
    const s = Number(sample);
    const r = Number(retention);
    const a = Number(sensitivity);
    if (!name.trim()) return setError("The project needs a name.");
    if (!Number.isInteger(s) || s < 0 || s > 200) return setError("Failing-row samples must be a whole number from 0 to 200.");
    if (!Number.isInteger(r) || r < 1 || r > 3650) return setError("Retention must be a whole number of days from 1 to 3650.");
    if (!Number.isFinite(a) || a < 2 || a > 10) return setError("Anomaly sensitivity must be from 2 to 10.");
    setError(null);
    update.mutate(
      { name: name.trim(), description: description.trim(), sample_size: s, retention_days: r, anomaly_sensitivity: a, ai_allow_samples: aiSamples },
      { onSuccess: () => toast.success("Project settings saved."), onError: (err) => setError(errorMessage(err)) },
    );
  }

  return (
    <div className="max-w-3xl space-y-4">
      {ro && <RoleNote>Only owners change these settings. You can read them to understand how scans behave here.</RoleNote>}
      <form onSubmit={save} noValidate>
        <Surface>
          <SurfaceHeader title="About" />
          <div className="grid gap-4 px-5 pb-5">
            <Field label="Name" htmlFor="ps-name">
              <Input id="ps-name" maxLength={120} disabled={ro} value={name} onChange={(e) => setName(e.target.value)} />
            </Field>
            <Field label="Description" htmlFor="ps-desc">
              <Textarea id="ps-desc" maxLength={2000} disabled={ro} value={description} onChange={(e) => setDescription(e.target.value)} />
            </Field>
          </div>
          <SurfaceHeader title="Scanning and history" className="pt-1" />
          <div className="grid gap-4 px-5 pb-5 sm:grid-cols-3">
            <Field label="Failing-row samples" htmlFor="ps-sample" hint="Rows kept per failing check (0 to 200). 0 keeps none.">
              <Input id="ps-sample" inputMode="numeric" disabled={ro} value={sample} onChange={(e) => setSample(e.target.value)} />
            </Field>
            <Field label="Keep results for" htmlFor="ps-ret" hint="Days of scans and samples kept. Older ones are purged.">
              <div className="relative">
                <Input id="ps-ret" inputMode="numeric" disabled={ro} className="pr-12" value={retention} onChange={(e) => setRetention(e.target.value)} />
                <span className="pointer-events-none absolute top-1/2 right-3 -translate-y-1/2 text-[12px] text-subtle">days</span>
              </div>
            </Field>
            <Field
              label="Anomaly sensitivity"
              htmlFor="ps-anom"
              labelExtra={
                <Hint text="How far a metric must move from its own history to count as unusual, in robust deviations from the median of recent scans. Lower flags more changes; 3.5 is a good default." />
              }
              hint="From 2 (sensitive) to 10 (only big swings). Default 3.5."
            >
              <Input id="ps-anom" inputMode="decimal" disabled={ro} value={sensitivity} onChange={(e) => setSensitivity(e.target.value)} />
            </Field>
          </div>
          <div className="px-5 pb-5">
            <label className="flex items-start gap-3 rounded-xl bg-muted/70 px-4 py-3">
              <Switch checked={aiSamples} onCheckedChange={setAiSamples} disabled={ro} aria-label="Allow the AI assistant to see sample values" className="mt-0.5" />
              <span>
                <span className="block text-[13px] font-medium">Allow the AI assistant to see sample values</span>
                <span className="block text-[12px] leading-relaxed text-muted-foreground">
                  {aiSamples
                    ? "Explanations and drafted checks may include a few failing values from this project."
                    : "Off: the assistant sees column names, statistics and check results, never row values."}{" "}
                  Applies only when an admin has turned the assistant on.
                </span>
              </span>
            </label>
          </div>
          {canOwn && (
            <div className="flex flex-col gap-2 rounded-b-[14px] bg-muted/50 px-5 py-3.5 sm:flex-row sm:items-center sm:justify-between">
              <div>{error && <FieldError>{error}</FieldError>}</div>
              <Button type="submit" disabled={update.isPending}>
                {update.isPending ? "Saving..." : "Save settings"}
              </Button>
            </div>
          )}
        </Surface>
      </form>
      {canOwn && <DangerZone project={p} />}
    </div>
  );
}

function DangerZone({ project }: { project: Project }) {
  const del = useDeleteProject(project.id);
  const router = useRouter();
  const setLast = useUiPrefs((s) => s.setLastProject);
  const [open, setOpen] = React.useState(false);
  const [typed, setTyped] = React.useState("");
  React.useEffect(() => {
    if (open) setTyped("");
  }, [open]);

  return (
    <Surface>
      <SurfaceHeader title="Danger zone" />
      <div className="flex flex-col gap-3 px-5 pb-5 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-[13px] leading-relaxed text-muted-foreground">
          Delete this project with its connections, datasets, checks, scan history, alerts and API keys. Your source databases are
          not touched.
        </p>
        <Button variant="destructive-soft" onClick={() => setOpen(true)} className="shrink-0">
          <Trash2Icon />
          Delete project
        </Button>
      </div>
      <ConfirmDialog
        open={open}
        onOpenChange={setOpen}
        title={`Delete ${project.name}?`}
        description="This cannot be undone. Pipelines that use its API keys start failing at once."
        confirmLabel="Delete forever"
        pending={del.isPending}
        confirmDisabled={typed !== project.name}
        onConfirm={() => {
          if (typed !== project.name) return;
          del.mutate(undefined, {
            onSuccess: () => {
              setLast(null);
              toast.success(`${project.name} deleted.`);
              router.replace("/projects");
            },
            onError: (err) => toast.error(errorMessage(err)),
          });
        }}
      >
        <Field label={<span>Type <span className="font-mono">{project.name}</span> to confirm</span>} htmlFor="del-confirm">
          <Input id="del-confirm" autoComplete="off" value={typed} onChange={(e) => setTyped(e.target.value)} aria-invalid={typed.length > 0 && typed !== project.name ? true : undefined} />
        </Field>
        {typed.length > 0 && typed !== project.name && <p className="mt-1.5 text-[12px] text-muted-foreground">The name does not match yet.</p>}
      </ConfirmDialog>
    </Surface>
  );
}
