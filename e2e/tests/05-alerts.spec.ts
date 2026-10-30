import { expect, test } from "@playwright/test";

import { ADMIN, apiAs, call, MOCK_INTERNAL, newProject, RUN, watchConsole } from "../helpers";

/** AC12 in the browser: a rule and a webhook channel, a failing scan opens one incident,
 * the incident page shows the delivered notification, and resolving it works. */
test("alert rule, incident, notification, resolve", async ({ page }) => {
  const errors = watchConsole(page);
  const api = await apiAs(ADMIN.email);
  const project = await newProject(api, "Alerts");
  const base = `/api/v1/projects/${project.id}`;
  const ds = await call<{ id: string }>(api, "POST", `${base}/datasets`, { name: `events ${RUN}`, kind: "push" });
  await call(api, "POST", `${base}/datasets/${ds.id}/checks`, { type: "not_null", column: "email" });

  await page.goto(`/projects/${project.id}/alerts?tab=channels`);
  await page.getByRole("button", { name: /Add (a )?channel/ }).first().click();
  await page.getByRole("dialog").getByText("Webhook", { exact: true }).click();
  await page.getByRole("dialog").getByLabel("Name").fill("Ops hook");
  await page.getByRole("dialog").getByLabel(/URL/).fill(`${MOCK_INTERNAL}/webhook`);
  await page.getByRole("dialog").getByRole("button", { name: /Add channel|Save|Create/ }).click();
  await expect(page.getByText(/signing secret/i).first()).toBeVisible();
  await page.getByRole("button", { name: "I saved it" }).click();

  const channels = await call<{ id: string }[]>(api, "GET", `${base}/alert-channels`);
  await call(api, "POST", `${base}/alert-rules`, { name: "Errors", kind: "check_failed", channel_ids: channels.map((c) => c.id) });
  await call(api, "POST", `${base}/datasets/${ds.id}/records?wait=60`, { records: [{ email: "a@x.io" }, { email: null }] });

  await page.goto(`/projects/${project.id}/incidents`);
  await page.getByText(/email not null failed/).first().click();
  await expect(page).toHaveURL(/\/incidents\/[0-9a-f-]{36}/);
  await expect(page.getByText(/sent/i).first()).toBeVisible({ timeout: 60_000 });
  await page.getByRole("button", { name: "Resolve" }).click();
  await expect(page.getByText(/Resolved/).first()).toBeVisible();
  expect(errors.filter((e) => !e.includes("409"))).toEqual([]);
  await api.dispose();
});
