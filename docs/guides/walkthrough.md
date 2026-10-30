# Walkthrough

A tour of the product with the demo data. Start the stack and seed it first
([quickstart-local.md](quickstart-local.md)): `make up && make demo`, then open
http://localhost:4910. Every number you see was computed by the engine against real
databases and files; the seed only shifts timestamps so 30 days of scans fit in a few
minutes.

## The demo

| Account | Role |
| --- | --- |
| `admin@dataquality.demo` (Priya Raman) | Instance admin: every project, users, system, audit, instance settings |
| `maya@dataquality.demo` (Maya Fernandes) | Editor in Kestrel Retail, owner of People Ops |
| `arjun@dataquality.demo` (Arjun Mehta) | Viewer in Kestrel Retail |

The password is `DQ_DEMO_PASSWORD` from `deploy/compose/.env`.

**Kestrel Retail** ("Customers, orders and stock for the Kestrel online store") has two
connections, each through a read-only `dq_reader` login:

| Dataset | Kind | Source | Notes |
| --- | --- | --- | --- |
| Customers | table | Warehouse (PostgreSQL) | Scanned daily at 06:00 Asia/Kolkata; `phone` masked; tags `core`, `pii` |
| Orders | table | Warehouse | Daily; referential check to Customers |
| Products | table | Warehouse | |
| VIP customers | query | Warehouse | `SELECT ... FROM customers WHERE segment = 'vip'` |
| Inventory | table | Shop (MySQL) | Daily; referential check to Suppliers |
| Suppliers | table | Shop | A GSTIN regex check |
| Partner leads | REST | the mock partner API | Records under `data.items`, with a sealed Authorization header |
| Signup events | push | batches pushed through the API | |
| Web events | file | an uploaded Parquet file | |

**People Ops** ("HR master data loaded from the payroll export") has one dataset, Employees,
from an uploaded Excel workbook, with PAN format, manager and salary checks.

Each dataset carries the suggested checks the seed accepted plus hand-written ones (PIN code
is 6 digits, phone is a +91 mobile, shipped after ordered, order belongs to a customer, total
is not negative, orders are fresh, stock never negative, synced in the last day, supplier
exists, GSTIN format, and more). Over the 30 replayed days, missing customer emails fade out
as the signup form is fixed, one nightly orders load breaks and delivers about a tenth of
the rows (repaired the next day), and a later load brings a burst of blank emails.

## Dashboard

Sign in as the admin and open **Kestrel Retail**. The dashboard is one API call
(`GET /api/v1/projects/{p}/dashboard`), cached for 30 s and recomputed after every scan:

- the **project score** (the mean of each dataset's latest score) and its change against a
  week ago;
- datasets scanned, records scanned, failing checks, duplicate records, open incidents and
  scans in the last 24 hours;
- the **dimension breakdown**: completeness, validity, consistency, uniqueness, freshness and
  volume;
- the **30 day trend** from the daily rollup, where the broken orders load is visible as a
  dip;
- the most recent failing checks and the datasets with the lowest scores.

How the numbers are computed: [scoring.md](../architecture/scoring.md).

## Datasets

**Datasets** lists every dataset with its kind, source, latest score, status, rows and failing
checks. **Add a dataset** offers the five kinds: **Database table**, **SQL query**, **Upload a
file**, **REST API** and **Push from your app**, with an optional daily scan time.

Open **Customers**:

- **Overview**: the latest scan, score per dimension, history charts of the score and row
  count, and the anomalies and schema changes found for this dataset.
- **Profile**: per column the inferred type, missing and blank values, distinct values,
  minimum and maximum, mean, standard deviation, quantiles, histogram, most common values and
  value shapes, and how many values look like emails, phones or dates. `phone` is masked: its
  values show as `[masked]`.
- **Checks**: every check with its latest result. **Suggested** lists checks derived from the
  profile, each with its reason ("Looks like a key and every value is distinct", "97% of values
  are valid email"); accept them one by one or all at once. **Add check** opens a form per
  check type. **Download YAML** exports the checks as code.
- **Scans**: every scan of the dataset with status, score and duration.
- **Settings**: description, filter, masked columns, tags, profiling, scan timeout, schedule.

Press **Scan now**: the scan is queued, a worker claims it, and the page updates within
seconds.

## A scan

Open any scan from **Scans**. Results are ordered failures first, then errors, then passes.
Each failing check shows how many rows it evaluated and how many failed, what it observed
(the dominant shape and its share, the mean and bounds, the newest timestamp), and a sample of
the failing rows (or, for duplicates, the most repeated keys and their copies). Download the
scan as **CSV** (one row per check, with the samples) or **PDF**; the numbers are the same
rows the API returns.

On the Orders scans around the broken load, **Order belongs to a customer** and the row count
tell the story, and the anomaly detector flags the drop: "Row count is ..., ...% below the
typical ... (median of the last ... scans)".

## Incidents

**Incidents** lists what the alert rules opened, newest first: open, acknowledged and
resolved. Kestrel Retail has an email channel (Data team) and a signed webhook channel (Ops
webhook, to the mock sink), and four rules: error checks failing (both channels), unusual
changes (anomalies, email), schema changes (webhook) and scan failures (email). People Ops
alerts its People team when Employees scores under 95%.

Open an incident: its title and detail, how many scans have seen it, the first and latest
scan, and every notification with its delivery status. **Acknowledge** it, or **Resolve** it
by hand; a problem that clears resolves on its own at the next scan. Alert emails are in
Mailpit at http://localhost:4925. How it works: [alerts.md](../architecture/alerts.md).

## Connections and alerts

**Connections** shows each database with its last test result, server version and how many
datasets use it; passwords are never shown, only whether one is set. **Alerts** has the
channels (with **Send test**) and the rules.

## Project settings

Owners see **General** (sample size, retention, anomaly sensitivity, whether the AI may see
sample values), **Members** (add existing users as viewer, editor or owner) and **API keys**.
The demo has two keys: "GitHub Actions" (`read`, `scan`) for CI and "Signup service"
(`push`) for the application that pushes signups. A new key is shown once.

Sign in as Arjun (viewer) to see the same project read-only: General and Members can be read
but not changed, and API keys are not shown. Editing controls are hidden throughout, and the
API refuses the same actions with 403.

## Admin

The admin's **Users** (create, disable, reset), **System** (version, backends, queue, counts),
**Audit log** (every change, who made it and from where; append-only) and **Instance
settings** (site name, sign-up, the optional AI assistant).

## From the command line

With the "GitHub Actions" key (create a new one under **API keys**, since keys are shown only
once):

```bash
export DQ_URL=http://localhost:4930 DQ_API_KEY=dq_... DQ_PROJECT=<Kestrel Retail id>
uv run --project apps/api dq scan orders --fail-on error
```

More in [checks-as-code.md](checks-as-code.md) and [api-integration.md](api-integration.md).
