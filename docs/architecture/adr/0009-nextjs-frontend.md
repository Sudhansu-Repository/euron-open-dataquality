# ADR-0009: Next.js for the web app

- **Status:** Accepted
- **Date:** 2026-10-30

## Context

The brief suggested a plain React single-page app. The Euron open-source programme fixes the
stack for every project: a Python and FastAPI backend and a Next.js 15 frontend (App Router,
React 19, TypeScript strict, Tailwind and shadcn/ui, TanStack Query), so contributors move
between projects without relearning the tooling, and the programme's rules take precedence
over a brief.

## Decision

Next.js 15 with the App Router, built as a standalone server (`output: "standalone"`). The
web server proxies `/api/*`, `/healthz`, `/readyz`, `/docs` and `/openapi.json` to the API,
so the browser talks to one origin and the session stays in a first-party HttpOnly cookie
with no CORS. Pages are client components fed by TanStack Query hooks per feature; the API
client is generated from the OpenAPI document. `middleware.ts` sets the
Content-Security-Policy and redirects signed-out visitors to `/login` before a protected page
renders.

## Consequences

**Good**
- Same-origin deployment without extra configuration, with security headers and a CSP from
  one place.
- The same structure, conventions and QA scripts as the other programme projects.
- Room for server rendering where it pays off later.

**Bad / caveats**
- A Node server to run (one more container than static files behind a CDN).
- Most of the app is client-rendered dashboards, so little of Next's server rendering is used
  today.

## Alternatives considered

- **Plain React with Vite, served as static files**: smaller, but then the API must handle
  CORS and cookies across origins, or an extra proxy is needed, and it would diverge from the
  programme's stack.
