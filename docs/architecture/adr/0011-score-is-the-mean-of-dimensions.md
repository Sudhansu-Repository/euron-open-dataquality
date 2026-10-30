# ADR-0011: The score is the mean of dimension scores, built from pass rates

- **Status:** Accepted
- **Date:** 2026-10-30

## Context

Teams want one number they can track per dataset and project, and the acceptance criteria
require it to follow a documented formula with a breakdown by dimension (completeness,
validity, consistency, uniqueness, freshness, volume). The number must not be gameable by
adding easy checks, must be proportional (one bad row in a million is not a failed dataset),
and must not hide a stale table behind many healthy column checks.

## Decision

Per check, a pass rate: `1 - failed / evaluated` for row-level checks, 1 or 0 for schema,
freshness and row count; errors and checks that evaluated nothing are left out. A dimension's
score is the mean pass rate of its checks; the dataset's score is the mean of the dimensions
it has; the project's score is the mean of its datasets' latest scores. Severity and
tolerance do not change the score. Formula and worked example: [scoring.md](../scoring.md).

## Consequences

**Good**
- Each dimension weighs the same however many checks it has, so ten `not_null` checks do not
  drown a freshness failure, and a team sees which kind of quality moved.
- Proportional: the score moves with the share of failing records.

**Bad / caveats**
- A dataset with one check in a dimension gives that one check a large weight (a single
  failed freshness check costs a fifth or a sixth of the score). That is intended, but it
  surprises people at first.
- Pass rates of different checks are averaged as if comparable; a 2% failure in a key column
  and a 2% failure in an optional note count the same. Severity, alerts and the per-check
  results carry that distinction.

## Alternatives considered

- **Mean over all checks**: dilutable by adding checks.
- **Share of checks passing**: not proportional, and tolerance would decide the score.
- **Weights per check set by users**: flexible, but the number would stop meaning the same
  thing across datasets and projects.
