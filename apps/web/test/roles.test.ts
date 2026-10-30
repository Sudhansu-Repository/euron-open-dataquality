import { describe, expect, it } from "vitest";

import { can, isAdmin, PROJECT_ROLE_DESCRIPTION, PROJECT_ROLES, roleDescription, roleLabel } from "@/lib/roles";

describe("can", () => {
  it("ranks viewer below editor below owner", () => {
    expect(can("owner", "owner")).toBe(true);
    expect(can("owner", "editor")).toBe(true);
    expect(can("owner", "viewer")).toBe(true);
    expect(can("editor", "editor")).toBe(true);
    expect(can("editor", "owner")).toBe(false);
    expect(can("viewer", "viewer")).toBe(true);
    expect(can("viewer", "editor")).toBe(false);
  });
  it("denies unknown or missing roles", () => {
    expect(can(undefined, "viewer")).toBe(false);
    expect(can(null, "viewer")).toBe(false);
    expect(can("admin", "viewer")).toBe(false);
    expect(can("", "viewer")).toBe(false);
  });
});

describe("instance roles", () => {
  it("labels and describes admin and user", () => {
    expect(roleLabel("admin")).toBe("Admin");
    expect(roleLabel("user")).toBe("User");
    expect(roleLabel("student")).toBe("Unknown");
    expect(roleDescription("admin")).toMatch(/every project/);
    expect(roleDescription("nobody")).toBe("");
    expect(isAdmin("admin")).toBe(true);
    expect(isAdmin("user")).toBe(false);
  });
  it("describes every project role", () => {
    for (const r of PROJECT_ROLES) expect(PROJECT_ROLE_DESCRIPTION[r].length).toBeGreaterThan(10);
  });
});
