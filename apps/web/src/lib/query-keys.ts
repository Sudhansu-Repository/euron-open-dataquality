/**
 * Query keys in one place, so invalidation after a mutation names exactly what it
 * touched. Everything inside a project starts with ["p", projectId], so leaving or
 * deleting a project drops all of it at once.
 */
export const qk = {
  me: ["auth", "me"] as const,
  publicSettings: ["settings", "public"] as const,
  adminSettings: ["settings", "admin"] as const,
  system: ["system"] as const,
  users: ["users"] as const,
  audit: (action?: string) => ["audit", { action }] as const,
  projects: ["projects"] as const,
  project: (pid: string) => ["p", pid] as const,
  dashboard: (pid: string) => ["p", pid, "dashboard"] as const,
  members: (pid: string) => ["p", pid, "members"] as const,
  apiKeys: (pid: string) => ["p", pid, "api-keys"] as const,
  connections: (pid: string) => ["p", pid, "connections"] as const,
  tables: (pid: string, cid: string) => ["p", pid, "connections", cid, "tables"] as const,
  datasets: (pid: string) => ["p", pid, "datasets"] as const,
  dataset: (pid: string, did: string) => ["p", pid, "datasets", did] as const,
  profile: (pid: string, did: string) => ["p", pid, "datasets", did, "profile"] as const,
  suggestions: (pid: string, did: string) => ["p", pid, "datasets", did, "suggestions"] as const,
  preview: (pid: string, did: string) => ["p", pid, "datasets", did, "preview"] as const,
  files: (pid: string, did: string) => ["p", pid, "datasets", did, "files"] as const,
  metrics: (pid: string, did: string, metric: string, key?: string) => ["p", pid, "datasets", did, "metrics", metric, key ?? ""] as const,
  checks: (pid: string, did: string) => ["p", pid, "datasets", did, "checks"] as const,
  scans: (pid: string, filters: object) => ["p", pid, "scans", filters] as const,
  scansAll: (pid: string) => ["p", pid, "scans"] as const,
  scan: (pid: string, sid: string) => ["p", pid, "scan", sid] as const,
  anomalies: (pid: string, did?: string) => ["p", pid, "anomalies", did ?? ""] as const,
  channels: (pid: string) => ["p", pid, "channels"] as const,
  rules: (pid: string) => ["p", pid, "rules"] as const,
  incidents: (pid: string, filters: object) => ["p", pid, "incidents", filters] as const,
  incidentsAll: (pid: string) => ["p", pid, "incidents"] as const,
  incident: (pid: string, iid: string) => ["p", pid, "incident", iid] as const,
};

/** staleTime per kind of data, chosen deliberately (docs/architecture/HLD.md, caching). */
export const STALE = {
  live: 3_000,
  list: 15_000,
  config: 30_000,
  static: 5 * 60_000,
} as const;
