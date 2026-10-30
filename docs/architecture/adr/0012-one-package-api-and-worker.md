# ADR-0012: One package and one image for the API and the scan worker

- **Status:** Accepted
- **Date:** 2026-10-30

## Context

The API and the worker share the domain models, the check engine, the sources, sealing and
storage. The worker also has periodic duties (scheduling, reaping leases, delivering
notifications, retention). These could be separate services: an API, a scan worker, a
scheduler, a notifier.

## Decision

One Python package (`dataquality`) and one image. The command picks the role:
`dataquality serve` (API), `dataquality worker` (scans plus every periodic task),
`dataquality migrate`, `create-admin`, `seed-demo`. The scheduler, reaper, notifier and
retention run inside every worker replica; each claims its rows with `FOR UPDATE SKIP
LOCKED` or conditional updates, so any number of replicas cooperate without a leader. The
`dq` CLI for CI ships in the same package.

## Consequences

**Good**
- One build, one version, one image to scan and deploy; the API and the worker can never
  disagree about a check's meaning.
- No singleton scheduler to keep alive: scaling the worker scales everything that runs in
  the background, and losing one replica loses nothing.

**Bad / caveats**
- The API image carries the source drivers and DuckDB it only uses for connection tests and
  previews.
- Periodic tasks share the worker's event loop with scan heartbeats; they are short queries,
  and scans run their source work in threads.

## Alternatives considered

- **Separate scheduler and notifier services**: more moving parts, and a singleton scheduler
  needs leader election or it duplicates work.
- **Separate images per role**: smaller images, but a second build and the risk of version
  skew between API and worker.
