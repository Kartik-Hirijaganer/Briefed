/*
 * KMS CMKs for Briefed.
 *
 * Two keys, not one:
 *   - token_wrap  (alias/${name_prefix}-token-wrap)
 *   - content    (alias/${name_prefix}-content-encrypt)
 *
 * Reasoning in ADR 0008 + plan §20.10: independent revocation surfaces,
 * independent rotation cadence, independent CloudTrail alarms.
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

variable "name_prefix" {
  description = "Prefix for KMS alias names (e.g. 'briefed-dev')."
  type        = string
}

variable "tags" {
  description = "Tags applied to every key."
  type        = map(string)
  default     = {}
}

resource "aws_kms_key" "token_wrap" {
  description             = "Briefed OAuth token-wrap CMK (ADR 0008)"
  deletion_window_in_days = 30
  enable_key_rotation     = true
  tags                    = merge(var.tags, { "briefed:purpose" = "token-wrap" })
}

resource "aws_kms_alias" "token_wrap" {
  name          = "alias/${var.name_prefix}-token-wrap"
  target_key_id = aws_kms_key.token_wrap.key_id
}

resource "aws_kms_key" "content" {
  description             = "Briefed content-at-rest CMK (plan §20.10)"
  deletion_window_in_days = 30
  enable_key_rotation     = true
  tags                    = merge(var.tags, { "briefed:purpose" = "content-encrypt" })
}

resource "aws_kms_alias" "content" {
  name          = "alias/${var.name_prefix}-content-encrypt"
  target_key_id = aws_kms_key.content.key_id
}

output "token_wrap_key_arn" {
  value       = aws_kms_key.token_wrap.arn
  description = "ARN of the OAuth token-wrap CMK; grant kms:Encrypt+Decrypt to the app role."
}

output "content_key_arn" {
  value       = aws_kms_key.content.arn
  description = "ARN of the content-at-rest CMK; grant kms:Encrypt+Decrypt to the app role."
}

output "token_wrap_alias" {
  value = aws_kms_alias.token_wrap.name
}

output "content_alias" {
  value = aws_kms_alias.content.name
}
