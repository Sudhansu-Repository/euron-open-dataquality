"use client";

import { ArrowRightIcon, BellRingIcon, DatabaseZapIcon, EyeIcon, EyeOffIcon, ScanSearchIcon, ServerIcon, ShieldCheckIcon } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import * as React from "react";
import { toast } from "sonner";

import { BrandLogo, BrandMark } from "@/components/brand";
import { ThemeToggle } from "@/components/theme-toggle";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { FieldError, FieldHint, Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { errorMessage } from "@/lib/api/errors";
import { safeNext } from "@/lib/auth-redirect";
import { cn } from "@/lib/cn";

import { useLogin, usePublicSettings, useSignup } from "../api";

import { MIN_PASSWORD } from "./change-password-dialog";

const PITCH = [
  { icon: ScanSearchIcon, title: "Profiling", body: "Every column summarized: types, missing values, ranges, common values and shapes." },
  { icon: DatabaseZapIcon, title: "Checks run in your database", body: "Counted where the data lives. Only results and a few failing samples come back." },
  { icon: BellRingIcon, title: "Alerts that resolve themselves", body: "One message per problem by email, Slack or webhook, and another when it clears." },
  { icon: ServerIcon, title: "Yours to run", body: "Self-hosted and MIT licensed. Your rows never leave your servers." },
];

type Outcome = "pass" | "fail" | "warn";
const DEMO_RESULTS: { check: string; result: string; outcome: Outcome }[] = [
  { check: "email not null", result: "8 missing", outcome: "fail" },
  { check: "id unique", result: "3 duplicates", outcome: "fail" },
  { check: "pin_code format", result: "12 odd shapes", outcome: "warn" },
  { check: "price range", result: "pass", outcome: "pass" },
  { check: "orders fresh", result: "pass", outcome: "pass" },
];
const OUTCOME_CLASS: Record<Outcome, string> = {
  pass: "bg-[var(--panel-pass-soft)] text-[var(--panel-pass)]",
  fail: "bg-[var(--panel-fail-soft)] text-[var(--panel-fail)]",
  warn: "bg-[var(--panel-warn-soft)] text-[var(--panel-warn)]",
};

type Mode = "login" | "signup";

export function LoginScreen({ mode: requested = "login" }: { mode?: Mode }) {
  const router = useRouter();
  const params = useSearchParams();
  const login = useLogin();
  const signup = useSignup();
  const settings = usePublicSettings();
  const [name, setName] = React.useState("");
  const [email, setEmail] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [show, setShow] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const setup = settings.data?.needs_setup === true;
  // On a fresh server the first account becomes the admin, whichever page was opened.
  const mode: Mode | "setup" = setup ? "setup" : requested;
  const creating = mode !== "login";
  const signupOpen = settings.data?.allow_signup === true;
  const expired = params.get("reason") === "expired";
  const pending = login.isPending || signup.isPending;
  const next = params.get("next");
  const otherHref = (target: Mode) => `/${target}${next ? `?next=${encodeURIComponent(next)}` : ""}`;
  const siteName = settings.data?.site_name || "DataQuality";

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!email.trim() || !password || (creating && !name.trim())) {
      setError(creating ? "Enter your name, email and a password." : "Enter your email and password.");
      return;
    }
    if (creating && password.length < MIN_PASSWORD) {
      setError(`Use at least ${MIN_PASSWORD} characters, with upper and lower case letters and a digit.`);
      return;
    }
    setError(null);
    const done = {
      onSuccess: (session: { user: { name: string } }) => {
        const first = session.user.name.split(" ")[0];
        toast.success(mode === "setup" ? `Welcome, ${first}. You are the admin of this server.` : creating ? `Welcome, ${first}.` : `Welcome back, ${first}.`);
        router.replace(mode === "setup" ? "/projects" : safeNext(next));
      },
      onError: (err: unknown) => setError(errorMessage(err)),
    };
    if (creating) signup.mutate({ name: name.trim(), email: email.trim(), password }, done);
    else login.mutate({ email: email.trim(), password }, done);
  }

  const title = mode === "setup" ? "Create the admin account" : mode === "signup" ? "Create your account" : `Sign in to ${siteName}`;
  const subtitle =
    mode === "setup"
      ? "This server has no accounts yet. The first account becomes the admin: it can add users, projects and instance settings."
      : mode === "signup"
        ? "Then ask a project owner to add you to their project, or create your own."
        : "Pick up your datasets, scans and incidents where you left them.";
  const blocked = mode === "signup" && settings.isSuccess && !signupOpen;

  return (
    <div className="grid min-h-dvh bg-background lg:grid-cols-[minmax(0,1fr)_minmax(0,1.05fr)]">
      <div className="relative flex min-w-0 flex-col px-5 py-6 sm:px-10">
        <div className="flex items-center justify-between">
          <BrandLogo />
          <ThemeToggle />
        </div>
        <div className="flex flex-1 items-center justify-center py-10">
          <div className="w-full max-w-[360px]">
            {settings.isPending ? (
              <div className="space-y-3" aria-busy aria-label="Loading">
                <Skeleton className="h-8 w-3/4" />
                <Skeleton className="h-4 w-full" />
                <Skeleton className="mt-6 h-10 w-full" />
                <Skeleton className="h-10 w-full" />
              </div>
            ) : (
              <>
                {mode === "setup" && (
                  <div className="mb-4 inline-flex items-center gap-1.5 rounded-full bg-primary-soft px-2.5 py-1 text-[12px] font-semibold text-primary">
                    <ShieldCheckIcon className="size-3.5" />
                    First run
                  </div>
                )}
                <h1 className="text-[26px] leading-tight font-semibold tracking-[-0.025em]">{title}</h1>
                <p className="mt-1.5 text-[13.5px] leading-relaxed text-muted-foreground">{subtitle}</p>
                {expired && mode === "login" && (
                  <div role="status" className="mt-5 rounded-lg bg-warning-soft px-3.5 py-2.5 text-[13px] text-warning">
                    Your session expired. Sign in again to pick up where you left off.
                  </div>
                )}
                {blocked && (
                  <div role="status" className="mt-5 rounded-lg bg-warning-soft px-3.5 py-2.5 text-[13px] text-warning">
                    Sign-up is closed on this server. Ask an admin to create your account.
                  </div>
                )}
                {settings.isError && (
                  <div role="alert" className="mt-5 rounded-lg bg-danger-soft px-3.5 py-2.5 text-[13px] text-danger">
                    {errorMessage(settings.error)}
                  </div>
                )}
                <form onSubmit={submit} className="mt-6 space-y-4" noValidate>
                  {creating && (
                    <div className="space-y-1.5">
                      <Label htmlFor="name">Name</Label>
                      <Input id="name" autoComplete="name" autoFocus className="h-10" value={name} onChange={(e) => setName(e.target.value)} disabled={blocked} />
                    </div>
                  )}
                  <div className="space-y-1.5">
                    <Label htmlFor="email">Email</Label>
                    <Input
                      id="email"
                      type="email"
                      autoComplete={creating ? "email" : "username"}
                      autoFocus={!creating}
                      placeholder="you@company.com"
                      className="h-10"
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                      aria-invalid={!!error || undefined}
                      disabled={blocked}
                    />
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="password">Password</Label>
                    <div className="relative">
                      <Input
                        id="password"
                        type={show ? "text" : "password"}
                        autoComplete={creating ? "new-password" : "current-password"}
                        className="h-10 pr-10"
                        value={password}
                        onChange={(e) => setPassword(e.target.value)}
                        aria-invalid={!!error || undefined}
                        disabled={blocked}
                      />
                      <button
                        type="button"
                        onClick={() => setShow((s) => !s)}
                        aria-label={show ? "Hide password" : "Show password"}
                        className="absolute top-1/2 right-2 flex size-7 -translate-y-1/2 items-center justify-center rounded-md text-subtle hover:text-foreground focus-visible:outline-2 focus-visible:outline-ring"
                      >
                        {show ? <EyeOffIcon className="size-4" /> : <EyeIcon className="size-4" />}
                      </button>
                    </div>
                    {creating && !error && <FieldHint>At least {MIN_PASSWORD} characters, with upper and lower case letters and a digit.</FieldHint>}
                  </div>
                  {error && <FieldError>{error}</FieldError>}
                  <Button type="submit" size="lg" className="w-full" disabled={pending || blocked}>
                    {pending
                      ? creating
                        ? "Creating the account..."
                        : "Signing in..."
                      : mode === "setup"
                        ? "Create admin account"
                        : mode === "signup"
                          ? "Create account"
                          : "Sign in"}
                    {!pending && <ArrowRightIcon />}
                  </Button>
                </form>
                {mode !== "setup" && (
                  <p className="mt-6 text-xs leading-relaxed text-muted-foreground">
                    {mode === "signup" ? (
                      <>
                        Already have an account?{" "}
                        <Link href={otherHref("login")} className="font-medium text-primary underline-offset-2 hover:underline">
                          Sign in
                        </Link>
                        .
                      </>
                    ) : signupOpen ? (
                      <>
                        New here?{" "}
                        <Link href={otherHref("signup")} className="font-medium text-primary underline-offset-2 hover:underline">
                          Create an account
                        </Link>
                        . Forgot your password? Ask an admin to reset it.
                      </>
                    ) : (
                      <>
                        Accounts are created by an admin. Forgot your password? Ask an admin to reset it, or run{" "}
                        <code className="rounded bg-muted px-1 py-0.5 font-mono text-[11px]">dataquality create-admin</code> on the server.
                      </>
                    )}
                  </p>
                )}
              </>
            )}
          </div>
        </div>
        <p className="text-[11.5px] text-faint">Self-hosted. Your rows stay in your databases; only results and samples are kept.</p>
      </div>

      <BrandPanel />
    </div>
  );
}

