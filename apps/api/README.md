# dataquality (API, scan worker and CLIs)

The Python package behind Euron Open DataQuality: the FastAPI API, the scan worker (which also
runs the scheduler, lease reaper, alert delivery and retention), the check engine, and two
command-line tools. One package, one image; the command picks the role.

## Layout

```
src/dataquality/
  core/          settings, database, KV store (Redis or memory), sealing, storage, mail, middleware, errors
  engine/        the check engine: specs, compiler, per-dialect SQL, runner, profiler, SQL guard,
                 scoring, anomaly detection, suggestions
  sources/       opening sources read-only: databases, DuckDB for files, REST
  scans/         queue, executor, completion, history, reports, periodic tasks, scan API
  alerts/        channels, rules, incidents, notification outbox and delivery
  auth/ users/ org/ projects/ connections/ datasets/ checks/ dashboard/ audit/ ai/ system/
  migrations/    Alembic
  client/cli.py  the dq command for CI
  cli.py         the dataquality command
src/mockai/      test fixture: OpenAI-compatible stand-in, webhook sink, demo REST feed
tests/           unit/, integration/, bench/, golden.py (planted defects), sources.py (every backend)
```

Architecture: [docs/architecture/](../../docs/architecture/). Start with
[HLD.md](../../docs/architecture/HLD.md) and [engine.md](../../docs/architecture/engine.md).

## Commands

```bash
uv sync                                   # dependencies (Python 3.12)

uv run dataquality serve                  # the API on $PORT (8080)
uv run dataquality worker                 # the scan worker and periodic tasks
uv run dataquality migrate                # apply migrations
uv run dataquality revision -m "..."      # autogenerate a migration from the models
uv run dataquality create-admin --email you@example.com
uv run dataquality seed-demo              # the demo (expects the Compose stack)
uv run dataquality openapi                # print the OpenAPI document as YAML

uv run dq scan <dataset> --fail-on error  # the CI client, with DQ_URL, DQ_API_KEY, DQ_PROJECT
```

Configuration is environment only: [docs/guides/configuration.md](../../docs/guides/configuration.md).

## Tests

```bash
uv run pytest tests/unit                             # no database, no network
uv run pytest tests/unit tests/integration           # needs Postgres, Redis and the source databases
uv run python -m tests.bench.bench_million           # 1,000,000 row benchmark (make up first)
```

From the repository root, `make test`, `make test-integration` (starts what it needs),
`make test-matrix` and `make bench` wrap these. Details:
[docs/guides/testing.md](../../docs/guides/testing.md).

## Licence

MIT, see [LICENSE](../../LICENSE).
