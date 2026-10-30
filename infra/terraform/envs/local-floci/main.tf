# ─────────────────────────────────────────────────────────────────────────────
# Local environment on the Floci AWS emulator.
#
# The modules that build production run here unchanged; only the provider endpoints
# differ. `make up` applies this automatically (the compose `terraform` one-shot)
# before migrate, api and worker start, so local development uses S3, KMS and Secrets
# Manager exactly as AWS does. By hand, against a running emulator:
#
#   terraform -chdir=infra/terraform/envs/local-floci init
#   terraform -chdir=infra/terraform/envs/local-floci apply -var endpoint=http://localhost:4966
#
# Postgres and Redis are plain Compose containers locally (the emulator does not back RDS
# or ElastiCache), and alert mail goes to Mailpit (the SES identity below is created so the
# email module is exercised, but the local app sends through SMTP). The database, cache,
# service, ecr and observability modules are exercised by aws-dev and aws-prod
# (make tf-validate, make tf-aws-on-floci).
# ─────────────────────────────────────────────────────────────────────────────

module "kms" {
  source                  = "../../modules/kms"
  name_prefix             = var.name_prefix
  deletion_window_in_days = 7
}

module "storage" {
  source        = "../../modules/storage"
  name_prefix   = var.name_prefix
  kms_key_arn   = module.kms.key_arn
  enforce_tls   = false # the emulator speaks plain HTTP
  force_destroy = true
  cors_origins  = var.cors_origins
}

# Generated secrets are an AWS-deployment concern; locally compose reads
# deploy/compose/.env (make env). Created here anyway so the module is exercised.
module "secrets" {
  source                  = "../../modules/secrets"
  name_prefix             = var.name_prefix
  kms_key_arn             = module.kms.key_arn
  recovery_window_in_days = 0
}

# The SES domain identity and configuration set, as on AWS. No Route53 zone locally, so
# the DKIM records only appear in the module output.
module "email" {
  source       = "../../modules/email"
  name_prefix  = var.name_prefix
  domain       = var.mail_domain
  from_address = "alerts@${var.mail_domain}"
}
