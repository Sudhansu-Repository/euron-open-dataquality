# `service` module

The application plane on ECS Fargate behind one Application Load Balancer:

| App | Role | Exposure |
|---|---|---|
| `api` | the API (`/api/*`), probes, docs, connection tests, dataset uploads | ALB on `hostname` (port `api_port`, 8080); Cloud Map for the web app |
| `worker` | claims queued scans, reads source databases, runs checks, delivers alerts, prunes old results | none: its `/metrics` (9464) stays inside the task |
| `web` | the Next.js app (every other path) | ALB (port `web_port`, 3000) |
| `migrate` | one-off task for `migrate`, `create-admin`, `seed-demo` | none |

`api` and `worker` run the same image; `web` has its own. The worker gets `worker_ephemeral_gib` (50 GiB by default) of task storage, because files and source extracts are spooled under `WORK_DIR` during a scan.

The api (connection tests) and the worker (scans) connect out to customer databases on `source_ports` (443, 5432, 3306, 1433) to `source_cidrs`. The default is anywhere; restrict `source_cidrs` to your database networks wherever you can.

Every app: its own security group (ingress only from the ALB or named callers), its own execution and task roles (only the api, worker and migrate touch S3 and KMS; only the api and worker may send mail through SES, with `send_mail`), read-only root filesystem, ARM64, no public IP, deployment circuit breaker with rollback. WAF with AWS managed rules; the body rules that mistake uploads, custom SQL and regular expressions for attacks only count.

## Inputs

