import { expect, test } from "@playwright/test";

import { ADMIN, watchConsole } from "../helpers";

test.describe("sign in", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test("a wrong password is explained; the right one signs you in", async ({ page }) => {
    const errors = watchConsole(page);
    await page.goto("/login");
    await page.locator("#email").fill(ADMIN.email);
    await page.locator("#password").fill("not-the-password");
    await page.getByRole("button", { name: "Sign in", exact: true }).click();
    await expect(page.getByText("Email or password is incorrect")).toBeVisible();
    await page.locator("#password").fill(ADMIN.password);
    await page.getByRole("button", { name: "Sign in", exact: true }).click();
    await expect(page.getByRole("button", { name: "Account menu" })).toBeVisible();
    await expect(page).toHaveURL(/\/projects\/[0-9a-f-]{36}/);
    expect(errors.filter((e) => !e.includes("401"))).toEqual([]);
  });

  test("every page sends you to sign in, then back to where you were", async ({ page }) => {
    await page.goto("/admin/audit");
    await expect(page).toHaveURL(/\/login\?next=%2Fadmin%2Faudit/);
    await page.locator("#email").fill(ADMIN.email);
    await page.locator("#password").fill(ADMIN.password);
    await page.getByRole("button", { name: "Sign in", exact: true }).click();
    await expect(page).toHaveURL(/\/admin\/audit$/);
  });

  test("a crafted next= cannot send you to another site", async ({ page }) => {
    await page.goto("/login?next=/%5Cevil.example");
    await page.locator("#email").fill(ADMIN.email);
    await page.locator("#password").fill(ADMIN.password);
    await page.getByRole("button", { name: "Sign in", exact: true }).click();
    await expect(page.getByRole("button", { name: "Account menu" })).toBeVisible();
    expect(new URL(page.url()).host).toBe(new URL(process.env.WEB_URL || "http://localhost:4910").host);
  });

  test("signing out ends the session for good", async ({ page }) => {
    await page.goto("/login");
    await page.locator("#email").fill(ADMIN.email);
    await page.locator("#password").fill(ADMIN.password);
    await page.getByRole("button", { name: "Sign in", exact: true }).click();
    await expect(page.getByRole("button", { name: "Account menu" })).toBeVisible();
    const cookie = (await page.context().cookies()).find((c) => c.name === "dq_session");
    expect(cookie).toBeTruthy();
    await page.getByRole("button", { name: "Account menu" }).click();
    await page.getByRole("menuitem", { name: "Sign out" }).click();
    await expect(page).toHaveURL(/\/login/);
    const replay = await page.request.get("/api/v1/auth/me", { headers: { cookie: `dq_session=${cookie?.value}` } });
    expect(replay.status()).toBe(401);
  });
});
