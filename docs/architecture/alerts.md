# Alerts and incidents

A finished scan becomes incidents (what is wrong now) and notifications (who was told). The
guarantees: one problem has one open incident however many scans see it, each channel hears
about it once when it opens (and once when it resolves, if asked), and the incident resolves
by itself when a scan no longer shows the problem. Code: `apps/api/src/dataquality/alerts/`.

## Channels

| Kind | Configuration | Delivery |
| --- | --- | --- |
| `email` | Recipients (up to 50) | One email per recipient through `MAIL_BACKEND` (Mailpit locally, SMTP or SES) |
| `slack` | An incoming webhook URL (sealed) | `POST {"text": ...}` with a red, green or blue circle for opened, resolved and test |
| `webhook` | A URL and a signing secret (both sealed; the secret is generated when omitted and shown once) | `POST` of the JSON payload below, signed |

URLs are checked when saved and again when used: never a metadata or link-local address,
and no private or loopback address unless `OUTBOUND_ALLOW_PRIVATE=true`. Redirects are not
followed; any status of 300 or above is a failure. **Send test** delivers a test message at
once (not through the outbox) and reports the error if it fails.

## Rules

A rule says when to alert and to which channels. It covers one dataset, or every dataset in
the project when `dataset_id` is empty.

| Kind | Opens an incident when | Problem key | Severity |
| --- | --- | --- | --- |
| `check_failed` | A check fails with severity at or above the rule's `min_severity` (`error` by default; `warn` includes warnings) | `<dataset>:check:<check id>` | the check's |
| `score_below` | The scan's score is below `threshold` (0 to 100, required) | `<dataset>:score` | `error` |
| `anomaly` | The scan flagged a metric anomaly | `<dataset>:metric:<metric>:<key>` | `warn` |
| `schema_change` | A column was added, removed or retyped since the previous scan | `<dataset>:schema:schema:<column>` | `error` |
| `scan_failed` | The scan failed (source unreachable, table gone, timeout, out of attempts) | `<dataset>:scan_failed` | `error` |

Each rule also has `notify_on_resolve` (default true) and `enabled`. Freshness has no rule
kind of its own: a failing `freshness` check is a `check_failed` problem like any other.

## Incident lifecycle

| From | Event | To |
| --- | --- | --- |
| (none) | A scan shows the problem | `open`, `opened` notifications queued |
| `open` | A person acknowledges | `acknowledged` |
| `open` or `acknowledged` | A scan shows the problem again | unchanged, `occurrences + 1` |
| `open` or `acknowledged` | A successful scan no longer shows it | `resolved` (`cleared`), `resolved` notifications if the rule asks |
| `open` or `acknowledged` | A person resolves it | `resolved` (`manual`) |

For each enabled rule that covers the dataset, `engine.evaluate` computes the scan's
problems and compares them with the rule's unresolved incidents for that dataset:

- **A new problem** inserts an incident (`open`) and one `opened` notification row per
  enabled channel of the rule.
- **A problem that already has an unresolved incident** (open or acknowledged) only updates
  it: `occurrences + 1`, `last_seen_at`, `last_scan_id`, the latest detail. No new
  notification: the team heard about it already.
- **An unresolved incident whose problem is gone** resolves with `resolution = cleared`,
  and queues a `resolved` notification per channel when the rule asks for one.
- **A scan that says nothing about a rule changes nothing.** A failed scan cannot measure
  checks, score, anomalies or schema, so it neither opens nor resolves those incidents; it
  only opens (or keeps open) a `scan_failed` incident, which the next successful scan
  resolves.

People can **acknowledge** an incident (it stays unresolved, so no repeat notifications, and
still resolves on its own) or **resolve** it by hand (`resolution = manual`). A problem that
is still there at the next scan then opens a new incident, because the old one is closed.
Deleting a rule deletes its incidents. With the optional AI on, **Explain** asks the model
for a plain-language explanation of an incident.

## Exactly one incident and one notification

Two scans of the same dataset can finish at the same moment on two workers. Two database
constraints make the guarantees hold anyway:

- the partial unique index `uq_incidents_open_key (rule_id, key) WHERE status <> 'resolved'`:
  the incident insert is `INSERT ... ON CONFLICT (rule_id, key) WHERE status <> 'resolved'
  DO NOTHING RETURNING id`, so the second scan gets no row back and skips the notification;
