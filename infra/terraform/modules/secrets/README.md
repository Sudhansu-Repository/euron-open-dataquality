# `secrets` module

Secrets Manager entries, injected by ECS into the api, scan worker and migrate containers:

- `<name_prefix>/app`: `SESSION_SECRET`, `API_KEY_PEPPER` (api, scan worker, migrate).
- `<name_prefix>/connections` (with `include_connection_urls`): `DATABASE_URL`, `REDIS_URL`.

Values are generated once and rotated out of band; Terraform never rolls them back (`ignore_changes`).

## Inputs

| Name | Description | Type | Default |
|---|---|---|---|
| `name_prefix` | Prefix for every resource name. | `string` | required |
| `kms_key_arn` | CMK that encrypts the secrets. Null uses the AWS-managed key. | `string` | `null` |
| `recovery_window_in_days` | Days a deleted secret stays recoverable. 0 deletes immediately (local and throwaway environments). | `number` | `30` |
| `include_connection_urls` | Create the connections secret from database_url and redis_url. false where Compose supplies them (local-floci). | `bool` | `false` |
| `database_url` | DATABASE_URL (database module connection_url), with include_connection_urls. | `string` | `null` |
| `redis_url` | REDIS_URL (cache module connection_url), with include_connection_urls. | `string` | `null` |

## Outputs

| Name | Description |
|---|---|
| `secret_arn` | ARN of the JSON secret holding SESSION_SECRET and API_KEY_PEPPER. |
| `connections_secret_arn` | ARN of the JSON secret holding DATABASE_URL and REDIS_URL (null without include_connection_urls). |
| `keys` | Every environment variable the secrets provide. |
| `ecs_secrets` | ECS `secrets` entries for the api, the scan worker and the migrate task: [{ name, valueFrom = "<arn>:<key>::" }]. |
