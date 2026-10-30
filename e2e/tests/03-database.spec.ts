import { expect, test } from "@playwright/test";

import { ADMIN, apiAs, call, demoProject, watchConsole } from "../helpers";

/** A connected database: test it, browse its tables, add one as a dataset (whose first
 * scan profiles it), and read the profile. Everything runs through a read-only login. */
test("connection test, table browser, table dataset with a profile", async ({ page }) => {
  const errors = watchConsole(page);
  const api = await apiAs(ADMIN.email);
  const project = await demoProject(api);
  const datasets = () =>
    call<{ id: string; name: string }[]>(api, "GET", `/api/v1/projects/${project.id}/datasets`);
  const removeBackup = async () => {
    for (const d of (await datasets()).filter((d) => d.name === "orders_backup")) {
      await call(api, "DELETE", `/api/v1/projects/${project.id}/datasets/${d.id}`);
    }
  };
  await removeBackup(); // a run that died half way may have left it behind
  try {
    await page.goto(`/projects/${project.id}/connections`);
    const card = page.getByRole("region", { name: "Warehouse (PostgreSQL)" });
    await expect(card).toBeVisible();
    await card.getByRole("button", { name: "Test", exact: true }).click();
    await expect(page.getByText(/Connected\. \d+ tables and views visible/).first()).toBeVisible({
      timeout: 30_000,
    });
    await card.getByRole("button", { name: "Tables", exact: true }).click();
    await expect(page.getByText("products", { exact: true }).first()).toBeVisible();

    // Add the orders_backup table as a dataset (deleted at the end, so reruns pass).
    const before = await datasets();
    await page.getByPlaceholder("Search tables").fill("orders_backup");
    await page.getByRole("button", { name: "Add as dataset" }).first().click();
    await expect(page).toHaveURL(/tab=checks/, { timeout: 60_000 });
    const after = await datasets();
    expect(after.length).toBe(before.length + 1);

    const url = new URL(page.url());
    url.searchParams.set("tab", "profile");
    await page.goto(url.toString());
    await expect(page.getByText("Column profile")).toBeVisible({ timeout: 60_000 });
    expect(errors).toEqual([]);
  } finally {
    await removeBackup();
    await api.dispose();
  }
});
