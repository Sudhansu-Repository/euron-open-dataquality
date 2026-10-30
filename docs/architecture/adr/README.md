# Architecture decision records

Decisions a newcomer would question, with the context and the alternatives. To change one,
add a new record that supersedes it rather than editing the old one.

| ADR | Decision |
| --- | --- |
| [0001](0001-checks-run-as-sql-in-the-source.md) | Checks run as SQL inside the source, not in pandas |
| [0002](0002-postgres-as-the-scan-queue.md) | PostgreSQL as the scan queue, not Celery (which the brief suggested) |
| [0003](0003-duckdb-for-files.md) | DuckDB for files, REST and push data |
| [0004](0004-own-check-engine.md) | Our own check engine instead of bundling Great Expectations or Soda Core |
| [0005](0005-mit-licence.md) | MIT licence, although the brief suggested Apache 2.0 |
| [0006](0006-nearest-rank-quantiles.md) | Nearest-rank quantiles in profiles |
| [0007](0007-robust-z-score-for-anomalies.md) | Robust z-score (median and MAD) for anomaly detection |
| [0008](0008-sealed-credentials-and-read-only-by-construction.md) | Sealed credentials, and read-only by construction |
| [0009](0009-nextjs-frontend.md) | Next.js for the web app, although the brief suggested plain React |
| [0010](0010-redis-is-optional.md) | Redis is optional |
| [0011](0011-score-is-the-mean-of-dimensions.md) | The score is the mean of dimension scores, built from pass rates |
| [0012](0012-one-package-api-and-worker.md) | One package and one image for the API and the scan worker |
