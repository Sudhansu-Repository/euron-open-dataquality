#!/usr/bin/env bash
# Run the API integration suite under every backend combination the app supports:
#
#   keys:    local AES-GCM key  | AWS KMS (Floci)
#   storage: local disk         | Amazon S3 (Floci)
#
# Redis is not a dimension: rate limits and caches only, with an in-process fallback.
# Needs Floci with the local-floci Terraform applied (make up). Each combination gets its
# own test database, so a run never reuses another's state.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FLOCI_URL="http://localhost:${DQ_FLOCI_PORT:-4966}"
PG="postgresql+asyncpg://dataquality:dataquality@localhost:${DQ_PG_PORT:-4942}"

if ! curl -sf -o /dev/null "$FLOCI_URL/"; then
  echo "Floci is not reachable at $FLOCI_URL. Start the stack first: make up" >&2
  exit 1
fi
"$ROOT/scripts/test-db.sh"

export AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test AWS_REGION=us-east-1
export TEST_AWS_ENDPOINT="$FLOCI_URL"
failed=()
runs=0
for keys in local kms; do
  for storage in local s3; do
    runs=$((runs + 1))
    echo
    echo "== keys=$keys storage=$storage"
    if ! (cd "$ROOT/apps/api" && TEST_KEY_MODE=$keys TEST_STORAGE=$storage \
          TEST_DATABASE_URL="$PG/dataquality_test_matrix_${keys}_${storage}" \
          TEST_REDIS_URL="redis://localhost:${DQ_REDIS_PORT:-4979}/14" \
          uv run pytest tests/integration -q -p no:warnings -rf); then
      failed+=("keys=$keys storage=$storage")
    fi
  done
done
echo
if ((${#failed[@]})); then
  printf 'matrix: FAILED for %s\n' "${failed[@]}"
  exit 1
fi
echo "matrix: all $runs combinations passed"
