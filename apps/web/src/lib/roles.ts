import type { ProjectRole, Role } from "./api/types";

export const ROLES: readonly Role[] = ["admin", "user"] as const;

const ROLE_LABEL: Record<Role, string> = { admin: "Admin", user: "User" };
const ROLE_DESCRIPTION: Record<Role, string> = {
  admin: "Sees and manages every project, plus users, instance settings and the audit log.",
  user: "Works in the projects they are a member of, with the role each project gives them.",
};

export function isRole(value: unknown): value is Role {
  return typeof value === "string" && (ROLES as readonly string[]).includes(value);
}

export function roleLabel(role: string | null | undefined): string {
  return isRole(role) ? ROLE_LABEL[role] : "Unknown";
}

export function roleDescription(role: string | null | undefined): string {
  return isRole(role) ? ROLE_DESCRIPTION[role] : "";
}

export function isAdmin(role: string | null | undefined): boolean {
  return role === "admin";
}

export const PROJECT_ROLES: readonly ProjectRole[] = ["viewer", "editor", "owner"] as const;
const RANK: Record<ProjectRole, number> = { viewer: 0, editor: 1, owner: 2 };

export const PROJECT_ROLE_DESCRIPTION: Record<ProjectRole, string> = {
  viewer: "Sees datasets, results, incidents and reports.",
  editor: "Also adds connections, datasets and checks, runs scans and handles incidents.",
  owner: "Also manages members, API keys and the project's settings.",
};

/** Whether a project role is at least ``needed``. */
export function can(role: string | null | undefined, needed: ProjectRole): boolean {
  const have = role && role in RANK ? RANK[role as ProjectRole] : -1;
  return have >= RANK[needed];
}
