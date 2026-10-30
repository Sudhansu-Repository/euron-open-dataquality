import { request } from "@playwright/test";

import { ADMIN, CSRF } from "./helpers";

/**
 * Sign in once as the demo admin and share the session cookie with every suite. Signing
 * in per test would meet the per-IP sign-in limit on repeated runs, which is the limit
 * working as intended.
 */
export default async function globalSetup(): Promise<void> {
  const baseURL = process.env.WEB_URL || "http://localhost:4910";
  const ctx = await request.newContext({ baseURL, extraHTTPHeaders: CSRF });
  const resp = await ctx.post("/api/v1/auth/login", { data: ADMIN });
  if (!resp.ok()) throw new Error(`demo sign-in failed (${resp.status()}): run make demo first`);
  await ctx.storageState({ path: ".auth/admin.json" });
  await ctx.dispose();
}
