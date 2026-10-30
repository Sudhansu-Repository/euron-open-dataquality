variable "endpoint" {
  description = "Emulator endpoint. http://floci:4566 inside compose, http://localhost:4966 from the host."
  type        = string
  default     = "http://localhost:4966"
}

variable "name_prefix" {
  description = "Must match OBJECTS_BUCKET (<name_prefix>-objects) and KMS_KEY_ID (alias/<name_prefix>) in deploy/compose/compose.floci.yaml."
  type        = string
  default     = "dataquality-local"
}

variable "cors_origins" {
  description = "App origins allowed to fetch objects with JavaScript."
  type        = list(string)
  default     = ["http://localhost:4910", "http://127.0.0.1:4910"]
}

variable "mail_domain" {
  description = "SES domain identity created in the emulator."
  type        = string
  default     = "dataquality.local"
}
