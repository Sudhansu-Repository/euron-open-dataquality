# `storage` module

One private S3 bucket, `<name_prefix>-objects` (`OBJECTS_BUCKET`):

- `projects/<id>/datasets/<id>/<file>`: uploaded dataset files (CSV, Parquet, JSON lines, Excel), one object per dataset version, kept as long as the version exists.
- `projects/<id>/connections/<id>.sqlite`: uploaded SQLite source databases.
- `exports/`: reserved for exported reports, expiring after `export_expiration_days` (the app streams reports today, so nothing is written here yet).
- Only the api, the scan worker and migrate may read or write the bucket.
- `backups/`: database dumps, expiring after `backup_retention_days`.

Versioning is on, and replaced or deleted versions stay recoverable for `noncurrent_retention_days`. Public access blocked, bucket-owner-enforced ownership, TLS-only bucket policy, SSE-KMS with the CMK (bucket key on). Applied in `local-floci` as `dataquality-local-objects` with `enforce_tls = false` (the emulator speaks plain HTTP) and `force_destroy = true`.

## Inputs

| Name | Description | Type | Default |
|---|---|---|---|
| `name_prefix` | Prefix for every resource name. The bucket is <name_prefix>-objects. | `string` | required |
| `kms_key_arn` | CMK for SSE-KMS. Null falls back to SSE-S3. | `string` | `null` |
| `enforce_tls` | Deny any request not made over TLS. Disable only for an emulator that speaks plain HTTP. | `bool` | `true` |
| `noncurrent_retention_days` | Days a replaced or deleted object version stays recoverable. | `number` | `30` |
| `export_expiration_days` | Days a report download (exports/) is kept. | `number` | `7` |
| `backup_retention_days` | Days a database backup (backups/) is kept. | `number` | `35` |
| `cors_origins` | Browser origins allowed to GET objects with JavaScript (the dashboard URL). Empty = no CORS configuration. | `list(string)` | `[]` |
| `force_destroy` | Allow `terraform destroy` to delete a non-empty bucket. Never in production. | `bool` | `false` |

## Outputs

| Name | Description |
|---|---|
| `bucket_name` | Objects bucket name (OBJECTS_BUCKET). |
| `bucket_arn` | Objects bucket ARN, for IAM policies. |
