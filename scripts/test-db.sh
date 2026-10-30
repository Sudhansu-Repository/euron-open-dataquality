#!/usr/bin/env bash
# Make sure Postgres, Redis and the source databases (a PostgreSQL and a MySQL) are
# reachable for the integration suite. Reuses the Compose services when the stack is up;
# otherwise starts just those. MSSQL=1 adds the SQL Server source.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORTS=("${DQ_PG_PORT:-4942}" "${DQ_REDIS_PORT:-4979}" "${DQ_SOURCE_PG_PORT:-4943}" "${DQ_SOURCE_MYSQL_PORT:-4906}")
SERVICES=(postgres redis source-postgres source-mysql)
if [[ "${MSSQL:-}" == "1" ]]; then
  PORTS+=("${DQ_SOURCE_MSSQL_PORT:-4933}")
  SERVICES+=(source-mssql)
  export COMPOSE_PROFILES=mssql
fi

ready() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }

all=1
for p in "${PORTS[@]}"; do ready "$p" || all=0; done
[[ $all == 1 ]] && exit 0
"$ROOT/scripts/gen-local-env.sh" >/dev/null
docker compose --env-file "$ROOT/deploy/compose/.env" -f "$ROOT/deploy/compose/compose.yaml" \
  up -d --wait "${SERVICES[@]}"
