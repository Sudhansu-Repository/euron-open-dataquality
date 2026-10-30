"use client";

import { KeyRoundIcon, ShieldCheckIcon } from "lucide-react";
import * as React from "react";
import { toast } from "sonner";

import { AdminOnly } from "@/components/admin-only";
import { ErrorState } from "@/components/error-state";
import { PageHeader } from "@/components/page-header";
import { Surface, SurfaceHeader } from "@/components/surface";
import { Button } from "@/components/ui/button";
import { Chip } from "@/components/ui/chip";
import { Input } from "@/components/ui/input";
import { Field, FieldError } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { usePermissions } from "@/features/auth/api";
import { errorMessage } from "@/lib/api/errors";
import type { AdminSettings, SettingsUpdate } from "@/lib/api/types";

import { useOrgSettings, useUpdateOrgSettings } from "../api";

function Toggle({ label, hint, checked, onChange, disabled }: { label: string; hint?: string; checked: boolean; onChange: (v: boolean) => void; disabled?: boolean }) {
  return (
    <label className="flex items-start gap-3 rounded-xl bg-muted/70 px-4 py-3">
      <Switch checked={checked} onCheckedChange={onChange} disabled={disabled} aria-label={label} className="mt-0.5" />
      <span>
        <span className="block text-[13px] font-medium">{label}</span>
        {hint && <span className="block text-[12px] leading-relaxed text-muted-foreground">{hint}</span>}
      </span>
    </label>
  );
}

export function SettingsScreen() {
  const { user, admin } = usePermissions();
  const q = useOrgSettings();
  if (user && !admin) return <AdminOnly what="Instance settings" />;
  return (
    <>
      <PageHeader title="Instance settings" description="How this DataQuality server presents itself, who can sign up, and the optional AI assistant." />
      {q.isError ? (
        <div className="surface">
          <ErrorState error={q.error} title="Settings could not be loaded" onRetry={() => void q.refetch()} />
        </div>
      ) : !q.data ? (
        <Skeleton className="h-96 w-full max-w-3xl rounded-[14px]" />
      ) : (
        <SettingsForm settings={q.data} />
      )}
    </>
  );
}

function SettingsForm({ settings: s }: { settings: AdminSettings }) {
  const update = useUpdateOrgSettings();
  const [siteName, setSiteName] = React.useState(s.site_name);
  const [signup, setSignup] = React.useState(s.allow_signup);
  const [aiEnabled, setAiEnabled] = React.useState(s.ai_enabled);
  const [baseUrl, setBaseUrl] = React.useState(s.ai_base_url ?? "");
  const [model, setModel] = React.useState(s.ai_model ?? "");
  const [newKey, setNewKey] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);

  function save(extra: SettingsUpdate = {}) {
    if (!siteName.trim()) return setError("The site name cannot be empty.");
    if (aiEnabled && !/^https?:\/\//i.test(baseUrl.trim()))
      return setError("The assistant needs the address of an OpenAI-compatible endpoint, like http://ollama:11434/v1 or https://api.openai.com/v1.");
    if (aiEnabled && !model.trim()) return setError("Name the model to use, like llama3.1:8b or gpt-4o-mini.");
    setError(null);
    const body: SettingsUpdate = {
      site_name: siteName.trim(),
      allow_signup: signup,
      ai_enabled: aiEnabled,
      ai_base_url: baseUrl.trim() || null,
      ai_model: model.trim() || null,
      ...(newKey ? { ai_api_key: newKey } : {}),
      ...extra,
    };
    update.mutate(body, {
      onSuccess: () => {
        setNewKey("");
        toast.success("Settings saved.");
      },
      onError: (e) => setError(errorMessage(e)),
    });
  }

  return (
    <form
      className="max-w-3xl space-y-4"
      noValidate
      onSubmit={(e) => {
        e.preventDefault();
        save();
      }}
    >
      <Surface>
        <SurfaceHeader title="General" />
        <div className="grid gap-4 px-5 pb-5">
          <Field label="Site name" htmlFor="st-name" hint="Shown on the sign-in page, in the browser tab and in alert emails.">
            <Input id="st-name" maxLength={80} value={siteName} onChange={(e) => setSiteName(e.target.value)} />
          </Field>
          <Toggle
            label="Anyone can create an account"
            hint={signup ? "The sign-in page offers sign-up. New accounts are users with no projects until someone adds them." : "Only admins create accounts, on the Users page."}
            checked={signup}
            onChange={setSignup}
          />
        </div>
      </Surface>

      <Surface>
        <SurfaceHeader
          title="AI assistant"
          description="Optional. When on, people can ask for a plain-language explanation of an incident or draft a check from a sentence. Scans and checks never depend on it."
        />
        <div className="grid gap-4 px-5 pb-5">
          <Toggle
            label="Turn on the AI assistant"
            hint={aiEnabled ? "Requests go only to the endpoint below." : "Off: no AI request is ever made, and the Explain and Draft buttons say so."}
            checked={aiEnabled}
            onChange={setAiEnabled}
          />
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Endpoint (OpenAI-compatible)" htmlFor="st-url" hint="A local model (Ollama, vLLM) keeps everything on your servers.">
              <Input id="st-url" placeholder="http://ollama:11434/v1" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} />
            </Field>
            <Field label="Model" htmlFor="st-model">
              <Input id="st-model" placeholder="llama3.1:8b" value={model} onChange={(e) => setModel(e.target.value)} />
            </Field>
          </div>
          <Field
            label="API key"
            htmlFor="st-key"
            labelExtra={s.ai_has_key ? <Chip tone="success" className="ml-1">A key is stored</Chip> : <Chip tone="neutral" className="ml-1">No key</Chip>}
            hint="Stored sealed and never shown again. Type a new one to replace it; leave it empty to keep the current one."
          >
            <div className="flex flex-col gap-2 sm:flex-row">
              <Input
                id="st-key"
                type="password"
                autoComplete="off"
                placeholder={s.ai_has_key ? "Replace the stored key" : "Only if the endpoint needs one"}
                value={newKey}
                onChange={(e) => setNewKey(e.target.value)}
              />
              {s.ai_has_key && (
                <Button type="button" variant="destructive-soft" onClick={() => save({ ai_api_key: "" })} disabled={update.isPending} className="shrink-0">
                  <KeyRoundIcon />
                  Remove key
                </Button>
              )}
            </div>
          </Field>
          <p className="flex items-start gap-2.5 rounded-xl bg-muted px-4 py-3 text-[12.5px] leading-relaxed text-muted-foreground">
            <ShieldCheckIcon className="mt-0.5 size-4 shrink-0 text-primary" aria-hidden />
            The assistant sees column names, statistics and check results. Row values are sent only for projects whose owners allow
            it in their project settings.
          </p>
        </div>
      </Surface>
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div>{error && <FieldError>{error}</FieldError>}</div>
        <Button type="submit" disabled={update.isPending}>
          {update.isPending ? "Saving..." : "Save settings"}
        </Button>
      </div>
    </form>
  );
}
