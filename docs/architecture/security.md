# Security

DataQuality holds credentials to an organisation's databases and reads its data. The design
goal is that holding those credentials is as harmless as possible: the platform cannot write
to a source, the credentials are sealed and never returned, failing values it keeps are
bounded and maskable, and nothing leaves the deployment unless an admin turns on AI or
configures an alert channel. The attacks considered are in
[threat-model.md](threat-model.md).

## Read-only by construction

Three independent locks keep scans from changing a source
([ADR-0008](adr/0008-sealed-credentials-and-read-only-by-construction.md)):

1. **The platform only generates `SELECT`.** The check compiler builds SQLAlchemy Core
   `select()` expressions; there is no code path that builds an INSERT, UPDATE or DDL
   against a source.
2. **User SQL is parsed and refused unless it is one read-only query.** Custom SQL checks,
   query datasets and filters are parsed with sqlglot in the source's dialect
   (`engine/sqlguard.py`):
   - exactly one statement, whose root is a `SELECT`, `UNION`, `INTERSECT`, `EXCEPT` or
     subquery (CTEs of selects included);
   - no node anywhere in the tree that is an INSERT, UPDATE, DELETE, MERGE, CREATE, DROP,
     ALTER, a raw command, `SELECT ... INTO`, a locking clause (`FOR UPDATE`), SET, PRAGMA,
     COPY, USE or a transaction statement;
   - no function from a deny list of side effects, sleeps and file or network access across
     the dialects (`pg_sleep`, `pg_read_file`, `dblink`, `lo_import`, `set_config`,
     `nextval`, `pg_advisory_lock`, `sleep`, `benchmark`, `load_file`, `get_lock`,
     `xp_cmdshell`, `openrowset`, `load_extension`, `read_csv`, `read_parquet`, `glob` and
     more);
   - no table function or file path in a FROM clause;
   - a filter must be a plain condition: it is parsed inside `SELECT 1 FROM t WHERE <filter>`
     and refused if it contains a subquery.
3. **The session itself is read-only where the database supports it** (`sources/sql.py`):

   | Database | How | What a write gets |
   | --- | --- | --- |
   | PostgreSQL | `default_transaction_read_only=on` and `statement_timeout` as connection options | `cannot execute ... in a read-only transaction` |
   | MySQL, MariaDB | `SET SESSION TRANSACTION READ ONLY`, plus `MAX_EXECUTION_TIME` (MySQL) or `max_statement_time` (MariaDB) | `Cannot execute statement in a READ ONLY transaction` |
   | SQLite | The uploaded file opened with `mode=ro` and `PRAGMA query_only = 1` | `attempt to write a readonly database` |
   | SQL Server | No session read-only mode exists. Locks 1 and 2 apply, the transaction is always rolled back, and `SET LOCK_TIMEOUT` bounds waits | Connect with a login that has only `db_datareader` for a database-enforced guarantee |
   | DuckDB (files) | An in-memory database holding only the loaded files; after loading, `enable_external_access = false`, `autoload_known_extensions = false`, `lock_configuration = true` | A custom check cannot read a file, reach the network, or change those settings |

   Every source transaction is rolled back at the end, and every source connection is
   closed after use (`NullPool`), so no session to a customer's database stays open.

Use a read-only login anyway. The demo does: it gives DataQuality a `dq_reader` user on each
demo database. Defence in depth means the guard and the session are the second and third
locks, not the first.

## Sealed credentials

| Secret | Where it is stored | Seal context |
| --- | --- | --- |
| Database passwords | `connections.secret_sealed` | `connection:<id>:password` |
| REST request headers (an Authorization header, typically) | `datasets.secret_sealed` | per dataset |
| Slack webhook URL, webhook URL and signing secret | `alert_channels.secret_sealed` | `alert_channel:<id>:secret` |
| The AI provider key | `org_settings.ai_api_key_sealed` | `org_settings:ai_api_key` |

- `KEY_MODE=local`: AES-256-GCM with a key derived (SHA-256) from `LOCAL_MASTER_KEY`, a
  random 96-bit nonce per value, and the context as associated data.
- `KEY_MODE=kms`: KMS `Encrypt` and `Decrypt` with the encryption context
  `{"dataquality:record": <context>}`. On AWS the key policy can scope use by that context.

In both modes the context binds a sealed value to its row: a ciphertext copied from one
connection to another fails to open. The API never returns a sealed value: connections say
`has_password`, datasets `has_secret`, channels show `target_hint` (the host only). The
webhook signing secret is shown once, when the channel is created. Source engines use
`hide_parameters=True`, so a driver error in a log never carries bound values; the
integration suite checks that no response or log line contains a source password.

## Network egress

Every outbound URL is checked twice: when it is saved and again when it is used, against
every address the host resolves to (`core/net.py`).

- **Never allowed:** link-local addresses (instance metadata at `169.254.169.254`), the
  unspecified address, the AWS IPv6 metadata address `fd00:ec2::254`, and the names
  `metadata`, `metadata.google.internal`, `instance-data`. Numeric IPv4 spellings that the
  resolver accepts (`2852039166`, `0xa9fea9fe`, `0251.0376.0251.0376`, a trailing dot) are
  canonicalised first, so none of them slips through.
- **Database hosts:** private addresses allowed by default, because databases live on
  private networks (`SOURCE_ALLOW_PRIVATE=true`).
