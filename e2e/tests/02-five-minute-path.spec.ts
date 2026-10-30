import { expect, test } from "@playwright/test";

import { CLEAN_CSV, DEFECT_CSV, RUN, watchConsole } from "../helpers";

/** AC6 and AC18: a new person creates a project, uploads a file, accepts the checks
 * suggested from its profile (no AI), and when a broken version arrives the scan shows
 * exactly what is wrong, all in the browser. */
test("project, upload, suggested checks, a broken load caught", async ({ page }) => {
  const errors = watchConsole(page);
  await page.goto("/projects?new=1");
  await page.locator("#np-name").fill(`Five minutes ${RUN}`);
  await page.getByRole("button", { name: "Create project" }).click();
  await expect(page).toHaveURL(/\/projects\/[0-9a-f-]{36}/);
  const pid = /\/projects\/([0-9a-f-]{36})/.exec(page.url())?.[1];

  await page.goto(`/projects/${pid}/datasets/new`);
  await page.getByText("Upload a file", { exact: true }).click();
  await page.locator("input[type=file]").setInputFiles({ name: "orders.csv", mimeType: "text/csv", buffer: Buffer.from(CLEAN_CSV) });
  await page.locator("#nd-name").fill("Orders");
  await page.getByRole("button", { name: "Add and scan" }).click();
  await expect(page).toHaveURL(/tab=checks/, { timeout: 60_000 });

  const add = page.getByRole("button", { name: /Add selected \(\d+\)/ });
  await expect(add).toBeVisible({ timeout: 60_000 });
  await add.click();
  await expect(page.getByText("order_id unique").first()).toBeVisible();

  // The next load is broken: upload it as a new version and scan.
  await page.locator("input[type=file]").first().setInputFiles({ name: "orders.csv", mimeType: "text/csv", buffer: Buffer.from(DEFECT_CSV) });
  await expect(page.getByText(/version 2|new version|Uploaded/i).first()).toBeVisible({ timeout: 30_000 });
  await page.getByRole("button", { name: "Scan now" }).click();
  await expect(page).toHaveURL(/\/scans\/[0-9a-f-]{36}/);
  await expect(page.getByText("1 duplicate value in 1 group")).toBeVisible({ timeout: 90_000 });
  await expect(page.getByText("2 of 6 rows fail (33.33%)")).toBeVisible();
  expect(errors).toEqual([]);
});
