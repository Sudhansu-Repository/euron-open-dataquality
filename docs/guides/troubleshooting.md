# Troubleshooting

Messages below are quoted from the code, so you can search for them. Errors from the API come
as `{"error": {"code", "type", "message", "details"}}`; the `code` is stable and listed where
it helps.

## Starting the stack

| Symptom | Cause | Fix |
| --- | --- | --- |
| `make up` fails with "port is already allocated" | Something else uses 4910, 4925, 4930, 4942, 4943, 4906, 4950, 4966 or 4979 | Set the matching `DQ_*_PORT` in `deploy/compose/.env` ([configuration.md](configuration.md#local-stack-deploycomposeenv)) |
| Compose says "run `make env` first" | `deploy/compose/.env` is missing a secret | `make env` (never overwrites). After regenerating secrets, `make down` so the databases match |
| The API exits with "unsafe production configuration: ..." | `ENVIRONMENT=production` with a demo or short secret, equal secrets, `COOKIE_SECURE=false`, `MAIL_BACKEND=log`, `STORAGE=local` or an endpoint override | Fix each item the message lists; they are the `guard()` rules in [configuration.md](configuration.md) |
| `make up MSSQL=1` is very slow on a Mac | The SQL Server image is amd64 only and runs under emulation | Expected; leave it out unless you need SQL Server |
| `make demo` stops with an HTTP error | The stack was not healthy yet, or an earlier partial demo exists | `make ps`; if the demo project exists the seed only prints the logins. For a clean demo: `make down && make up && make demo` |

## Connections

`POST .../connections/{id}/test` turns driver errors into a sentence (`connections/service.py`,
`friendly()`):

| Message | What to check |
| --- | --- |
| "The username or password was refused. Check them, and that the user may log in" | Credentials, and on PostgreSQL `pg_hba.conf` for the platform's address |
| "The database name was not found on the server" | The database field (case matters on some servers) |
| "The host name could not be resolved. Check the spelling, or use an IP address" | DNS from the API and worker containers, not from your laptop. A database on your own machine is `host.docker.internal` from Docker Desktop |
| "Nothing answered on that host and port. Check the port, firewall and that the database is running" | Port, security groups (`source_cidrs` on AWS), that the server listens on a non-loopback address |
| "The connection timed out. Check that the database is reachable from this deployment" | Network path; on AWS, peering or routes to the database's VPC |
| "The SSL handshake failed (...). Try another SSL mode" | `ssl_mode`: `require` or `verify-full` for servers that demand TLS, `disable` for local test servers without it |
| "The database did not answer in time" | The test has a 20 s limit; the server is slow or unreachable |
| "The host resolves to an address this deployment refuses (metadata, or private when SOURCE_ALLOW_PRIVATE=false)" | The host resolves to a link-local or metadata address (always refused), or to a private one with `SOURCE_ALLOW_PRIVATE=false` |
| "This SQLite connection has no database file" | Upload the file again |
| "N datasets use this connection. Delete or move them first" (`connection_in_use`) | A connection with datasets cannot be deleted |

## Datasets and uploads

| Message | Cause | Fix |
| --- | --- | --- |
| "unknown file type; upload CSV, TSV, JSON, NDJSON, Parquet or Excel (.xlsx)" | The extension is not one of `.csv .tsv .tab .txt .json .jsonl .ndjson .parquet .pq .xlsx .xlsm` and the file does not start like JSON | Rename it with the right extension |
| "the file does not look like parquet" (or xlsx) | The extension says Parquet or Excel but the bytes do not | Export the file again |
| "the CSV file could not be read: ..." | DuckDB could not parse it (quoting, encoding, delimiter) | Set the delimiter in the dataset options; save the file as UTF-8 |
| "the Excel file could not be read: ..." | A protected or damaged workbook, or a missing sheet | Remove the protection; check the sheet name |
| "The request body is larger than N bytes. Split it, use a background job, or raise MAX_BODY_BYTES" (413) | Over the body limit. Uploads get `MAX_UPLOAD_BYTES` and pushes `MAX_PUSH_BYTES`, but only with a valid session or API key | Sign in (or send the key) before uploading; raise the limit if the file is legitimately larger |
| "There is nothing to scan yet. Upload a file first" (or "Push records to it first"; `nothing_to_scan`) | A file or push dataset without a version | Upload a file or push a batch |
| "table 'x' was not found or has no columns" | The table was renamed or dropped, or the login cannot see it | Grant `SELECT`, or edit the dataset |
| "The dataset's connection no longer exists" | The connection was deleted | Point the dataset at another connection |
| "Records can only be pushed to a push dataset" | `POST .../records` on another kind | Create a push dataset |
| "At most 50,000 records per request; split the batch" (`too_many_records`) | Over `MAX_PUSH_RECORDS` | Split the batch |

### REST datasets

| Message | Fix |
| --- | --- |
| "The REST endpoint could not be read: the endpoint answered HTTP 401" | Check the Authorization header saved with the dataset |
| "...: the endpoint redirected; use the final URL" | Redirects are never followed; use the URL it redirects to |
| "...: the URL resolves to a private or metadata address, which this deployment refuses" | Private endpoints need `OUTBOUND_ALLOW_PRIVATE=true` |
| "...: the response is larger than N bytes" | Page the endpoint, or raise `REST_MAX_BYTES` |
| "...: the response is not JSON" | The endpoint must return JSON |
| "...: the response has nothing at 'data.items' (stopped at 'items')" | Fix the records path (dotted, numeric parts index arrays) |
| "...: the records must be a JSON array of objects" | Point the records path at the array |
| "The REST endpoint returned no records" | An empty array cannot be scanned |

## Checks

| Message | Cause | Fix |
| --- | --- | --- |
| "column 'x' does not exist in customers" | A renamed column, or a typo | Edit the check; the result is an `error`, not a failure, and does not count in the score |
| "freshness needs a date or timestamp column, not integer" | Wrong column type | Use a date, timestamp or ISO text column |
| "outliers needs a numeric column, not text" | Wrong column type | Use a `type` check first, or a numeric column |
| "reference dataset 'x' is not in the same source, so it cannot be joined" | Referential checks join within one database connection, or among file, REST and push datasets | Add the reference table as a dataset on the same connection |
| "use explicit classes such as [0-9] instead of \d, \w or \s" | A non-portable regex | Rewrite with the portable subset ([checks.md](../architecture/checks.md#regular-expressions)) |
| "lookahead and lookbehind are not supported by every database" (also back references, inline flags, POSIX classes) | Same | Same |
| "only SELECT is allowed, not INSERT" / "INSERT is not allowed in a read-only check" (`unsafe_sql`) | Custom SQL that is not a read-only query | Custom SQL returns the failing rows with one `SELECT` |
| "use exactly one SELECT statement" | Two statements, or a trailing second statement after `;` | One statement |
| "the function pg_sleep is not allowed" | A function on the deny list | Remove it |
| "a filter is a plain condition such as status = 'active'" | A filter with a subquery or not a condition | Use a query dataset for complex logic |
| "Invalid range check: ..." (`invalid_check`) | Parameters that do not fit the type | The message names the field; parameters per type are in [checks.md](../architecture/checks.md) |
| "A check named 'x' exists on this dataset" (`name_taken`) | Names are unique per dataset | Rename, or apply YAML (which updates by name) |

## Scans

| Message or symptom | Cause | Fix |
| --- | --- | --- |
| Scans stay `queued` | No worker running, every worker busy, or the connection is at `max_concurrent_scans` | `make ps`, `make logs SERVICE=worker`; the admin **System** page shows queued and running scans and the age of the oldest |
| "the scan ran past its time limit" | The dataset's scan timeout (default 1,800 s) passed | Raise `scan_timeout_s` on the dataset, add a dataset filter, or check a replica |
| A statement error such as "canceling statement due to statement timeout" | One query passed `STATEMENT_TIMEOUT_S` (default 300 s) | Raise it, or reduce the work (index the filter column, narrow custom SQL) |
| "The worker running this scan stopped responding 3 times" | The worker died or stalled on every attempt (often out of memory on a large file) | Raise worker memory, lower `DUCKDB_MEMORY_LIMIT`, check `make logs SERVICE=worker` |
| "Cancelled before it started" / "Cancelled" | Someone cancelled it | None |
| "Too many scans requested in this project. Wait a minute and try again" (429, `retry-after`) | Over `SCAN_RPM` (30 per project per minute) | Wait, or raise `SCAN_RPM`; pushes are not counted |
| `dq scan` exits 1 with "the scan did not finish in 300s; it keeps running (id ...)" | The wait ran out | `--timeout` (or `DQ_TIMEOUT`) longer; the scan continues in the background |
| The profile says `sampled` | More rows than `PROFILE_MAX_ROWS` | Expected: checks are still exact; raise the limit to profile everything |

## Alerts

| Symptom | Cause | Fix |
| --- | --- | --- |
| No emails locally | Mail goes to Mailpit, not the internet | Open http://localhost:4925 |
| Emails on AWS go nowhere | SES is in its sandbox, or DKIM is not set | Add the DKIM records; request production access |
| A notification shows "the endpoint answered HTTP 404" or "could not reach the endpoint (ConnectError)" | The webhook or Slack URL is wrong or down | Fix the channel; **Send test** reports the error at once. Retries back off up to an hour, 8 attempts |
| "the channel has no recipients" | An email channel without addresses | Add recipients |
| No second email while a check keeps failing | By design: one notification per incident and channel | The incident counts occurrences; you get one more when it resolves |
| A receiver rejects the signature | It verifies a re-serialised body, or its clock is off by more than its tolerance | Verify the raw bytes ([alerts.md](../architecture/alerts.md#verifying-the-signature)) |

## Accounts and access

| Message | Cause | Fix |
| --- | --- | --- |
| "Too many failed attempts. Try again in a few minutes" (`account_locked`) | 5 wrong passwords lock the account for 15 minutes | Wait, or an admin resets the password (`make admin EMAIL=...`) |
| "Too many sign-in attempts from this address. Wait a minute and try again" | 20 sign-ins per minute per IP | Wait |
| "Sign-up is closed. Ask an administrator for an account" (`signup_closed`) | Only the first account may sign up unless an admin opens sign-up | An admin creates the account, or opens sign-up in **Instance settings** |
| "Missing CSRF header" (`csrf_required`) | A script using the session cookie without `X-DQ-CSRF: 1` | Send the header, or use `Authorization: Bearer` |
| "This API key lacks the 'scan' scope" (`insufficient_scope`) | The key was created without that scope | Create a key with the scope (owners, **Project settings**, **API keys**) |
| "Project not found" with a valid key | The key belongs to another project | Keys work on their own project only |
| "No user with this email. Ask an admin to create the account first" (`user_not_found`) | Members must have an account | An admin creates the user first |
| "The AI assistant is off. An admin can turn it on in Settings with any OpenAI-compatible endpoint" (`ai_disabled`) | AI is off (the default) | Admin, **Instance settings** |
