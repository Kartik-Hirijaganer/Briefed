/*
 * Three S3 buckets per plan §19.15:
 *   raw-email   — optional mirror of Gmail MIME bodies (encryption on)
 *   digests     — rendered digest HTML/Markdown
 *   backups     — pg_dump snapshots (ciphertext only; see §20.10)
 *
 * Lifecycle rules are enabled at the bucket level; block-public-access is
 * enforced; versioning on for backups (recovery window) + digests.
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
  type = string
}

variable "tags" {
  type    = map(string)
  default = {}
}

locals {
  buckets = {
    raw_email = { purpose = "raw-email", versioning = false, expire_days = 30 }
    digests   = { purpose = "digests", versioning = true, expire_days = 365 }
    backups   = { purpose = "backups", versioning = true, expire_days = 180 }
  }
}

resource "aws_s3_bucket" "this" {
  for_each = local.buckets
  bucket   = "${var.name_prefix}-${each.value.purpose}"
  tags     = var.tags
}

resource "aws_s3_bucket_public_access_block" "this" {
  for_each                = aws_s3_bucket.this
  bucket                  = each.value.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "this" {
  for_each = aws_s3_bucket.this
  bucket   = each.value.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_versioning" "this" {
  for_each = local.buckets
  bucket   = aws_s3_bucket.this[each.key].id
  versioning_configuration {
    status = each.value.versioning ? "Enabled" : "Disabled"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "this" {
  for_each = local.buckets
  bucket   = aws_s3_bucket.this[each.key].id

  rule {
    id     = "expire"
    status = "Enabled"
    filter {}
    expiration {
      days = each.value.expire_days
    }
    noncurrent_version_expiration {
      noncurrent_days = 30
    }
  }
}

output "bucket_names" {
  value = { for k, b in aws_s3_bucket.this : k => b.bucket }
}

output "bucket_arns" {
  value = { for k, b in aws_s3_bucket.this : k => b.arn }
}
