/**
 * Browser QA (make qa): signs in through the real form as each role, visits every page in
 * light and dark at desktop and phone width, saves screenshots, and fails on console
 * errors, failed or 4xx/5xx requests, broken images, error states, empty pages with no
 * explanation, and horizontal overflow.
 *
 *   make qa
 *   QA_BASE=http://localhost:4910 QA_OUT=./output node qa.mjs
 *   QA_PAGES=/projects QA_ROLES=admin QA_THEMES=dark QA_SIZES=desktop node qa.mjs
 *
 * Needs the seeded stack (make up && make demo). Uses Puppeteer's bundled Chromium; set
 * CHROME_PATH to use a local browser instead.
 */
import { mkdir } from "node:fs/promises";
import { existsSync } from "node:fs";
import path from "node:path";
import puppeteer from "puppeteer";

const BASE = process.env.QA_BASE ?? "http://localhost:4910";
const OUT = process.env.QA_OUT ?? path.resolve("output");
const PASSWORD = process.env.QA_PASSWORD ?? process.env.DQ_DEMO_PASSWORD ?? "";
const CHROME = process.env.CHROME_PATH && existsSync(process.env.CHROME_PATH) ? process.env.CHROME_PATH : undefined;

const ADMIN = "admin@dataquality.demo";
const EDITOR = "maya@dataquality.demo";
const VIEWER = "arjun@dataquality.demo";

// Pages per role. Placeholders are resolved from the seeded data once.
const P = "/projects/:retail";
const ROLE_PAGES = {
  anonymous: ["/login"],
  admin: [
    "/projects",
    P,
    `${P}/datasets`,
    `${P}/datasets/new`,
    `${P}/datasets/:customers`,
    `${P}/datasets/:customers?tab=profile`,
    `${P}/datasets/:customers?tab=checks`,
    `${P}/datasets/:customers?tab=scans`,
    `${P}/datasets/:customers?tab=settings`,
    `${P}/datasets/:orders`,
    `${P}/datasets/:signups`,
    `${P}/datasets/:leads`,
    `${P}/datasets/:events?tab=profile`,
    `${P}/scans`,
    `${P}/scans/:scan`,
    `${P}/incidents`,
    `${P}/incidents/:incident`,
    `${P}/connections`,
    `${P}/alerts`,
    `${P}/settings`,
    `${P}/settings?tab=members`,
    `${P}/settings?tab=api-keys`,
    "/projects/:people",
    "/projects/:people/datasets/:employees?tab=checks",
    "/admin/users",
    "/admin/system",
    "/admin/audit",
    "/admin/settings",
  ],
  editor: [P, `${P}/datasets/:customers?tab=checks`, `${P}/incidents`, "/projects/:people"],
  viewer: [P, `${P}/datasets`, `${P}/datasets/:customers?tab=checks`, `${P}/incidents/:incident`, `${P}/settings`],
};
const ONLY = process.env.QA_PAGES ? new Set(process.env.QA_PAGES.split(",")) : null;
const ROLES = (process.env.QA_ROLES ?? "anonymous,admin,editor,viewer").split(",");
const THEMES = (process.env.QA_THEMES ?? "light,dark").split(",");
const SIZES = {
  desktop: { width: 1440, height: 900 },
  phone: { width: 390, height: 844, isMobile: true, hasTouch: true, deviceScaleFactor: 2 },
};
const SIZE_KEYS = (process.env.QA_SIZES ?? "desktop,phone").split(",");
const FULL = process.env.QA_FULL !== "0";