- **REST datasets, Slack and webhooks:** private and loopback addresses refused unless
  `OUTBOUND_ALLOW_PRIVATE=true` (the local stack sets it for its demo webhook sink).
  Redirects are never followed, and REST responses are capped at `REST_MAX_BYTES`.
- **The AI endpoint:** metadata always refused; private hosts refusable with
  `AI_ALLOW_PRIVATE_ENDPOINTS=false` (default true, so a model inside the network such as
  Ollama or vLLM works).

## Authentication

- **Passwords:** argon2id (argon2-cffi defaults). At least 10 characters with upper and
  lower case and a digit. Unknown emails are verified against a dummy hash, so timing does
  not reveal which accounts exist.
- **Lockout:** 5 failed sign-ins lock the account for 15 minutes, counted atomically in
  Postgres. Sign-in is also throttled to 20 per minute per IP and sign-up to 10, in the KV
  store.
- **Sessions:** HS256 JWTs signed with `SESSION_SECRET`, audience `dataquality-dashboard`,
  lifetime `SESSION_TTL_HOURS`. The dashboard keeps it in the `dq_session` cookie
  (HttpOnly, SameSite=Lax, Secure when `COOKIE_SECURE=true`); scripts send it as a bearer
  token. Sign-out records the token id in `revoked_sessions`; a password change bumps the
  user's `session_version`, which ends every other session.
- **CSRF:** a mutation authenticated by the cookie must carry `X-DQ-CSRF: 1`. A cross-site
  page cannot add a custom header without a CORS preflight, which the origin allowlist
  (`CORS_ORIGINS`) refuses. Requests with an explicit `Authorization` header need no CSRF
  header: browsers never attach one cross-site.
- **First user:** sign-up is closed by default; the first account on a fresh instance is
  always allowed and becomes the admin. Admins create other accounts, or open sign-up in
  instance settings.

## Authorization

People hold a role per project: `viewer` (read everything in the project), `editor`
(datasets, checks, connections, alerts, scans), `owner` (members, API keys, project
settings, delete). Any signed-in user may create a project and becomes its owner. Instance
admins act as owners everywhere and manage users and instance settings.

API keys belong to one project and carry scopes instead of roles:

| Scope | Allows |
| --- | --- |
| `read` | Everything a viewer sees |
| `scan` | Trigger scans, wait for them, cancel them |
| `push` | Send records to push datasets |
| `manage` | Edit datasets and checks (checks as code from CI) |

Routes that need the owner role refuse every API key. Keys look like `dq_<prefix>_<secret>`;
the prefix (12 hex characters) finds the row and the secret is compared, in constant time,
as an HMAC-SHA256 with `API_KEY_PEPPER`, so a leaked database alone does not yield usable
keys. A project the caller cannot see, and a key used on another project, answer **404**,
never 403, so a project's existence does not leak.

## Data the platform keeps

- **Failing samples** are bounded by the project's `sample_size` (default 20, up to 200;
  0 keeps none). Text values longer than 200 characters are cut and binary values shown as
  a short hex prefix.
- **Masked columns** (per dataset) are replaced by `[masked]` in samples, previews, profile
  top values, minimum and maximum, and quantiles, before anything is stored or returned.
  Aggregates that do not show a value (counts, mean, standard deviation, histogram bins,
  value shapes) are still computed and shown for masked columns.
- **Retention** deletes old scan results per project ([data-model.md](data-model.md#retention)).
- **The audit log** records every mutation with the actor, target and IP, and the database
  refuses to update or delete its rows.
- **AI** is off by default. With it on, prompts carry column names, types and profile
  statistics; sample values only when the project sets `ai_allow_samples`, and never for
  masked columns. No request is made at all while AI is off.

## Reports

CSV cells starting with `=`, `+`, `-`, `@`, a tab or a carriage return are prefixed with a
quote, so a value planted in the data cannot run as a formula when a report is opened in a
spreadsheet. A side effect: negative numbers in samples appear as `'-12.5`.

## Transport and headers

The API adds `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
`Referrer-Policy: no-referrer`, `Cross-Origin-Opener-Policy: same-origin` and a restrictive
`Permissions-Policy` to every response, and gzips responses over 2 KB. The web app sets a
Content-Security-Policy (`default-src 'self'`, `frame-ancestors 'none'`, `object-src
'none'`) and HSTS in production. Request bodies are capped before any route parses them
(`MAX_BODY_BYTES`, with larger limits for uploads and pushes from authenticated callers).
On AWS, RDS forces TLS and the ALB terminates HTTPS.

## Operator checklist

- Generate secrets with `make env` locally; on AWS they come from Secrets Manager. Never
  reuse `SESSION_SECRET` as `API_KEY_PEPPER` (production refuses to start if they match).
- Set `ENVIRONMENT=production`, `COOKIE_SECURE=true`, `STORAGE=s3`, `KEY_MODE=kms` and a real
  `MAIL_BACKEND`; `guard()` refuses the unsafe combinations.
- Give every connection a read-only login, and `db_datareader` only on SQL Server.
- Restrict `source_cidrs` in the AWS environment to the networks your databases are in.
- Mark columns holding personal data as masked; lower `sample_size` where samples are not
  wanted at all.
- Keep `OUTBOUND_ALLOW_PRIVATE=false` unless a webhook or REST source must live inside your
  network.
- Keep `/metrics` off the public load balancer (the AWS `service` module restricts it to
  `metrics_allowed_cidrs`).
- Leave AI off, or point it at a model inside your network; turn on `ai_allow_samples` only
  for projects whose data may go to that model.
