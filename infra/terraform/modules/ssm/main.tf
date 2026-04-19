/*
 * SSM Parameter Store placeholders.
 *
 * Creates the parameter *names* and marks them as SecureString, but
 * does NOT commit actual secret values — those are set out-of-band via
 * `aws ssm put-parameter --overwrite` after bootstrap. Terraform only
 * owns the name + type so we can import values into Lambda roles.
 *
 * Parameters per plan §19.15:
 *   anthropic_api_key, gemini_api_key, supabase_url,
 *   supabase_service_key, google_oauth_client_secret,
 *   session_signing_key, vapid_private_key.
 */

terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.50"
    }
  }
}

variable "env" {
  description = "Environment slug (e.g. 'dev', 'prod')."
  type        = string
}

variable "tags" {
  type    = map(string)
  default = {}
}

locals {
  parameter_names = [
    "anthropic_api_key",
    "gemini_api_key",
    "supabase_url",
    "supabase_service_key",
    "supabase_db_url",
    "google_oauth_client_id",
    "google_oauth_client_secret",
    "session_signing_key",
    "vapid_private_key",
  ]
}

resource "aws_ssm_parameter" "secret" {
  for_each = toset(local.parameter_names)
  name     = "/briefed/${var.env}/${each.key}"
  type     = "SecureString"
  value    = "PLACEHOLDER — set via aws ssm put-parameter --overwrite"
  tags     = var.tags

  lifecycle {
    # Do not drift on value changes made out-of-band.
    ignore_changes = [value]
  }
}

output "parameter_arns" {
  value       = [for p in aws_ssm_parameter.secret : p.arn]
  description = "All secret parameter ARNs; grant ssm:GetParameter to the app role."
}

output "parameter_prefix" {
  value = "/briefed/${var.env}/"
}
