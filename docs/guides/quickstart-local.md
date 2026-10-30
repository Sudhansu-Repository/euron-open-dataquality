# Quickstart (local)

Everything runs in Docker on one machine. No AWS account, no API keys.

## Prerequisites

- Docker with Compose v2 (Docker Desktop or Docker Engine on Linux)
- `make`, `bash`, `openssl`
- For the tests outside containers: Python 3.12 with [uv](https://docs.astral.sh/uv/), and
  Node 22 with pnpm

## Start

```bash
git clone https://github.com/euron-sde-team/euron-open-dataquality.git
cd euron-open-dataquality
make up      # Postgres, Redis, Mailpit, Floci (provisioned by Terraform), demo sources, api, worker, web
make demo    # users, two projects, sources, datasets of every kind, checks, alerts, 30 days of scans
```

`make up` generates `deploy/compose/.env` with random local secrets the first time
(`make env`, never overwrites), builds the images, applies the `local-floci` Terraform to the
emulator, runs the migrations and waits until everything is healthy. It also starts two demo
source databases the platform will check: a "warehouse" PostgreSQL and a "shop" MySQL.

`make demo` builds the demo through the real API and the real worker, then replays 30 days of
loads and scans (two or three minutes). It prints the sign-in details. Open
http://localhost:4910.

| Who | Email | Sees |
| --- | --- | --- |
| Instance admin | `admin@dataquality.demo` (Priya Raman) | Everything, plus users, system, audit and instance settings |
| Editor and owner | `maya@dataquality.demo` (Maya Fernandes) | Editor in Kestrel Retail, owner of People Ops |
| Viewer | `arjun@dataquality.demo` (Arjun Mehta) | Kestrel Retail, read only |

All demo accounts share the password `DQ_DEMO_PASSWORD` from `deploy/compose/.env` (`make
demo` prints it). Alert emails land in Mailpit at http://localhost:4925. The API's
interactive docs are at http://localhost:4930/docs.

To also run the optional SQL Server demo source (an amd64 image, emulated on Apple silicon):
`make up MSSQL=1`.

## Five minutes

1. Sign in as the admin and open **Kestrel Retail**. The dashboard shows the project score,
   its trend over 30 days, the dimension breakdown and the most recent failing checks.
2. Open **Datasets**, **Orders**, **Checks**: every check with its latest result. Open a
   failing one, such as **Order belongs to a customer**, to see the failing rows.
3. Press **Scan now**. The scan is queued, claimed by the worker and finished in seconds; the
   scan page updates live.
4. Add your own data: **Datasets**, **Add a dataset**, **Upload a file**, and drop a CSV.
   **Add and scan** uploads it, profiles it and opens it. The **Profile** tab shows what each
   column holds; **Checks** lists **Suggested** checks with the reason for each. Accept
   them, then **Scan now**.
5. Open **Incidents**: the problems the demo's alert rules opened, with the emails and
   webhook calls they sent. Mailpit has the emails.

## Connect your own database

**Connections**, **Add a connection** (PostgreSQL, MySQL or SQL Server, or upload a SQLite
file), press **Test connection**, then **Add a dataset**, **Database table**. Use a
read-only login: the platform never writes, and a read-only login makes the database enforce
it too
([security.md](../architecture/security.md#read-only-by-construction)). From inside Docker
Desktop, a database on your own machine is at `host.docker.internal`, not `localhost`.

## Stop

```bash
make down    # stops the stack and deletes its data (volumes included)
```

## Next

- [Walkthrough](walkthrough.md): a tour of every screen with the demo data
- [Checks as code](checks-as-code.md) and [API integration](api-integration.md)
- [Configuration](configuration.md)
- [Testing](testing.md)
