output "url" {
  description = "Public URL (the app, with the API under /api)."
  value       = module.service.url
}

output "load_balancer_dns_name" {
  description = "CNAME target for the host name when the zone is not in Route53."
  value       = module.service.alb_dns_name
}

output "cluster_name" {
  description = "ECS cluster of the api, worker and web."
  value       = module.service.cluster_name
}

output "services" {
  description = "ECS service names."
  value       = module.service.service_names
}

output "ecr_repositories" {
  description = "Image repositories."
  value       = module.ecr.repository_urls
}

output "run_task" {
  description = "Parameters for one-off tasks (migrate, create-admin, seed-demo)."
  value       = module.service.run_task
}

output "objects_bucket" {
  description = "Objects bucket (OBJECTS_BUCKET)."
  value       = module.storage.bucket_name
}

output "kms_key_alias" {
  description = "KMS key alias (KMS_KEY_ID)."
  value       = module.kms.alias_name
}

output "dkim_records" {
  description = "DKIM CNAMEs for the mail domain (already published when route53_zone_id is set)."
  value       = module.email.dkim_records
}

output "dashboard_name" {
  description = "CloudWatch dashboard."
  value       = module.observability.dashboard_name
}
