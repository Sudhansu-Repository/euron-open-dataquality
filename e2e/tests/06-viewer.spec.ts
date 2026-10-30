import { expect, test } from "@playwright/test";

import { ADMIN, apiAs, call, demoProject, signedInContext, VIEWER, watchConsole } from "../helpers";

/** AC15 in the browser: a viewer reads everything and changes nothing. */
test("a viewer sees results and no controls", async ({ browser }) => {
  const admin = await apiAs(ADMIN.email);
  const project = await demoProject(admin);
  const datasets = await call<{ id: string; name: string }[]>(admin, "GET", `/api/v1/projects/${project.id}/datasets`);
  const customers = datasets.find((d) => d.name === "Customers");
  const { context, page } = await signedInContext(browser, VIEWER);
  const errors = watchConsole(page);
  await page.goto(`/projects/${project.id}/datasets/${customers?.id}?tab=checks`);
  await expect(page.getByText("email not null").first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Scan now" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /Add check/ })).toHaveCount(0);
  await page.goto(`/projects/${project.id}/settings`);
  await expect(page.getByRole("tab", { name: /API keys/ })).toHaveCount(0);
  expect(errors).toEqual([]);
  await context.close();
  await admin.dispose();
});
