# Checks as code

A dataset's checks can live in a YAML file in your repository, reviewed like code and applied
from CI, with a CLI (`dq`) that scans a dataset and fails the build when quality drops. The
format is read and written by `apps/api/src/dataquality/checks/service.py`.

## The format

```yaml
version: 1
dataset: orders
checks:
- name: Order belongs to a customer
  type: referential
  column: customer_id
  params:
    dataset: customers
    column: customer_id
- name: Total is not negative
  type: range
  column: total
  params:
    min: 0
- name: Orders are fresh
  type: freshness
  column: ordered_at
  params:
    max_age_hours: 2160
  severity: warn
- name: Paid orders have a payment id
  type: not_null
  column: payment_id
  filter: status = 'paid'
  tolerance:
    max_percent: 0.5
```

| Key | Required | Meaning |
| --- | --- | --- |
| `version` | no (default 1) | Must be `1`; another value is refused with "Unsupported version ..." |
| `dataset` | no | Written on export (the dataset's slug) for readers; ignored on import, where the target is the dataset in the URL or the CLI argument |
| `checks` | yes | A list; the only other top-level key that is read |
| `checks[].type` | yes | One of the 16 check types ([checks.md](../architecture/checks.md)) |
| `checks[].name` | no | Unique per dataset; the key for updates. When missing, a name is built from the type, column and preset (`email pattern (email)`) |
| `checks[].column` | per type | The column |
| `checks[].params` | per type | Validated by the type's parameter model; unknown parameters are errors |
| `checks[].filter` | no | A plain SQL condition limiting the rows checked |
| `checks[].severity` | no (default `error`) | `error` or `warn` |
| `checks[].tolerance` | no | `max_count` and/or `max_percent` |
| `checks[].dimension` | no (default per type) | Override the quality dimension |
| `checks[].enabled` | no (default `true`) | `false` keeps the check but skips it |
| `checks[].description` | no | Free text |

Export writes keys in that order and leaves out defaults (`severity: error`, the type's own
dimension, `enabled: true`, empty values), so an exported file is minimal and stable. Other
keys inside a check item are ignored.

## Applying a file

`PUT /api/v1/projects/{p}/datasets/{d}/checks/yaml` with `{"yaml": "<file>", "prune": false}`
(editor role, or an API key with the `manage` scope):

- every check is validated first, in the dataset's SQL dialect (a filter or custom SQL that
  is not read-only is refused); a file naming the same check twice is refused;
- a name that does not exist is **created**;
- a name that exists is **updated** when any field differs, and left alone when nothing
  changed;
- with `prune: true`, checks on the dataset that the file does not list are **removed** (their
  past results stay in history);
- the response says `created`, `updated` and `removed` (names).

The file is applied in one transaction: if any check is invalid, nothing changes and the
error says which (for example "Check 3 (email valid): ..." or "Invalid pattern check: ...").
Applying the same file twice changes nothing, which the integration suite checks. `GET` on
the same path exports the current checks as `<slug>.dataquality.yaml`.

## The `dq` CLI

`dq` ships in the same package as the server (`apps/api`, entry point
`dataquality.client.cli`). It talks to the API with a project API key.

```bash
pip install "git+https://github.com/euron-sde-team/euron-open-dataquality.git#subdirectory=apps/api"
# or, from a clone: uv run --project apps/api dq ...

export DQ_URL=https://dq.example.com      # the API, or the web origin (it proxies /api)
export DQ_API_KEY=dq_...                  # a project API key
export DQ_PROJECT=<project id>

dq checks export orders > dq/orders.yaml         # current checks as YAML
dq checks apply orders dq/orders.yaml --prune    # make the dataset's checks match the file
dq scan orders --fail-on error                   # scan, wait, exit 1 if an error check fails
dq push signups batch.json                       # validate a batch (JSON array or NDJSON)
```

Datasets are named by id, slug or name. Options:

| Option | Default | Meaning |
| --- | --- | --- |
| `--url`, `--key`, `--project`, `--timeout` | `DQ_URL`, `DQ_API_KEY`, `DQ_PROJECT`, `DQ_TIMEOUT` (300) | Connection and how long to wait for a scan, in seconds. The API waits at most 300 s per request, so keep `--timeout` at 300 or less |
| `scan --fail-on` | `error` | `error`: fail on a failing error-severity check; `warn`: on any failing check; `none`: never fail on results |
| `scan --idempotency-key` | none | A retried CI step with the same key gets the same scan instead of starting another |
| `scan --json` | off | Print the full scan result as JSON |
| `push --fail-on` | `error` | As for `scan`; push waits up to 120 s |
| `checks apply --prune` | off | Delete checks the file no longer lists |

Exit codes: **0** passed, **1** the quality gate failed (a failing check at the chosen
severity, a scan that failed or was cancelled, or a scan that did not finish within the
timeout), **2** a usage or connection problem. The report lists each check, for example:

```
Orders: succeeded, score 96.4%, 48,210 rows
  ok   Total is not negative: All 48,210 rows pass
  FAIL Order belongs to a customer: 37 values have no match in customers.customer_id
  warn Orders are fresh: Newest value is 30.2 hours old (limit 90.0 days)
```

The key needs `read` (to find the dataset by name) plus `scan` for `dq scan`, `push` for
`dq push`, and `manage` for `dq checks apply`.

## GitHub Actions

Keep the YAML in `dq/`, store the key as a secret and the URL and project as variables:

```yaml
name: data-quality

on:
  push:
    branches: [main]
    paths: ["dq/**"]
  schedule:
    - cron: "30 1 * * *"   # every night, after the loads

jobs:
  quality:
    runs-on: ubuntu-latest
    env:
      DQ_URL: ${{ vars.DQ_URL }}
      DQ_PROJECT: ${{ vars.DQ_PROJECT }}
      DQ_API_KEY: ${{ secrets.DQ_API_KEY }}   # scopes: read, scan, manage
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install the dq CLI
        run: pip install "git+https://github.com/euron-sde-team/euron-open-dataquality.git#subdirectory=apps/api"
      - name: Apply checks as code
        run: dq checks apply orders dq/orders.yaml --prune
      - name: Quality gate
        run: dq scan orders --fail-on error --idempotency-key "${{ github.run_id }}-${{ github.run_attempt }}-orders"
```

The runner must reach the API (a public host name, or a self-hosted runner inside your
network). The CLI installs the whole server package and its dependencies, which takes a
little longer than a small client would; cache pip if the job runs often.
