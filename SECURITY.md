# Security Policy

DataQuality holds credentials to an organisation's databases, runs SQL against them, and keeps
samples of their failing records. We take reports seriously and respond quickly.

## Supported versions

| Version | Supported |
| ------- | --------- |
| 0.x (latest minor) | Yes |
| Older minors | No |

## Reporting a vulnerability

**Please do not open a public issue for security problems.**

Report privately through GitHub's
[private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)
on this repository ("Security" tab, "Report a vulnerability").

Please include:

- the affected component (`apps/api`, the scan worker, `apps/web`, `infra/terraform/...`) and
  version or commit,
- a description of the issue and its impact,
- steps to reproduce, or a proof of concept (for a SQL guard bypass, the check or query and
  the source database and version),
- any suggested mitigation.

What to expect:

| Stage | Target |
| ----- | ------ |
| Acknowledgement | within 3 business days |
| Initial assessment and severity | within 7 business days |
| Fix or mitigation for critical and high issues | within 30 days |
| Coordinated public disclosure | after a fix is released, credited to you unless you prefer otherwise |

## Scope

In scope: the code in this repository and the infrastructure it provisions with its default
settings. We are especially interested in:

- **any way to change data in a source database through the platform**: a custom SQL check,
  query dataset or filter that passes the SQL guard and writes, locks, calls a function with
  side effects, or runs a second statement, on any supported database,
- any way for a check on a file dataset to read files or reach the network from DuckDB,
- recovering a source password, REST header, Slack or webhook URL, webhook secret or the AI
  key from the API, logs, reports or the database (other than by holding the sealing key),
- reading another project's datasets, samples, results or incidents, or using an API key
  beyond its project or scopes,
- requests from the platform reaching instance metadata, or private addresses where the
  configuration forbids them (connections, REST datasets, webhooks, the AI endpoint),
- forged or replayable webhook signatures,
- masked column values appearing in samples, previews, profiles, reports or AI prompts,
- authentication or authorization bypasses, CSRF, session fixation or revocation failures,
- spreadsheet formula injection through reports.

Out of scope:

- **SQL Server's lack of a read-only session.** Documented in
  [docs/architecture/security.md](docs/architecture/security.md); a write that requires the
  login to have write rights and passes the SQL guard is in scope, the general observation is
  not.
- **The demo seed.** `make demo` creates well-known demo accounts with the password from your
  local `.env`, on purpose.
- **The mock AI** (`apps/api/src/mockai`), a test fixture and webhook sink never deployed to
  AWS.
- Members seeing the unmasked data of their own project, and admins seeing every project (by
  design).
- Load a valid read-only query puts on a source within its statement timeout.
- Findings that require a compromised host, a compromised AWS account, or leaked deployment
  secrets (`SESSION_SECRET`, `API_KEY_PEPPER`, `LOCAL_MASTER_KEY`, KMS decrypt rights).
- Denial of service through resource exhaustion of a deployment you operate yourself.

## Hardening checklist for operators

See [docs/architecture/security.md](docs/architecture/security.md#operator-checklist).
