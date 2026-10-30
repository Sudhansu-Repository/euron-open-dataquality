#!/usr/bin/env bash
# Run a one-off `dataquality` command as an ECS task, wait for it, print its logs.
#   scripts/aws-run-task.sh <aws-dev|aws-prod> migrate
#   DATAQUALITY_ADMIN_PASSWORD=... scripts/aws-run-task.sh aws-dev create-admin --email you@example.com
#   DQ_DEMO_PASSWORD=... scripts/aws-run-task.sh aws-dev seed-demo
# The command runs as arguments to the `dataquality` CLI (the api image's entrypoint) on the
# migrate task definition. DATAQUALITY_ADMIN_PASSWORD and DQ_DEMO_PASSWORD, when set, are
# passed as environment overrides (never on the command line).
set -euo pipefail
ENV="${1:?usage: aws-run-task.sh <env> <dataquality command...>}"; shift
DIR="$(cd "$(dirname "$0")/.." && pwd)/infra/terraform/envs/$ENV"
spec=$(terraform -chdir="$DIR" output -json run_task)
get() { echo "$spec" | python3 -c "import json,sys; v=json.load(sys.stdin)['$1']; print(','.join(v) if isinstance(v, list) else v)"; }
cluster=$(get cluster)
taskdef=$(get task_definition); container=$(get container); groups=$(get security_groups)
overrides=$(python3 - "$container" "$@" <<'PY'
import json, os, sys
container, *command = sys.argv[1:]
override = {"name": container, "command": command}
env = [{"name": k, "value": os.environ[k]} for k in ("DATAQUALITY_ADMIN_PASSWORD", "DQ_DEMO_PASSWORD") if os.environ.get(k)]
if env:
    override["environment"] = env
print(json.dumps({"containerOverrides": [override]}))
PY
)
network="awsvpcConfiguration={subnets=[$(get subnets)],securityGroups=[$groups],assignPublicIp=DISABLED}"
arn=$(aws ecs run-task --cluster "$cluster" --task-definition "$taskdef" --launch-type FARGATE \
  --network-configuration "$network" --overrides "$overrides" \
  --query 'tasks[0].taskArn' --output text)
echo "started $arn"
aws ecs wait tasks-stopped --cluster "$cluster" --tasks "$arn"
code=$(aws ecs describe-tasks --cluster "$cluster" --tasks "$arn" --query 'tasks[0].containers[0].exitCode' --output text)
group=$(aws ecs describe-task-definition --task-definition "$taskdef" \
  --query 'taskDefinition.containerDefinitions[0].logConfiguration.options."awslogs-group"' --output text)
aws logs tail "$group" --since 15m --format short | tail -40
echo "exit code: $code"
[[ "$code" == "0" ]]
