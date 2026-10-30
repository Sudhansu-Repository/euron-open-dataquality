## What and why

<!-- One paragraph: the problem, and how this change solves it. Link the issue. -->

## How it was verified

- [ ] `make lint typecheck test`
- [ ] `make test-integration` (if the API, the scan worker, a source driver, a cache or database code changed)
- [ ] `make e2e` (if a user flow or infrastructure changed)
- [ ] `make tf-validate tf-lint tf-security tf-aws-on-floci` (if Terraform changed)

## Checklist

- [ ] Docs updated (README, `docs/`, configuration reference) for any behavior or config change
- [ ] New Alembic revision instead of editing an applied one
- [ ] Source connections stay read-only, and connection credentials stay sealed (never logged, never returned by the API)
- [ ] No new place where customer rows or samples leave the deployment (AI suggestions stay opt-in, and send sample values only where the project allows it)
- [ ] Check results stay deterministic for the same data (golden dataset tests updated if a check changed)
- [ ] `make openapi` run if the API changed
- [ ] No secrets, account ids, real hostnames or em/en dashes (`make sanitize` is clean)
- [ ] Security-relevant change? Described the threat and mitigation above
