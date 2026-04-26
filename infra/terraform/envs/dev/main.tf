/*
 * dev environment — composes the Briefed modules into a deployable stack.
 *
 * Intentionally minimal; prod/ is a near-copy with stricter retention +
 * custom domain wired in. A backend.tf (NOT committed with real bucket /
 * table names) configures S3 + DynamoDB state per environment.
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

provider "aws" {
  region              = var.region
  allowed_account_ids = ["970385384114"]
}

provider "aws" {
  alias               = "us_east_1"
  region              = "us-east-1"
  allowed_account_ids = ["970385384114"]
}

variable "region" {
  type    = string
  default = "us-east-1"
}

variable "name_prefix" {
  type    = string
  default = "briefed-dev"
}

variable "image_uri" {
  description = "ECR URI for the app container image (tag = git sha)."
  type        = string
}

variable "domain_name" {
  description = "Optional custom domain. Empty string = CloudFront default only."
  type        = string
  default     = ""
}

variable "alarm_email" {
  description = "Email to subscribe to the Phase 8 SNS alarm topic. Empty = manual subscription."
  type        = string
  default     = ""
}

locals {
  tags = {
    "briefed:env"     = "dev"
    "briefed:managed" = "terraform"
  }
}

module "kms" {
  source      = "../../modules/kms"
  name_prefix = var.name_prefix
  tags        = local.tags
}

module "ssm" {
  source = "../../modules/ssm"
  env    = "dev"
  tags   = local.tags
}

module "sqs" {
  source      = "../../modules/sqs"
  name_prefix = var.name_prefix
  tags        = local.tags
}

module "s3" {
  source      = "../../modules/s3"
  name_prefix = var.name_prefix
  tags        = local.tags
}

module "api" {
  source               = "../../modules/lambda-api"
  name                 = "${var.name_prefix}-api"
  image_uri            = var.image_uri
  ssm_parameter_prefix = module.ssm.parameter_prefix
  kms_key_arns         = [module.kms.token_wrap_key_arn, module.kms.content_key_arn]
  sqs_queue_arns       = values(module.sqs.queue_arns)
  tags                 = local.tags
  env_vars = {
    BRIEFED_ENV                  = "dev"
    BRIEFED_SSM_PREFIX           = module.ssm.parameter_prefix
    BRIEFED_TOKEN_WRAP_KEY_ALIAS = module.kms.token_wrap_alias
    BRIEFED_CONTENT_KEY_ALIAS    = module.kms.content_alias
  }
}

module "worker" {
  source               = "../../modules/lambda-worker"
  name                 = "${var.name_prefix}-worker"
  image_uri            = var.image_uri
  queue_arns           = module.sqs.queue_arns
  ssm_parameter_prefix = module.ssm.parameter_prefix
  kms_key_arns         = [module.kms.token_wrap_key_arn, module.kms.content_key_arn]
  s3_bucket_arns       = values(module.s3.bucket_arns)
  tags                 = local.tags
  env_vars = {
    BRIEFED_ENV                   = "dev"
    BRIEFED_SSM_PREFIX            = module.ssm.parameter_prefix
    BRIEFED_TOKEN_WRAP_KEY_ALIAS  = module.kms.token_wrap_alias
    BRIEFED_CONTENT_KEY_ALIAS     = module.kms.content_alias
    BRIEFED_CLASSIFY_QUEUE_URL    = module.sqs.queue_urls["classify"]
    BRIEFED_SUMMARIZE_QUEUE_URL   = module.sqs.queue_urls["summarize"]
    BRIEFED_JOBS_QUEUE_URL        = module.sqs.queue_urls["jobs"]
    BRIEFED_UNSUBSCRIBE_QUEUE_URL = module.sqs.queue_urls["unsubscribe"]
    BRIEFED_RAW_EMAIL_BUCKET      = module.s3.bucket_names["raw_email"]
    BRIEFED_STORE_RAW_MIME        = "0"
  }
}

module "fanout" {
  source               = "../../modules/lambda-fanout"
  name                 = "${var.name_prefix}-fanout"
  image_uri            = var.image_uri
  ingest_queue_arn     = module.sqs.queue_arns["ingest"]
  ssm_parameter_prefix = module.ssm.parameter_prefix
  kms_key_arns         = [module.kms.token_wrap_key_arn]
  tags                 = local.tags
  env_vars = {
    BRIEFED_ENV              = "dev"
    BRIEFED_SSM_PREFIX       = module.ssm.parameter_prefix
    BRIEFED_INGEST_QUEUE_URL = module.sqs.queue_urls["ingest"]
  }
}

# PWA bucket — separate from the three business buckets so CloudFront OAC
# can target it without granting the app role write access to the dist.
resource "aws_s3_bucket" "pwa" {
  bucket = "${var.name_prefix}-pwa"
  tags   = local.tags
}

resource "aws_s3_bucket_public_access_block" "pwa" {
  bucket                  = aws_s3_bucket.pwa.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

module "cloudfront" {
  source                   = "../../modules/cloudfront"
  name                     = "${var.name_prefix}-cdn"
  pwa_bucket_domain_name   = aws_s3_bucket.pwa.bucket_regional_domain_name
  lambda_function_url_host = replace(replace(module.api.function_url, "https://", ""), "/", "")
  aliases                  = var.domain_name == "" ? [] : [var.domain_name]
  acm_certificate_arn      = null
  tags                     = local.tags
}

# Bucket policy granting CloudFront's OAC read access to the PWA
# assets. See envs/prod/main.tf for full rationale.
data "aws_caller_identity" "current" {}

resource "aws_s3_bucket_policy" "pwa" {
  bucket = aws_s3_bucket.pwa.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "AllowCloudFrontServicePrincipalReadOnly"
      Effect    = "Allow"
      Principal = { Service = "cloudfront.amazonaws.com" }
      Action    = "s3:GetObject"
      Resource  = "${aws_s3_bucket.pwa.arn}/*"
      Condition = {
        StringEquals = {
          "AWS:SourceArn" = "arn:aws:cloudfront::${data.aws_caller_identity.current.account_id}:distribution/${module.cloudfront.distribution_id}"
        }
      }
    }]
  })
}

# Phase 8 — observability + alarms (plan §14, §20.10).
module "alarms" {
  source          = "../../modules/alarms"
  name_prefix     = var.name_prefix
  alarm_email     = var.alarm_email
  dlq_arn         = module.sqs.dlq_arn
  dlq_name        = module.sqs.dlq_name
  content_cmk_arn = module.kms.content_key_arn
  lambda_function_names = {
    api    = module.api.function_name
    worker = module.worker.function_name
    fanout = module.fanout.function_name
  }
  log_group_names = {
    api    = "/aws/lambda/${module.api.function_name}"
    worker = "/aws/lambda/${module.worker.function_name}"
    fanout = "/aws/lambda/${module.fanout.function_name}"
  }
  tags = local.tags
}

output "function_url" {
  value = module.api.function_url
}

output "cloudfront_domain" {
  value = module.cloudfront.distribution_domain
}

output "pwa_bucket" {
  value = aws_s3_bucket.pwa.bucket
}

output "alarm_topic_arn" {
  value = module.alarms.alarm_topic_arn
}

output "dashboard_name" {
  value = module.alarms.dashboard_name
}
