variable "region" {
  description = "AWS region."
  type        = string
}

variable "environment" {
  description = "Environment tag."
  type        = string
  default     = "prod"
}

variable "extra_tags" {
  description = "Tags added to every resource."
  type        = map(string)
  default     = {}
}

variable "name_prefix" {
  description = "Prefix for every resource name (at most 24 characters); the objects bucket name derives from it, so make it globally unique (e.g. \"acme-dataquality-prod\")."
  type        = string
}

variable "hostname" {
  description = "Public host name of the app and API, e.g. dq.example.com."
  type        = string
}

variable "certificate_arn" {
  description = "ACM certificate in the same region covering hostname."
  type        = string
}

variable "route53_zone_id" {
  description = "Hosted zone for the alias record and the DKIM records. Null: create them yourself (load_balancer_dns_name and dkim_records outputs)."
  type        = string
  default     = null
}

variable "mail_domain" {
  description = "Domain alert mail is sent from (an SES domain identity), e.g. dq.example.com."
  type        = string
}

variable "mail_from_address" {
  description = "From address of alert mail, on mail_domain, e.g. alerts@dq.example.com."
  type        = string
}

variable "image_tag" {
  description = "Image tag to deploy (the git commit or a release)."
  type        = string
}

variable "alarm_email" {
  description = "Alarm notification address."
  type        = string
  default     = null
}

variable "api_extra_environment" {
  description = "Extra api/worker environment (see docs/guides/configuration.md). Never secrets."
  type        = map(string)
  default     = {}
}

variable "backup_retention_days" {
  description = "Days a database backup in the objects bucket (backups/) is kept."
  type        = number
  default     = 35
}

variable "db_instance_class" {
  description = "RDS instance class."
  type        = string
  default     = "db.t4g.medium"
}

variable "cache_node_type" {
  description = "ElastiCache node type."
  type        = string
  default     = "cache.t4g.small"
}

variable "scan_failure_threshold" {
  description = "Failed scans per 5 minutes that raise an alarm."
  type        = number
  default     = 10
}

variable "metrics_allowed_cidrs" {
  description = "Source CIDRs allowed to scrape the api's /metrics through the load balancer."
  type        = list(string)
  default     = []
}

variable "source_cidrs" {
  description = "Networks of the databases DataQuality scans (the api and worker may connect to them on 443, 5432, 3306 and 1433). Default: anywhere; restrict it to your database CIDRs."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "ai_egress" {
  description = "Extra api egress for a self-hosted AI model not on HTTPS 443, as { cidr, port } pairs."
  type = list(object({
    cidr = string
    port = number
  }))
  default = []
}
