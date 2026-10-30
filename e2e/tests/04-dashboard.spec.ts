import { expect, test } from "@playwright/test";

import { ADMIN, apiAs, call, demoProject, watchConsole } from "../helpers";

interface Dashboard {
  score: number | null;
  datasets: number;
  open_incidents: number;
  issues: { check_name: string }[];
}

/** AC7: the dashboard shows the same numbers as the API. */
test("the dashboard matches the API", async ({ page }) => {
  const errors = watchConsole(page);
  const api = await apiAs(ADMIN.email);
  const project = await demoProject(api);
  const dash = await call<Dashboard>(api, "GET", `/api/v1/projects/${project.id}/dashboard`);
  await page.goto(`/projects/${project.id}`);
  const score = `${dash.score?.toFixed(1).replace(/\.0$/, "")}%`;
  await expect(page.getByText(score, { exact: true }).first()).toBeVisible();
  await expect(page.getByText(dash.issues[0].check_name).first()).toBeVisible();
  for (const dim of ["Completeness", "Validity", "Consistency", "Uniqueness", "Freshness", "Volume"]) {
    await expect(page.getByText(dim, { exact: true }).first()).toBeVisible();
  }
  // The summary report downloads as a PDF.
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: /Download summary/ }).click();
  expect((await download).suggestedFilename()).toMatch(/\.pdf$/);
  expect(errors).toEqual([]);
  await api.dispose();
});