function slug(p) {
  return p.replace(/^\//, "").replace(/[/:?=]/g, "-") || "home";
}

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

/** Ids of seeded records for the parameterised pages. */
async function resolveIds() {
  const t = await token(ADMIN);
  const projects = await api(t, "GET", "/api/v1/projects");
  const retail = projects.find((p) => p.slug === "kestrel-retail");
  const people = projects.find((p) => p.slug === "people-ops");
  if (!retail || !people) throw new Error("the demo projects are missing: run make demo");
  const ds = await api(t, "GET", `/api/v1/projects/${retail.id}/datasets`);
  const byName = (n) => ds.find((d) => d.name === n)?.id ?? "missing";
  const hr = await api(t, "GET", `/api/v1/projects/${people.id}/datasets`);
  const incidents = await api(t, "GET", `/api/v1/projects/${retail.id}/incidents?status=active`);
  const customers = byName("Customers");
  const scans = await api(t, "GET", `/api/v1/projects/${retail.id}/scans?dataset_id=${customers}&limit=1`);
  return {
    retail: retail.id,
    people: people.id,
    customers,
    orders: byName("Orders"),
    signups: byName("Signup events"),
    leads: byName("Partner leads"),
    events: byName("Web events"),
    employees: hr[0]?.id ?? "missing",
    scan: scans.items[0]?.id ?? "missing",
    incident: incidents[0]?.id ?? "missing",
  };
}

async function signInForm(page, email) {
  await page.goto(`${BASE}/login`, { waitUntil: "networkidle2" });
  await page.type("#email", email);
  await page.type("#password", PASSWORD);
  await Promise.all([page.waitForNavigation({ waitUntil: "networkidle2" }), page.click("button[type=submit]")]);
}

function watch(page, sink) {
  page.on("console", (m) => {
    if (m.type() === "error") sink.push(m.text());
  });
  page.on("pageerror", (e) => sink.push(`pageerror: ${e.message}`));
  page.on("requestfailed", (r) => {
    const err = r.failure()?.errorText ?? "";
    if (!err.includes("ERR_ABORTED")) sink.push(`requestfailed ${r.url()} ${err}`);
  });
  page.on("response", (r) => {
    if (r.status() >= 400) sink.push(`HTTP ${r.status()} ${r.url()}`);
  });
}

async function inspect(page) {
  return page.evaluate(() => {
    const overflow = document.documentElement.scrollWidth - window.innerWidth;
    const broken = [...document.images].filter((img) => img.complete && img.naturalWidth === 0).map((img) => img.src);
    const errorStates = [...document.querySelectorAll("[data-qa='error-state']")].map((el) => el.textContent?.slice(0, 80) ?? "");
    const main = document.querySelector("main") ?? document.body;
    const text = (main.textContent ?? "").replace(/\s+/g, " ").trim();
    return { overflow, broken, errorStates, empty: text.length < 40 };
  });
}

async function main() {
  await mkdir(OUT, { recursive: true });
  const ids = await resolveIds();
  const browser = await puppeteer.launch({ executablePath: CHROME, headless: true, args: ["--no-sandbox"] });
  const problems = [];
  let visited = 0;

  for (const role of ROLES) {
    const pages = ROLE_PAGES[role].filter((p) => !ONLY || ONLY.has(p));
    if (!pages.length) continue;
    for (const theme of THEMES) {
      for (const sizeKey of SIZE_KEYS) {
        const ctx = await browser.createBrowserContext();
        const page = await ctx.newPage();
        await page.setViewport(SIZES[sizeKey]);
        await page.evaluateOnNewDocument((t) => {
          try {
            localStorage.setItem("theme", t);
          } catch {}
        }, theme);
        const errors = [];
        watch(page, errors);
        const who = { admin: ADMIN, editor: EDITOR, viewer: VIEWER }[role];
        if (who) await signInForm(page, who);
        for (const p of pages) {
          const url = p.replace(/:(\w+)/g, (_, k) => ids[k] ?? k);
          errors.length = 0;
          await page.goto(`${BASE}${url}`, { waitUntil: "networkidle2", timeout: 60_000 });
          await new Promise((r) => setTimeout(r, 1200));
          const found = await inspect(page);
          const file = path.join(OUT, `${role}-${sizeKey}-${theme}-${slug(p)}.png`);
          await page.screenshot({ path: file, fullPage: FULL });
          const issues = [...errors];
          if (found.overflow > 1) issues.push(`horizontal overflow ${found.overflow}px`);
          for (const src of found.broken) issues.push(`broken image ${src}`);
          for (const text of found.errorStates) issues.push(`error state: ${text}`);
          if (found.empty) issues.push("page is empty with no explanation");
          if (issues.length) problems.push({ role, page: p, theme, size: sizeKey, issues });
          visited += 1;
          console.log(`${issues.length ? "WARN" : "ok  "} ${role} ${sizeKey} ${theme} ${p}${issues.length ? `: ${issues.join(" | ")}` : ""}`);
        }
        await ctx.close();
      }
    }
  }
  await browser.close();
  console.log(`\n${visited} page views, ${problems.length} with problems. Screenshots in ${OUT}`);
  if (problems.length) process.exitCode = 1;
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
