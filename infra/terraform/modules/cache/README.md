# `cache` module

ElastiCache (Valkey by default) holding dashboard caches and rate limit counters. Nothing here is the only copy of anything: the scan queue lives in Postgres.

- `maxmemory-policy` is `allkeys-lru` by default: a full node evicts old cache entries instead of refusing writes; the memory alarm in the observability module warns first.
- Private subnets, TLS in transit, AUTH token in Secrets Manager, encrypted at rest with the CMK, slow log to CloudWatch, automatic failover with two or more nodes.

## Inputs

| Name | Description | Type | Default |
|---|---|---|---|
| `name_prefix` | Prefix for every resource name. | `string` | required |
| `vpc_id` | VPC id. | `string` | required |
| `subnet_ids` | Private subnets for the cache subnet group (2+ AZs for failover). | `list(string)` | required |
| `kms_key_arn` | CMK for data at rest and for the AUTH token secret. | `string` | required |
| `logs_kms_key_arn` | CMK for the slow-log group. Null uses CloudWatch's default encryption. | `string` | `null` |
| `engine` | valkey (default, cheaper) or redis. | `string` | `"valkey"` |
| `engine_version` | Engine version, e.g. 8.0 for Valkey or 7.1 for Redis OSS. | `string` | `"8.0"` |
| `parameter_group_family` | Parameter group family matching engine and engine_version, e.g. valkey8 or redis7. | `string` | `"valkey8"` |
| `maxmemory_policy` | Eviction policy. allkeys-lru: everything here is a cache or a rate limit counter, so evicting old keys is safe; the scan queue lives in Postgres. | `string` | `"allkeys-lru"` |
| `node_type` | Node type. Graviton (t4g/m7g/r7g) recommended. | `string` | `"cache.t4g.small"` |
| `num_cache_clusters` | Nodes in the replication group: 1 (no failover) or 2+ (primary plus replicas, Multi-AZ failover). | `number` | `2` |
| `snapshot_retention_days` | Daily snapshots kept (0 disables). Counters rehydrate from Postgres, so snapshots only speed up recovery. | `number` | `1` |
| `recovery_window_in_days` | Days a deleted AUTH token secret stays recoverable. 0 deletes immediately. | `number` | `30` |
| `log_retention_days` | Slow-log retention in CloudWatch Logs. | `number` | `30` |
| `apply_immediately` | Apply modifications now instead of in the maintenance window. | `bool` | `false` |

## Outputs

| Name | Description |
|---|---|
| `primary_endpoint_address` | Primary endpoint hostname. |
| `replication_group_id` | Replication group id (CloudWatch dimension prefix). |
| `member_clusters` | Node ids (CloudWatch CacheClusterId dimension). |
| `security_group_id` | Cache security group; consumers add ingress rules against it. |
| `auth_secret_arn` | Secrets Manager secret holding AUTH_TOKEN and REDIS_URL. |
| `connection_url` | REDIS_URL for the API (rediss://, TLS + AUTH). Pass it to the secrets module, never to plain task environment. |
