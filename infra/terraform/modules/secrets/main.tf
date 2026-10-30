# DataQuality's secrets, in Secrets Manager. ECS injects each JSON key into the containers
# that need it as an environment variable; the values never appear in a task definition,
# a plan diff or a log.
#
# Two secrets with different lifecycles:
#
#   <name_prefix>/app          SESSION_SECRET, API_KEY_PEPPER. Read by the api, the scan
#                              worker and the migrate task.
#   <name_prefix>/connections  DATABASE_URL, REDIS_URL. Derived from the database and
#                              cache modules and kept in step with them on every apply.
#
# Generated once, then rotated out of band; Terraform never rolls them back. The values
# are distinct on purpose (the API refuses to boot in production if any two are equal).
# Locally (Compose) the same values come from deploy/compose/.env; on AWS no master key is
# needed because connection credentials are sealed with KMS (KEY_MODE=kms).
locals {
  app_keys        = ["API_KEY_PEPPER", "SESSION_SECRET"]
  connection_keys = var.include_connection_urls ? ["DATABASE_URL", "REDIS_URL"] : []
}

resource "random_password" "this" {
  for_each = toset(local.app_keys)
  length   = 64
  special  = false
}

resource "aws_secretsmanager_secret" "app" {
  #checkov:skip=CKV2_AWS_57:These are HMAC keys; rotation is an operator procedure (docs/guides/operations.md), not a Lambda.
  name                    = "${var.name_prefix}/app"
  description             = "DataQuality signing secrets (sessions, API key pepper)"
  kms_key_id              = var.kms_key_arn
  recovery_window_in_days = var.recovery_window_in_days
}

resource "aws_secretsmanager_secret_version" "app" {
  secret_id     = aws_secretsmanager_secret.app.id
  secret_string = jsonencode({ for k in local.app_keys : k => random_password.this[k].result })

  # Rotation happens out of band (put a new version by hand or by pipeline). Without
  # this, the next `terraform apply` would quietly roll every secret back.
  lifecycle {
    ignore_changes = [secret_string]
  }
}

resource "aws_secretsmanager_secret" "connections" {
  #checkov:skip=CKV2_AWS_57:Derived values; they change when the database or cache module rotates its credential.
  count                   = var.include_connection_urls ? 1 : 0
  name                    = "${var.name_prefix}/connections"
  description             = "DataQuality connection URLs (PostgreSQL, Redis/Valkey)"
  kms_key_id              = var.kms_key_arn
  recovery_window_in_days = var.recovery_window_in_days
}

resource "aws_secretsmanager_secret_version" "connections" {
  count     = var.include_connection_urls ? 1 : 0
  secret_id = aws_secretsmanager_secret.connections[0].id
  secret_string = jsonencode({
    DATABASE_URL = var.database_url
    REDIS_URL    = var.redis_url
  })
}

locals {
  # api, worker and migrate all read the same set.
  ecs_secrets = concat(
    [for k in local.app_keys : { name = k, valueFrom = "${aws_secretsmanager_secret.app.arn}:${k}::" }],
    [for k in local.connection_keys : { name = k, valueFrom = "${aws_secretsmanager_secret.connections[0].arn}:${k}::" }],
  )
}
