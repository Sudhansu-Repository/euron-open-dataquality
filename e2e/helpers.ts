import { type APIRequestContext, type Browser, type BrowserContext, expect, type Page, request } from "@playwright/test";

const BASE = process.env.WEB_URL || "http://localhost:4910";
export const MAILPIT = process.env.MAILPIT_URL || "http://localhost:4925";
/** The mock service as the worker sees it (inside Compose): the webhook sink. */
export const MOCK_INTERNAL = process.env.MOCK_INTERNAL_URL || "http://mock-ai:4950";
export const PASSWORD = process.env.E2E_PASSWORD || process.env.DQ_DEMO_PASSWORD || "";
export const ADMIN = { email: process.env.E2E_EMAIL || "admin@dataquality.demo", password: PASSWORD };
export const EDITOR = "maya@dataquality.demo";
export const VIEWER = "arjun@dataquality.demo";

/** Mutations through the API carry the CSRF header the web app sends. */
export const CSRF = { "x-dq-csrf": "1" };

/** A per-run suffix so suites can run repeatedly against the same demo database. */
export const RUN = process.env.E2E_RUN || Date.now().toString(36).slice(-5);

/** Fail the test on any console error or CSP violation the page reports. */
export function watchConsole(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (m) => {
    if (m.type() === "error") errors.push(m.text());
  });
  page.on("pageerror", (e) => errors.push(e.message));
  return errors;
}

async function retrying(fn: () => Promise<import("@playwright/test").APIResponse>) {
  for (let i = 0; i < 10; i++) {
    const resp = await fn();
    if (resp.status() !== 429) return resp;
    await new Promise((r) => setTimeout(r, Number(resp.headers()["retry-after"] ?? "5") * 1000));
  }
  return fn();
}

/** An API client signed in as someone (waits out the sign-in limit if needed). */
export async function apiAs(email: string, password = PASSWORD): Promise<APIRequestContext> {
  const ctx = await request.newContext({ baseURL: BASE, extraHTTPHeaders: CSRF });
  const resp = await retrying(() => ctx.post("/api/v1/auth/login", { data: { email, password } }));
  expect(resp.status(), await resp.text()).toBe(200);
  return ctx;
}

/** JSON from the API, asserting success. */
export async function call<T = unknown>(ctx: APIRequestContext, method: string, path: string, data?: unknown): Promise<T> {
  const resp = await retrying(() => ctx.fetch(path, { method, data }));
  expect(resp.status(), `${method} ${path}: ${await resp.text()}`).toBeLessThan(300);
  return (resp.status() === 204 ? null : await resp.json()) as T;
}

/** A browser context carrying the session of an existing account. */
export async function signedInContext(browser: Browser, email: string): Promise<{ context: BrowserContext; page: Page }> {
  const api = await apiAs(email);
  const state = await api.storageState();
  await api.dispose();
  const context = await browser.newContext({ storageState: state });
  return { context, page: await context.newPage() };
}

export interface Project {
  id: string;
  name: string;
  slug: string;
}

/** The seeded demo project by slug. */
export async function demoProject(api: APIRequestContext, slug = "kestrel-retail"): Promise<Project> {
  const projects = await call<Project[]>(api, "GET", "/api/v1/projects");
  const found = projects.find((p) => p.slug === slug);
  expect(found, "run make demo first").toBeTruthy();
  return found as Project;
}

/** A fresh project for a suite, owned by the admin. */
export async function newProject(api: APIRequestContext, name: string): Promise<Project> {
  return call<Project>(api, "POST", "/api/v1/projects", { name: `${name} ${RUN}` });
}

/** 25 clean orders: the profile of this file suggests the checks the next version breaks. */
export const CLEAN_CSV = [
  "order_id,email,amount,country",
  ...Array.from({ length: 25 }, (_, i) => `${i + 1},buyer${i + 1}@example.com,${(10 + i * 3.5).toFixed(2)},${["IN", "US", "GB", "AE"][i % 4]}`),
].join("\n");

/** The next load, with known defects: 2 missing emails, 1 duplicate id, 1 negative amount. */
export const DEFECT_CSV = [
  "order_id,email,amount,country",
  "1,asha@example.com,120.50,IN",
  "2,,80.00,IN",
  "3,ravi@example.com,-15.00,US",
  "3,meera@example.com,42.00,GB",
  "4,,15.25,IN",
  "5,kabir@example.com,64.00,AE",
].join("\n");

/** Pick an option in one of the web app's custom selects. */
export async function choose(page: Page, triggerId: string, option: string | RegExp): Promise<void> {
  await page.locator(`#${triggerId}`).click();
  await page.getByRole("option", { name: option }).first().click();
}