function BrandPanel() {
  return (
    <aside className="relative hidden overflow-hidden bg-[var(--panel)] p-10 text-white lg:flex lg:flex-col lg:justify-between">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 opacity-90"
        style={{
          background:
            "radial-gradient(60% 50% at 80% 10%, var(--panel-glow), transparent 70%), radial-gradient(50% 45% at 10% 90%, var(--panel-glow-2), transparent 70%)",
        }}
      />
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 opacity-[0.07]"
        style={{
          backgroundImage: "linear-gradient(white 1px, transparent 1px), linear-gradient(90deg, white 1px, transparent 1px)",
          backgroundSize: "36px 36px",
        }}
      />
      <div className="relative flex items-center gap-2 text-[13px] font-medium text-white/70">
        <BrandMark className="size-6" />
        Open-source data quality
      </div>

      <div className="relative max-w-lg">
        <h2 className="text-[34px] leading-[1.12] font-semibold tracking-[-0.03em]">
          Know your data is right,
          <br />
          <span className="text-[var(--panel-accent)]">before your dashboards say otherwise.</span>
        </h2>
        <p className="mt-3 text-[14.5px] leading-relaxed text-white/65">
          Profile databases, files and APIs, accept the checks DataQuality suggests, and get told the moment a scan finds missing,
          duplicate or out-of-range values.
        </p>

        <div className="mt-8 rounded-2xl bg-white/[0.06] p-4 shadow-[0_20px_60px_rgba(0,0,0,0.35)] ring-1 ring-white/10 backdrop-blur" aria-label="Example scan results">
          <div className="flex items-center justify-between gap-3 text-[12px] text-white/55">
            <span>
              <span className="font-mono text-white/80">customers</span>, scanned 2 minutes ago
            </span>
            <span className="rounded-full bg-[var(--panel-accent-soft)] px-2 py-0.5 font-semibold text-[var(--panel-accent)]">Score 96.4%</span>
          </div>
          <ul className="mt-3 space-y-1.5 font-mono text-[12px]">
            {DEMO_RESULTS.map((r) => (
              <li key={r.check} className="flex items-center justify-between gap-3 rounded-lg bg-white/[0.04] px-3 py-1.5">
                <span className="truncate text-white/75">{r.check}</span>
                <span className={cn("shrink-0 rounded-full px-2 py-0.5 font-semibold", OUTCOME_CLASS[r.outcome])}>{r.result}</span>
              </li>
            ))}
          </ul>
        </div>

        <ul className="mt-8 grid gap-5 sm:grid-cols-2">
          {PITCH.map((p) => (
            <li key={p.title} className="flex gap-3">
              <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-white/10 text-[var(--panel-accent)]">
                <p.icon className="size-4" />
              </span>
              <div>
                <div className="text-[13px] font-semibold">{p.title}</div>
                <div className="mt-0.5 text-[12.5px] leading-relaxed text-white/55">{p.body}</div>
              </div>
            </li>
          ))}
        </ul>
      </div>

      <div className="relative text-[11.5px] text-white/40">MIT licensed. Part of the Euron open-source initiative.</div>
    </aside>
  );
}