| Name | Description | Type | Default |
|---|---|---|---|
| `name_prefix` | Deployment prefix, e.g. "dataquality-prod". At most 24 characters, so target group names stay unique within AWS's 32-character limit. | `string` | required |
| `vpc_id` | VPC of the load balancer and the tasks. | `string` | required |
| `public_subnet_ids` | Public subnets for the load balancer. | `list(string)` | required |
| `private_subnet_ids` | Private subnets the tasks run in. | `list(string)` | required |
| `hostname` | Public host name of the dashboard and API, e.g. dq.example.com. The certificate must cover it. | `string` | required |
| `certificate_arn` | ACM certificate (same region) for the HTTPS listener, covering hostname. | `string` | required |
| `route53_zone_id` | Hosted zone to create the hostname alias record in. Null: point DNS at alb_dns_name yourself. | `string` | `null` |
| `api_image` | Full api image reference (also runs the worker and migrate), e.g. <registry>/dataquality-prod/api:<tag>. | `string` | required |
| `web_image` | Full web image reference, e.g. <registry>/dataquality-prod/web:<tag>. | `string` | required |
| `api_port` | Port the api container listens on (passed to `dataquality serve --port`). | `number` | `8080` |
| `web_port` | Port the web container listens on (PORT). | `number` | `3000` |
| `environment` | Plain environment for api, worker and migrate (PUBLIC_URL and OBJECTS_BUCKET are set by the module). Never secrets. | `map(string)` | `{}` |
| `web_environment` | Plain environment for web (PORT, HOSTNAME and API_INTERNAL_URL are set by the module). Never secrets. | `map(string)` | `{}` |
| `secrets` | Secrets injected into api, worker and migrate: [{ name, valueFrom = "<secret arn>:<json key>::" }] (secrets module ecs_secrets). | `list(object)` | `[]` |
| `kms_key_arn` | CMK that seals source connection credentials and the AI provider key, encrypts the objects bucket and the injected secrets. | `string` | required |
| `objects_bucket_arn` | Objects bucket (storage module bucket_arn). | `string` | required |
| `objects_bucket_name` | Objects bucket name (storage module bucket_name), passed as OBJECTS_BUCKET. | `string` | required |
| `db_security_group_id` | Database security group; api, worker and migrate get ingress on it. | `string` | required |
| `db_port` | Database port. | `number` | `5432` |
| `cache_security_group_id` | Cache security group; api, worker and migrate get ingress on it. | `string` | required |
| `cache_port` | Cache port. | `number` | `6379` |
| `log_group_names` | CloudWatch log group per app: { api, worker, web, migrate } (observability module log_group_names). | `map(string)` | required |
| `logs_kms_key_arn` | CMK for the WAF log group. Null uses CloudWatch's default encryption. | `string` | `null` |
| `cpu_architecture` | ARM64 (Graviton, cheaper) or X86_64. Images must be built for it. | `string` | `"ARM64"` |
| `container_insights` | ECS Container Insights: enabled, enhanced or disabled. | `string` | `"enabled"` |
| `api_cpu` | Fargate CPU units per api task. | `number` | `1024` |
| `api_memory` | Fargate memory (MiB) per api task. | `number` | `2048` |
| `api_min_count` | Minimum (and initial) api task count. | `number` | `2` |
| `api_max_count` | Maximum api task count under autoscaling. Equal to api_min_count disables scaling. | `number` | `6` |
| `api_ephemeral_gib` | Fargate ephemeral storage (GiB, 21 to 200) per api task; dataset uploads are spooled there before they go to S3. Null: the Fargate default of 20 GiB. | `number` | `null` |
| `worker_cpu` | Fargate CPU units for the worker. | `number` | `1024` |
| `worker_memory` | Fargate memory (MiB) for the worker. DuckDB runs the checks in it: keep it above DUCKDB_MEMORY_LIMIT (default 2GB). | `number` | `4096` |
| `worker_ephemeral_gib` | Fargate ephemeral storage (GiB, 21 to 200) per worker task. Files and source extracts are spooled under WORK_DIR during a scan. | `number` | `50` |
| `worker_count` | Scan worker task count. Several are safe (scans are claimed with SKIP LOCKED and leased); not autoscaled, and deploys replace tasks rather than double them. | `number` | `1` |
| `web_cpu` | Fargate CPU units per web task. | `number` | `512` |
| `web_memory` | Fargate memory (MiB) per web task. | `number` | `1024` |
| `web_min_count` | Minimum (and initial) web task count. | `number` | `1` |
| `web_max_count` | Maximum web task count under autoscaling. | `number` | `3` |
| `cpu_target_percent` | Average CPU the autoscaler aims for (api and web). | `number` | `60` |
| `idle_timeout` | Load balancer idle timeout in seconds. Bounds how long a stalled connection (an upload that stopped sending) is kept. | `number` | `120` |
| `deletion_protection` | Block accidental deletion of the load balancer. | `bool` | `true` |
| `access_logs_bucket` | Existing bucket for load balancer access logs (needs the ELB log-delivery bucket policy). Null disables. | `string` | `null` |
| `metrics_allowed_cidrs` | Source CIDRs allowed to read /metrics through the load balancer. Empty: /metrics answers 404 at the edge. | `list(string)` | `[]` |
| `enable_waf` | Attach a WAF web ACL (managed rule sets plus a per-IP flood guard) to the load balancer. | `bool` | `true` |
| `waf_rate_limit_per_5min` | Requests per source IP per 5 minutes before WAF blocks. Keep it high: SDK backends often sit behind one NAT address. | `number` | `20000` |
| `waf_log_retention_days` | WAF log retention. | `number` | `30` |
| `source_cidrs` | Destinations the api (connection tests) and the worker (scans) may reach on source_ports: your source databases. Default: anywhere. Restrict it to your database networks wherever you can. | `list(string)` | `["0.0.0.0/0"]` |
| `source_ports` | Ports of the source databases and REST sources (HTTPS 443, PostgreSQL 5432, MySQL 3306, SQL Server 1433 by default). | `list(number)` | `[443, 5432, 3306, 1433]` |
| `ai_egress` | Extra egress from the api tasks for a self-hosted AI model not on HTTPS 443, as { cidr, port } pairs (for example Ollama or vLLM inside the VPC). Empty: HTTPS only. | `list(object)` | `[]` |
| `send_mail` | Attach mail_policy_json to the api and worker task roles (alert mail through SES). | `bool` | `false` |
| `mail_policy_json` | IAM policy for sending alert mail (email module send_policy_json), with send_mail. | `string` | `null` |

## Outputs

| Name | Description |
|---|---|
| `cluster_name` | ECS cluster name. |
| `cluster_arn` | ECS cluster ARN. |
| `url` | Public URL of the dashboard and API. |
| `internal_urls` | Private service URLs through Cloud Map: { api }. The web app uses it as API_INTERNAL_URL. |
| `alb_dns_name` | Load balancer DNS name (CNAME target for the host name when the zone is not in Route53). |
| `alb_arn_suffix` | Load balancer ARN suffix, for CloudWatch metrics. |
| `services` | Load-balanced services: { api, web } => { service_name, target_group_arn_suffix }. |
| `service_names` | Every ECS service name (api, worker, web). |
| `security_group_ids` | Task security group per app. |
| `task_role_arns` | Task role per app. |
| `run_task` | Parameters for one-off tasks: `dataquality migrate` (task_definition, the default), or `create-admin` and `seed-demo` as command overrides on the same definition. |
| `namespace_id` | Cloud Map private DNS namespace (api.<name_prefix>.internal resolves through it). |
