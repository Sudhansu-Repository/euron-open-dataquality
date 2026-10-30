# API integration

Other applications and pipelines use DataQuality through its REST API: trigger a scan and
read the result in one call, push a batch of records and get it validated, or manage checks
as code. The full reference is the OpenAPI document: interactive at `/docs`, raw at
`/openapi.json`, and committed as [`docs/api/openapi.yaml`](../api/openapi.yaml).

## API keys and scopes

Project owners create keys under **Project settings**, **API keys**, or with
`POST /api/v1/projects/{project_id}/api-keys`:

```json
{"name": "GitHub Actions", "scopes": ["read", "scan"]}
```

The response contains `key` (`dq_<prefix>_<secret>`) **once**; only an HMAC of the secret is
stored. Without `scopes` a key gets `read` and `scan`.

| Scope | Allows |
| --- | --- |
| `read` | Everything a project viewer can read: datasets, checks, scans, results, history, anomalies, incidents, reports, the dashboard |
| `scan` | Trigger, wait for and cancel scans |
| `push` | Push records to push datasets |
| `manage` | Create and change datasets and checks (including YAML checks as code) |

A key belongs to one project. On any other project it gets the same 404 as a project that
does not exist. Routes that need the owner role (members, keys, project settings) refuse
every key. Revoke a key with `DELETE /api/v1/projects/{p}/api-keys/{key_id}`; it stops working
at once.

Send the key either way:

```
Authorization: Bearer dq_3f9a1c0b7e2d_...
X-API-Key: dq_3f9a1c0b7e2d_...
```

People can also call the API with a session: `POST /api/v1/auth/login` returns a token to send
as `Authorization: Bearer <token>` (the dashboard uses an HttpOnly cookie instead, and cookie
requests that change something must send `X-DQ-CSRF: 1`).

## Trigger a scan and wait for the result

```bash
curl -s -X POST \
  -H "Authorization: Bearer $DQ_API_KEY" -H "Content-Type: application/json" \
  -d '{"idempotency_key": "nightly-2026-10-30"}' \
  "$DQ_URL/api/v1/projects/$PROJECT/datasets/$DATASET/scans?wait=120"
```

- `wait` (seconds, 0 to 300, default 0): the request returns when the scan finishes or the
  wait runs out. **200** with the finished scan, or **202** with its current state (`queued`
  or `running`) to poll later.
