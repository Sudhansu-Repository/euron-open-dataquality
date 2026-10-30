import { request } from "@playwright/test";

import { CSRF, RUN } from "./helpers";

/** Delete the projects this run created (their names end in the run suffix), so the demo
 * stack stays as `make demo` left it however often the suites run. */
export default async function globalTeardown(): Promise<void> {
  const baseURL = process.env.WEB_URL || "http://localhost:4910";
  const ctx = await request.newContext({ baseURL, extraHTTPHeaders: CSRF, storageState: ".auth/admin.json" });
  try {
    const resp = await ctx.get("/api/v1/projects");
    if (!resp.ok()) return;
    for (const p of (await resp.json()) as { id: string; name: string }[]) {
      if (p.name.endsWith(` ${RUN}`)) await ctx.delete(`/api/v1/projects/${p.id}`);
    }
  } finally {
    await ctx.dispose();
  }
}
