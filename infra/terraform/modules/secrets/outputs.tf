output "secret_arn" {
  description = "ARN of the JSON secret holding SESSION_SECRET and API_KEY_PEPPER."
  value       = aws_secretsmanager_secret.app.arn
}

output "connections_secret_arn" {
  description = "ARN of the JSON secret holding DATABASE_URL and REDIS_URL (null without include_connection_urls)."
  value       = var.include_connection_urls ? aws_secretsmanager_secret.connections[0].arn : null
}

output "keys" {
  description = "Every environment variable the secrets provide."
  value       = sort(concat(local.app_keys, local.connection_keys))
}

output "ecs_secrets" {
  description = "ECS `secrets` entries for the api, the scan worker and the migrate task: [{ name, valueFrom = \"<arn>:<key>::\" }]."
  value       = local.ecs_secrets
}