- the unique key `(incident_id, channel_id, event)` on `notifications`, inserted with
  `ON CONFLICT DO NOTHING`.

The `WHERE` of that `ON CONFLICT` is literal SQL text, not a bound parameter. PostgreSQL
can infer a partial unique index as the conflict arbiter only when the statement's predicate
implies the index predicate. With a parameter (`status <> $1`) that holds for the first
executions, but after five executions of the same prepared statement PostgreSQL may switch
to a generic plan, where the parameter's value is unknown at planning time, cannot prove the
implication, and fails with "there is no unique or exclusion constraint matching the ON
CONFLICT specification". The literal predicate (`text("status <> 'resolved'")`) is the same
in every plan. The integration suite opens many incidents on one connection to keep it that
way.

Incident evaluation runs in a **savepoint** of the scan's completion transaction: incidents
and notification rows commit atomically with the results, and an error while alerting is
logged and counted (`dataquality_dependency_errors_total{dependency="postgres",
operation="alerts"}`) without costing the scan its results.

## Delivery: the outbox

Notification rows are an outbox. The worker's `notify` task, every tick:

1. claims up to 20 due rows (`status = 'pending' AND next_attempt_at <= now()`) with
   `FOR UPDATE SKIP LOCKED`, so replicas never send the same row;
2. skips a row whose channel was disabled or deleted (`skipped`);
3. sends it; on success `sent` with `sent_at`;
4. on failure records the error and retries with exponential backoff: 1, 2, 4, 8, 16, 32,
   then 60 minutes; after 8 attempts the row is `failed` and stays visible on the incident
   with its last error.

Delivery is at least once per row: a worker that crashes after sending but before
committing sends that row again. Receivers can deduplicate on `incident.id` and the event.

## Webhook payload

```json
{
  "event": "incident.opened",
  "incident": {
    "id": "6f0c...",
    "status": "open",
    "severity": "error",
    "title": "Orders: Order belongs to a customer failed",
    "detail": "37 values have no match in customers.customer_id",
    "opened_at": "2026-10-30T06:04:12.381+00:00",
    "occurrences": 1,
    "url": "https://dq.example.com/projects/<project>/incidents/6f0c..."
  },
  "dataset": {"id": "...", "name": "Orders", "slug": "orders"},
  "project_id": "...",
  "sent_at": "2026-10-30T06:04:15.002+00:00"
}
```

`event` is `incident.opened`, `incident.resolved` or `incident.test` (a test has no
dataset). Headers: `content-type: application/json`, `x-dq-event: <event>`, and, when the
channel has a secret, `x-dq-signature`. The incident URL is built from `PUBLIC_URL`.

## Verifying the signature

```
X-DQ-Signature: t=<unix seconds>,v1=<hex HMAC-SHA256 of "<t>.<raw body>" with the channel secret>
```

The timestamp is part of what is signed, so a captured request cannot be replayed later
with a new time. A receiver must compute the HMAC over the **raw body bytes as received**
(not a re-serialised JSON object), compare in constant time, and reject timestamps too far
from its own clock:

```python
import hashlib
import hmac
import time


def verify(secret: str, body: bytes, header: str, tolerance_s: int = 300) -> bool:
    """True when the X-DQ-Signature header matches the raw body and is recent."""
    try:
        parts = dict(item.split("=", 1) for item in header.split(","))
        ts = int(parts["t"])
        received = parts["v1"]
    except (ValueError, KeyError):
        return False
    if abs(time.time() - ts) > tolerance_s:
        return False
    expected = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, received)
```

In a FastAPI receiver:

```python
from fastapi import FastAPI, HTTPException, Request

app = FastAPI()
SECRET = "the signing secret shown when the channel was created"


@app.post("/dataquality")
async def receive(request: Request) -> dict[str, str]:
    body = await request.body()
    if not verify(SECRET, body, request.headers.get("x-dq-signature", "")):
        raise HTTPException(status_code=401, detail="bad signature")
    event = await request.json()
    # deduplicate on (event["incident"]["id"], event["event"]) before acting
    return {"ok": "true"}
```

`alerts/delivery.py` has the same `verify` function, which the integration tests use against
a webhook sink.