- Body (optional): `idempotency_key` (up to 128 characters) and `profile` (profile columns
  too; defaults to the dataset's setting).
- Scans requested with a key are recorded with `trigger: "api"` and the key as requester.

The response is the scan with every check result:

```json
{
  "id": "...", "dataset_id": "...", "dataset_name": "Orders",
  "status": "succeeded", "trigger": "api", "attempt": 1,
  "row_count": 48210, "score": 96.4,
  "dimension_scores": {"consistency": 99.9, "freshness": 100.0, "validity": 89.3},
  "checks_total": 3, "checks_passed": 2, "checks_failed": 1, "checks_warned": 0,
  "checks_errored": 0, "failed_rows": 37, "duplicate_rows": 0,
  "results": [
    {"check_name": "Order belongs to a customer", "type": "referential",
     "severity": "error", "dimension": "consistency", "status": "fail",
     "evaluated": 48210, "failed": 37, "failed_pct": 0.0767,
     "observed": {"reference": "customers"}, "sample": [{"order_id": 1001, "...": "..."}],
     "message": "37 values have no match in customers.customer_id", "error": null}
  ],
  "error": null
}
```

(Values shown for illustration.) Then:

| Call | What |
| --- | --- |
| `GET .../scans/{scan_id}/wait?timeout=60` | Wait again (1 to 300 s) for a scan started earlier |
| `GET .../scans/{scan_id}` | The scan with its results |
| `POST .../scans/{scan_id}/cancel` | Cancel a queued or running scan |
| `GET .../scans?dataset_id=&status=&limit=&cursor=` | Scans, newest first; `next_cursor` for the next page |
| `GET .../scans/{scan_id}/report.csv`, `report.pdf` | The scan as a report |

A scan's `status` is final once it is `succeeded`, `failed` (with `error` explaining why) or
`cancelled`. "Passed" is your rule: the CLI's default is no failing check of severity
`error`.

### Idempotency keys

A scan request with an `idempotency_key` that the dataset already has returns **that scan**,
whatever its state, instead of starting another. Use a key per logical run (a pipeline run id
and attempt), so a retried HTTP call or CI step cannot double-scan. Keys are unique per
dataset and kept as long as the scan is (see retention).

## Push records and validate them

For data that lives in an application rather than a database: create a dataset of kind
`push` and its checks, then post batches:

```bash
curl -s -X POST \
  -H "Authorization: Bearer $DQ_PUSH_KEY" -H "Content-Type: application/json" \
  -d '{"records": [{"signup_id": "su_0001", "email": "asha@example.com", "plan": "pro"},
                   {"signup_id": "su_0002", "email": "not-an-email", "plan": "trial"}]}' \
  "$DQ_URL/api/v1/projects/$PROJECT/datasets/$DATASET/records?wait=30"
```

- Each request stores the batch as the dataset's newest version (NDJSON in object storage)
  and scans it with every enabled check, without a profile.
- `wait` defaults to **30** seconds here (0 to 120). The response is
  `{"scan": <scan with results>, "records": 2, "passed": false}`; **202** when the scan is
  still running.
- `passed` is true when the scan succeeded and no check of severity `error` failed.
- Up to `MAX_PUSH_RECORDS` (50,000) records and `MAX_PUSH_BYTES` (25 MB) per request.
  Records are JSON objects; nested objects and arrays become JSON text columns.
- Pushes are not counted against the scan rate limit, and have no idempotency key: retrying a
  push stores and scans the batch again.
- A key with only the `push` scope can push but not read anything else.

`dq push <dataset> <file>` does the same from a terminal or CI
([checks-as-code.md](checks-as-code.md)).

## Manage checks from code

| Call | Scope |
| --- | --- |
| `GET .../datasets/{d}/checks` | `read` |
| `POST .../datasets/{d}/checks` (one), `POST .../checks/bulk` (up to 500) | `manage` |
| `PATCH`, `DELETE .../checks/{check_id}` | `manage` |
| `GET .../checks/yaml`, `PUT .../checks/yaml` | `read`, `manage` |

Checks are validated against their type's parameters and the dataset's SQL dialect before they
are stored ([checks.md](../architecture/checks.md)).

## Errors

Every error has the same envelope:

```json
{
  "error": {
    "code": "insufficient_scope",
    "type": "permission_error",
    "message": "This API key lacks the 'scan' scope",
    "details": {}
  }
}
```

| Status | `type` | Typical `code` |
| --- | --- | --- |
| 400 | `invalid_request_error` | `invalid_check`, `unsafe_sql`, `invalid_yaml`, `too_many_records`, `not_a_push_dataset` |
| 401 | `authentication_error` | `invalid_api_key`, `not_signed_in`, `session_expired` |
| 403 | `permission_error` | `insufficient_scope`, `insufficient_role`, `csrf_required` |
| 404 | `invalid_request_error` | `not_found` (also for projects the caller cannot see) |
| 409 | `invalid_request_error` | `nothing_to_scan`, `name_taken`, `scan_finished`, `connection_in_use`, `ai_disabled`, `conflict` |
| 413 | `invalid_request_error` | `payload_too_large` (`details.limit_bytes`) |
| 422 | `invalid_request_error` | `validation_error` (`details.errors`: location, message, type per field) |
| 429 | `rate_limit_error` | `rate_limited`, with a `retry-after` header in seconds |
| 500 | `api_error` | `internal_error` (logged with the request id; no stack trace in the body) |
| 502 | `invalid_request_error` | `ai_unavailable`: the optional AI model could not be reached |

The `message` is meant for people and says what to do; branch on `code`. Every response
carries `x-request-id` (send your own to correlate logs).

## Rate limits

| Limit | Default | Scope |
| --- | --- | --- |
| Scan requests | 30 per minute (`SCAN_RPM`) | Per project, keys and people together; pushes not counted |
| Sign-in | 20 per minute | Per IP |
| Sign-up | 10 per minute | Per IP |
| Failed sign-ins | 5, then a 15 minute lock | Per account |

With Redis these windows are sliding and shared by every API replica; without
it they are fixed windows per process.

## Body limits

Ordinary requests: `MAX_BODY_BYTES` (2 MB). Pushes and YAML: `MAX_PUSH_BYTES` (25 MB). File
and SQLite uploads (multipart): `MAX_UPLOAD_BYTES` (500 MB), streamed. The larger limits apply
only to requests with a valid session or an API key; anything else is held to 2 MB.
