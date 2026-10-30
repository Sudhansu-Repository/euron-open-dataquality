# `observability` module

Logs, alarms and a dashboard:

- A KMS-encrypted log group per app: api, worker, web, migrate.
- Scan metrics extracted from the worker's JSON logs, the CloudWatch side of its Prometheus series (`dataquality_scans_total` and friends, which stay inside the task): `ScansTotal` (every `scan finished` line), `ScansFailed` (scans that finished `failed`), `ScansRequeued` (the `requeued` field of the `reaped scans` line: a worker died or stalled mid-scan) and `ScanErrors` (worker error lines).
- Alarms to an SNS topic (optionally e-mailed): 5xx, api p95 latency, unhealthy targets, CPU and memory per service, database CPU, storage and connections, cache memory and CPU, worker errors, a burst of failed scans, and any re-queued scan.
- `dataquality_queue_depth` (scans queued or running) is a gauge on the worker's `/metrics` only; to alarm on a backed-up queue, add a Prometheus or ADOT sidecar to the worker task.

## Inputs

| Name | Description | Type | Default |
|---|---|---|---|
| `name_prefix` | Prefix for every resource name. | `string` | required |
| `log_retention_days` | CloudWatch log retention for the app log groups. | `number` | `30` |
| `logs_kms_key_arn` | CMK for the log groups (its key policy must allow CloudWatch Logs, as the kms module's does). Null uses CloudWatch's default encryption. | `string` | `null` |
| `alarm_email` | Address subscribed to alarm notifications (confirm the e-mail AWS sends). Null: subscribe something else to the topic. | `string` | `null` |
| `alb_arn_suffix` | Load balancer ARN suffix. | `string` | required |
| `ecs_cluster_name` | ECS cluster name. | `string` | required |
| `lb_services` | Load-balanced services (service module `services`): { api = { service_name, target_group_arn_suffix }, web = { ... } }. Must contain api. | `map(object)` | required |
| `ecs_services` | Every ECS service to watch for CPU and memory (service module `service_names`): { api = "api", worker = "worker", web = "web" }. | `map(string)` | required |
| `db_instance_identifier` | RDS instance identifier. | `string` | required |
| `db_max_connections` | Connection ceiling the alarm measures against. | `number` | `200` |
| `cache_replication_group_id` | ElastiCache replication group id; nodes are <id>-001, <id>-002, ... | `string` | required |
| `cache_node_count` | Nodes in the replication group (cache module num_cache_clusters). | `number` | `1` |
| `target_5xx_threshold` | 5xx responses per 5 minutes (per app, and at the load balancer) that raise an alarm. | `number` | `25` |
| `api_p95_latency_seconds` | api p95 time to first byte that raises an alarm. Judging is queued, never on a request path. | `number` | `3` |
| `scan_finished_log_pattern` | CloudWatch Logs JSON filter matching the worker's `scan finished` line (one per finished scan). | `string` | `"{ $.msg = \"scan finished\" }"` |
| `scan_failed_log_pattern` | CloudWatch Logs JSON filter matching a scan that finished with status failed. | `string` | `"{ ($.msg = \"scan finished\") && ($.status = \"failed\") }"` |
| `scan_reaped_log_pattern` | CloudWatch Logs JSON filter matching the worker's `reaped scans` line (its `requeued` field becomes the metric). | `string` | `"{ $.msg = \"reaped scans\" }"` |
| `worker_error_log_pattern` | CloudWatch Logs JSON filter matching a worker error line. | `string` | `"{ $.level = \"error\" }"` |
| `scan_error_threshold` | Worker error lines per 5 minutes that raise an alarm. | `number` | `5` |
| `scan_failure_threshold` | Failed scans per 5 minutes that raise an alarm. Some failures are the source's fault (unreachable, bad credentials), so this is a rate, not zero. | `number` | `10` |

## Outputs

| Name | Description |
|---|---|
| `log_group_names` | Log group per app: { api, worker, web, migrate } (service module log_group_names). |
| `alarm_topic_arn` | SNS topic receiving every alarm. |
| `dashboard_name` | CloudWatch dashboard. |
| `metrics_namespace` | Namespace of the scan metrics extracted from the worker logs. |
