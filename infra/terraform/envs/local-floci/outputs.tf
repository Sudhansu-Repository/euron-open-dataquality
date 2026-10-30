output "objects_bucket" {
  description = "OBJECTS_BUCKET for the local stack."
  value       = module.storage.bucket_name
}

output "kms_key_alias" {
  description = "KMS_KEY_ID for the local stack."
  value       = module.kms.alias_name
}

output "app_secret_arn" {
  description = "The emulated Secrets Manager secret (SESSION_SECRET, API_KEY_PEPPER)."
  value       = module.secrets.secret_arn
}

output "mail_identity" {
  description = "ARN of the emulated SES domain identity (MAIL_BACKEND=ses would send from it)."
  value       = module.email.identity_arn
}
