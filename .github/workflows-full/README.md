# Full CI pipeline (opt-in)

These workflows are the complete quality pipeline for Euron Open DataQuality. They are kept
here, outside `.github/workflows/`, so they do **not** run on the upstream repository.
Only the fast [`checks`](../workflows/checks.yml) workflow (lint, typecheck, unit tests,
sanitization) runs there.

| Workflow | What it runs |
| --- | --- |
| [`ci.yml`](ci.yml) | Sanitization scan, OpenAPI drift, and the integration suite on Postgres 16, Redis 7, Floci and two source databases (a second PostgreSQL 16 and MySQL 8.4): the real API and scan worker checking real tables, with an 85% coverage floor, then the same suite again with KMS sealing and S3 storage on Floci |
| [`security.yml`](security.yml) | gitleaks over full history, CodeQL (Python and TypeScript), pip-audit, pnpm audit |
| [`terraform.yml`](terraform.yml) | `terraform fmt` and `validate` for every environment, tflint, checkov, and the full `aws-dev` environment applied and destroyed against Floci |
| [`docker.yml`](docker.yml) | Multi-arch (amd64, arm64) image builds for the api (also the scan worker) and web images |
| [`e2e.yml`](e2e.yml) | The full stack on the local AWS emulator: the integration suite under every key and storage backend, the Playwright browser tests and the Puppeteer QA sweep |

To enable them in your fork, move them into `.github/workflows/`:

```bash
git mv .github/workflows-full/*.yml .github/workflows/
```

Every gate is also runnable locally:
`make lint typecheck test test-integration test-matrix e2e qa tf-validate tf-lint tf-security tf-aws-on-floci sanitize`.
