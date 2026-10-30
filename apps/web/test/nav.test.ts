import { describe, expect, it } from "vitest";

import { activeHref, hrefOf, NAV, projectIdFrom, visibleTo, type NavItem } from "@/lib/nav";

const PID = "5bff5132-b0f6-4c20-93cb-7dce7f4e9629";
const items = NAV.flatMap((g) => g.items);
const item = (label: string) => items.find((i) => i.label === label) as NavItem;

describe("projectIdFrom", () => {
  it("reads the project id from project paths", () => {
    expect(projectIdFrom(`/projects/${PID}`)).toBe(PID);
    expect(projectIdFrom(`/projects/${PID}/datasets/abc`)).toBe(PID);
  });
  it("returns null outside a project or for a malformed id", () => {
    expect(projectIdFrom("/projects")).toBeNull();
    expect(projectIdFrom("/admin/users")).toBeNull();
    expect(projectIdFrom("/projects/not-a-uuid/datasets")).toBeNull();
    expect(projectIdFrom(`/projects/${PID}extra`)).toBeNull();
  });
});

describe("hrefOf", () => {
  it("prefixes project items with the current project", () => {
    expect(hrefOf(item("Dashboard"), PID)).toBe(`/projects/${PID}`);
    expect(hrefOf(item("Datasets"), PID)).toBe(`/projects/${PID}/datasets`);
  });
  it("has no href for a project item outside a project", () => {
    expect(hrefOf(item("Datasets"), null)).toBeNull();
  });
  it("keeps admin items absolute", () => {
    expect(hrefOf(item("Users"), null)).toBe("/admin/users");
    expect(hrefOf(item("Users"), PID)).toBe("/admin/users");
  });
});

describe("visibleTo", () => {
  it("shows admin items to admins only", () => {
    expect(visibleTo(item("System"), "admin", null)).toBe(true);
    expect(visibleTo(item("System"), "user", PID)).toBe(false);
    expect(visibleTo(item("System"), undefined, PID)).toBe(false);
  });
  it("shows project items to anyone signed in, inside a project", () => {
    expect(visibleTo(item("Incidents"), "user", PID)).toBe(true);
    expect(visibleTo(item("Incidents"), "admin", PID)).toBe(true);
    expect(visibleTo(item("Incidents"), "user", null)).toBe(false);
    expect(visibleTo(item("Incidents"), null, PID)).toBe(false);
  });
});

describe("activeHref", () => {
  it("picks the longest matching prefix", () => {
    expect(activeHref(`/projects/${PID}/datasets/x`, PID)).toBe(`/projects/${PID}/datasets`);
    expect(activeHref(`/projects/${PID}/incidents/abc`, PID)).toBe(`/projects/${PID}/incidents`);
    expect(activeHref(`/projects/${PID}`, PID)).toBe(`/projects/${PID}`);
  });
  it("ignores a trailing slash", () => {
    expect(activeHref(`/projects/${PID}/alerts/`, PID)).toBe(`/projects/${PID}/alerts`);
  });
  it("matches admin pages and nothing for unknown pages", () => {
    expect(activeHref("/admin/audit", null)).toBe("/admin/audit");
    expect(activeHref("/projects", null)).toBeNull();
  });
});
