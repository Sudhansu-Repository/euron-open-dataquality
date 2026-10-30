/**
 * Curated README screenshots and tour frames from the seeded stack (real data only).
 *
 *   make up && make demo
 *   cd scripts/qa && QA_PASSWORD=... node screenshots.mjs
 *   ../../scripts/qa/make-tour.sh        (stitches the frames into docs/assets/tour.gif)
 *
 * The scan capture is a real scan: the editor starts it from the dataset page and the
 * worker runs it against the demo warehouse while the page follows it live.
 *
 * Writes docs/assets/screenshots/NN-name.png and scripts/qa/output/tour/NN.png.
 */
import { mkdir, rm } from "node:fs/promises";
import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import puppeteer from "puppeteer";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const BASE = process.env.QA_BASE ?? "http://localhost:4910";
const PASSWORD = process.env.QA_PASSWORD ?? process.env.DQ_DEMO_PASSWORD ?? "";
const SHOTS = path.resolve(HERE, "../../docs/assets/screenshots");
const TOUR = path.resolve(HERE, "output/tour");
const CHROME = process.env.CHROME_PATH && existsSync(process.env.CHROME_PATH) ? process.env.CHROME_PATH : undefined;
const DESKTOP = { width: 1440, height: 900, deviceScaleFactor: 1 };
const PHONE = { width: 390, height: 844, isMobile: true, hasTouch: true, deviceScaleFactor: 2 };

const ADMIN = "admin@dataquality.demo";
const EDITOR = "maya@dataquality.demo";

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let tourIndex = 0;

async function api(token, method, url, body) {
  const resp = await fetch(`${BASE}${url}`, {
    method,
    headers: { authorization: `Bearer ${token}`, "content-type": "application/json", "x-dq-csrf": "1" },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!resp.ok) throw new Error(`${method} ${url}: ${resp.status} ${await resp.text()}`);
  return resp.status === 204 ? null : resp.json();
}

async function token(email) {
  const resp = await fetch(`${BASE}/api/v1/auth/login`, {
    method: "POST",
    headers: { "content-type": "application/json", "x-dq-csrf": "1" },
    body: JSON.stringify({ email, password: PASSWORD }),
  });
  if (!resp.ok) throw new Error(`sign-in for ${email} failed (${resp.status}): run make demo first`);
  return (await resp.json()).session_token;
}

async function settle(page, ms = 1200) {
  await page.waitForNetworkIdle({ idleTime: 400, timeout: 20_000 }).catch(() => {});
  await sleep(ms);
}

/** A curated shot, plus a viewport-sized tour frame (all tour frames share one size). */
async function shot(page, name, { tour = true, curated = true, fullPage = false } = {}) {
  await page.mouse.move(1, 1); // no hover tooltip in a capture
  await sleep(250);
  if (curated) await page.screenshot({ path: path.join(SHOTS, `${name}.png`), fullPage });
  if (tour) {
    await page.screenshot({
      path: path.join(TOUR, `${String(++tourIndex).padStart(2, "0")}.png`),
      clip: { x: 0, y: 0, width: DESKTOP.width, height: DESKTOP.height },
    });
  }
  console.log(`saved ${name}`);
}

async function open(page, url, ms = 1500) {
  await page.goto(`${BASE}${url}`, { waitUntil: "networkidle2", timeout: 60_000 });
  await settle(page, ms);
}

async function session(browser, email, { theme = "light", viewport = DESKTOP } = {}) {
  const ctx = await browser.createBrowserContext();
  const page = await ctx.newPage();
  await page.setViewport(viewport);
  await page.evaluateOnNewDocument((t) => {
    try {
      localStorage.setItem("theme", t);
    } catch {}
  }, theme);
  if (email) {
    await page.goto(`${BASE}/login`, { waitUntil: "networkidle2" });
    await page.type("#email", email);
    await page.type("#password", PASSWORD);
    await Promise.all([page.waitForNavigation({ waitUntil: "networkidle2" }), page.click("button[type=submit]")]);
  }
  return { ctx, page };
}

/** Click the first button (or link) whose visible text matches. */
async function clickText(page, text, selector = "button, a") {
  for (const el of await page.$$(selector)) {
    const t = ((await el.evaluate((e) => e.textContent)) ?? "").trim();
    if (typeof text === "string" ? t === text : text.test(t)) {
      await el.click();
      return true;
    }
  }
  return false;
}

async function main() {
  await rm(TOUR, { recursive: true, force: true });
  await mkdir(SHOTS, { recursive: true });
  await mkdir(TOUR, { recursive: true });
  const t = await token(ADMIN);
  const projects = await api(t, "GET", "/api/v1/projects");
  const retail = projects.find((p) => p.slug === "kestrel-retail");
  const ds = await api(t, "GET", `/api/v1/projects/${retail.id}/datasets`);
  const byName = (n) => ds.find((d) => d.name === n).id;
  const customers = byName("Customers");
  const incidents = await api(t, "GET", `/api/v1/projects/${retail.id}/incidents?status=active`);
  const P = `/projects/${retail.id}`;

  const browser = await puppeteer.launch({ executablePath: CHROME, headless: true, args: ["--no-sandbox"] });
  try {
    const { ctx, page } = await session(browser, ADMIN);
    await open(page, P, 2500);
    await shot(page, "01-dashboard");
    await open(page, `${P}/datasets`);
    await shot(page, "02-datasets");
    await open(page, `${P}/datasets/${customers}`, 2500);
    await shot(page, "03-dataset");
    await open(page, `${P}/datasets/${customers}?tab=profile`);
    // Open the email column's detail panel.
    if (await clickText(page, "email", "button, td, [role=button]")) await settle(page, 1200);
    await shot(page, "04-profile");
    await page.keyboard.press("Escape");
    await open(page, `${P}/datasets/${customers}?tab=checks`);
    await shot(page, "05-checks");
    // A real scan, followed live.
    await open(page, `${P}/datasets/${byName("Orders")}`);
    await clickText(page, "Scan now");
    await page.waitForFunction(() => /\/scans\/[0-9a-f-]{36}/.test(location.pathname), { timeout: 30_000 });
    await settle(page, 400);
    await shot(page, "06-scan-running", { curated: false }); // a tour frame only
    await page.waitForFunction(() => !document.body.textContent?.includes("Running") && !document.body.textContent?.includes("Queued"), { timeout: 120_000 }).catch(() => {});
    await settle(page, 1500);
    // The first failing result opens on its own, with its failing rows.
    await shot(page, "07-scan");
    if (incidents[0]) {
      await open(page, `${P}/incidents/${incidents[0].id}`);
      await shot(page, "08-incident");
    }
    await open(page, `${P}/alerts`);
    await shot(page, "09-alerts");
    await open(page, `${P}/connections`);
    await shot(page, "10-connections");
    await open(page, `${P}/datasets/new`);
    await shot(page, "11-new-dataset");
    await ctx.close();

    const dark = await session(browser, ADMIN, { theme: "dark" });
    await open(dark.page, P, 2500);
    await shot(dark.page, "12-dashboard-dark");
    await open(dark.page, `${P}/datasets/${customers}?tab=profile`);
    await shot(dark.page, "13-profile-dark", { tour: false });
    await dark.ctx.close();

    const phone = await session(browser, EDITOR, { viewport: PHONE });
    await open(phone.page, P, 2500);
    await shot(phone.page, "14-phone", { tour: false });
    await phone.ctx.close();
  } finally {
    await browser.close();
  }
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
