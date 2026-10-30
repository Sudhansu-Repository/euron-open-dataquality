import {
  ActivityIcon,
  BellRingIcon,
  CableIcon,
  DatabaseIcon,
  GaugeIcon,
  HistoryIcon,
  ScrollTextIcon,
  SettingsIcon,
  SirenIcon,
  SlidersHorizontalIcon,
  UsersIcon,
  type LucideIcon,
} from "lucide-react";

export type Audience = "project" | "admin";

export interface NavItem {
  /** A path; inside a project, relative to /projects/<id>. */
  href: string;
  label: string;
  icon: LucideIcon;
  audience: Audience;
}

export interface NavGroup {
  label: string;
  items: NavItem[];
}

export const NAV: NavGroup[] = [
  {
    label: "Monitor",
    items: [
      { href: "", label: "Dashboard", icon: GaugeIcon, audience: "project" },
      { href: "/datasets", label: "Datasets", icon: DatabaseIcon, audience: "project" },
      { href: "/scans", label: "Scans", icon: HistoryIcon, audience: "project" },
      { href: "/incidents", label: "Incidents", icon: SirenIcon, audience: "project" },
    ],
  },
  {
    label: "Configure",
    items: [
      { href: "/connections", label: "Connections", icon: CableIcon, audience: "project" },
      { href: "/alerts", label: "Alerts", icon: BellRingIcon, audience: "project" },
      { href: "/settings", label: "Project settings", icon: SlidersHorizontalIcon, audience: "project" },
    ],
  },
  {
    label: "Admin",
    items: [
      { href: "/admin/users", label: "Users", icon: UsersIcon, audience: "admin" },
      { href: "/admin/system", label: "System", icon: ActivityIcon, audience: "admin" },
      { href: "/admin/audit", label: "Audit log", icon: ScrollTextIcon, audience: "admin" },
      { href: "/admin/settings", label: "Instance settings", icon: SettingsIcon, audience: "admin" },
    ],
  },
];

/** The project id in a path like /projects/<id>/datasets, or null. */
export function projectIdFrom(pathname: string): string | null {
  const m = /^\/projects\/([0-9a-f-]{36})(?:\/|$)/.exec(pathname);
  return m?.[1] ?? null;
}

/** The real href of an item: project items are prefixed with the current project. */
export function hrefOf(item: NavItem, projectId: string | null): string | null {
  if (item.audience === "admin") return item.href;
  return projectId ? `/projects/${projectId}${item.href}` : null;
}

/** Whether someone with this instance role sees an item, given the current project. */
export function visibleTo(item: NavItem, role: string | null | undefined, projectId: string | null): boolean {
  if (item.audience === "admin") return role === "admin";
  return !!role && !!projectId;
}

/** The nav item a path belongs to: the longest matching prefix. */
export function activeHref(pathname: string, projectId: string | null): string | null {
  const path = pathname.replace(/\/+$/, "") || "/";
  const hrefs = NAV.flatMap((g) => g.items)
    .map((i) => hrefOf(i, projectId))
    .filter((h): h is string => !!h);
  return hrefs
    .filter((h) => path === h || path.startsWith(`${h}/`))
    .sort((a, b) => b.length - a.length)[0] ?? null;
}
