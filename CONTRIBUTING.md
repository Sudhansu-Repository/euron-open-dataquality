# Contributing

Thanks for helping improve Euron Open DataQuality. This guide covers the workflow, the bar a
change has to clear, and the conventions the codebase follows.

## Ground rules

- **Open an issue first** for anything larger than a bug fix or a docs tweak, so we can
  agree on the approach before you invest time.
- **One concern per pull request.** A refactor and a feature are two PRs.
- **Security issues go through private reporting**, never a public issue. That includes any
  way to write to a source database or to read credentials. See [SECURITY.md](SECURITY.md).
- By contributing you agree your work is released under the [MIT License](LICENSE).

## Development setup

Requirements: Docker, Python 3.12 with [uv](https://docs.astral.sh/uv/), Node 22 and
pnpm (`corepack enable`).

```bash
make up          # Postgres, Redis, Mailpit, Floci (provisioned by Terraform), demo sources, api, worker, web
make demo        # users, two projects, datasets of every kind, checks, alerts, 30 days of scans
make test        # unit tests (API and web)
```

[docs/guides/quickstart-local.md](docs/guides/quickstart-local.md) walks through the local
stack, and [docs/architecture/LLD.md](docs/architecture/LLD.md) maps the code.

## Before you open a pull request

Each of these must pass:

```bash
make lint typecheck test
make test-integration                  # the API against real Postgres, Redis and source databases
make test-integration MSSQL=1          # when you touched the engine, a dialect or sources/sql.py
make test-matrix                       # when you touched sealing, storage or anything AWS
make e2e                               # when you touched a web flow or infrastructure
make tf-validate tf-lint tf-security   # when you touched infra/terraform
make tf-aws-on-floci                   # same: apply and destroy aws-dev against Floci
make openapi                           # when you changed an endpoint or a schema
make sanitize                          # no credentials, account ids, resource ids or dashes
```

## Conventions

**Package by domain.** `apps/api/src/dataquality/<domain>/` owns its `router.py` (HTTP only),
`schemas.py` (the public contract), `service.py` (rules) and `models.py`. Dependencies point
inward: router, service, data. A domain calls another domain's service, never its tables.
`engine/` and `sources/` know nothing about HTTP or the platform's database.

**Checks mean the same thing everywhere.** A check type is a parameter model in
`engine/spec.py`, a branch in `engine/compiler.py`, and, if its SQL differs per database, a
construct in `engine/dialects.py` with one `@compiles` per dialect. A new check type or a
change to one needs: its semantics in
[docs/architecture/checks.md](docs/architecture/checks.md) (what is evaluated, what fails,
NULL and blank handling), planted defects in `apps/api/tests/golden.py` with their expected
counts, and a green parity test on every backend, SQL Server included (`MSSQL=1`). Results
are exact: never sample or estimate in a check.

**Never write to a source.** The engine generates `SELECT` only. User SQL goes through
`engine/sqlguard.py`. Source sessions are read-only where the database allows it and always
rolled back. A change that weakens any of these will not be merged; a change to the guard
needs tests that prove the new refusals and acceptances.

**Work stays in the database.** Do not fetch rows into Python to evaluate them; add a SQL
expression instead. The only exception is the streamed SQL Server regex path.

**Secrets are sealed and never returned.** Anything that grants access (passwords, tokens,
URLs with secrets in them) goes through the sealer with a context bound to its row, and the
API shows at most a hint.

**One transaction per scan outcome.** Writes about a scan go through `scans/complete.py` and
are guarded by `(id, attempt, worker)`. Periodic work registers with `core/tasks.py` and must
be safe with several worker replicas (`FOR UPDATE SKIP LOCKED` or conditional updates).

**Caches are documented.** A new cache layer goes in the caching table of
[docs/architecture/HLD.md](docs/architecture/HLD.md) with its key, TTL and invalidation, and
its invalidation is tested.

**Configuration is validated.** A new setting goes in `core/config.py`, is documented in
[docs/guides/configuration.md](docs/guides/configuration.md) in the same PR, and
security-relevant ones are enforced by `guard()` at boot.

**Database changes are new migrations.** Change the models, then autogenerate a revision
with `uv run dataquality revision -m "what changed"` against a local database and review it.
Never edit an applied one. Indexes for every new filter the API exposes belong in the same
revision.

**The web app uses the generated client.** After an API change, `make openapi` and
`pnpm gen:api` in `apps/web`; never hand-write API types. Server state goes through TanStack
Query hooks in `features/<domain>/api.ts` with a deliberate `staleTime`.

**Comments explain why.** The code says what it does. Comments are for the constraint, the
incident, or the trade-off that made it this way.

**Style.** ruff and mypy `--strict` for Python; ESLint and TypeScript strict for the web. No
em dashes or en dashes anywhere (the sanitization check enforces it).

## Adding a source database

Add the driver to `apps/api/pyproject.toml`; teach `sources/sql.py` to open it read-only with
a statement timeout; add its dialect to `engine/dialects.py` (regex, length, shape, exact
text) and `engine/sqlguard.py` (its sqlglot dialect and dangerous functions); add it to the
connection kinds and the migration's check constraint; load the golden dataset into it in
`apps/api/tests/sources.py` and add a parity test. If it cannot express a construct, use the
streamed Python path and say so in [docs/architecture/engine.md](docs/architecture/engine.md).

## Commit messages

Imperative mood with an optional scope: `engine: count blank strings as missing for type
checks`, `web: show the dominant shape on format results`. Explain the why in the body when it
is not obvious.

## Architecture decisions

Significant decisions are recorded in [docs/architecture/adr/](docs/architecture/adr/). If
your change reverses or extends one, add a new ADR rather than editing the old one.
