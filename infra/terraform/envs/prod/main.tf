/*
 * prod environment — composes the Briefed modules into the production
 * stack. Plan §13 + §14 Phase 9: blue/green deploys via the Lambda
 * ``live`` alias; rollback = ``aws lambda update-alias --function-version
 * <previous>`` against api + worker + fanout.
 *
 * Diffs from dev (envs/dev/main.tf) are intentionally small — same
 * module graph, stricter retention + alarms, custom domain wired in
 * once ACM is approved.
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
  default = "briefed-prod"
}

variable "image_uri" {
  description = "ECR URI for the app container image (tag = git sha)."
  type        = string
}

variable "function_url_auth_mode" {
  type    = string
  default = "AWS_IAM"
}

variable "public_base_url" {
  description = "Browser-facing app origin used for OAuth callback URLs."
  type        = string
  default     = "https://briefed-six.vercel.app"
}

variable "domain_name" {
  description = "Custom domain (e.g. app.briefed.example). Empty string = CloudFront default only."
  type        = string
  default     = ""
}

variable "alarm_email" {
  description = "Email to subscribe to the SNS alarm topic. Empty = manual subscription."
  type        = string
  default     = ""
}

locals {
  tags = {
    "briefed:env"     = "prod"
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
  env    = "prod"
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
  source                 = "../../modules/lambda-api"
  name                   = "${var.name_prefix}-api"
  image_uri              = var.image_uri
  function_url_auth_mode = var.function_url_auth_mode
  ssm_parameter_prefix   = module.ssm.parameter_prefix
  kms_key_arns           = [module.kms.token_wrap_key_arn, module.kms.content_key_arn]
  sqs_queue_arns         = values(module.sqs.queue_arns)
  tags                   = local.tags
  env_vars = {
    BRIEFED_ENV                  = "prod"
    BRIEFED_INGEST_QUEUE_URL     = module.sqs.queue_urls["ingest"]
    BRIEFED_PUBLIC_BASE_URL      = var.public_base_url
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
    BRIEFED_ENV                   = "prod"
    BRIEFED_SSM_PREFIX            = module.ssm.parameter_prefix
    BRIEFED_TOKEN_WRAP_KEY_ALIAS  = module.kms.token_wrap_alias
    BRIEFED_CONTENT_KEY_ALIAS     = module.kms.content_alias
    BRIEFED_CLASSIFY_QUEUE_URL    = module.sqs.queue_urls["classify"]
    BRIEFED_SUMMARIZE_QUEUE_URL   = module.sqs.queue_urls["summarize"]
    BRIEFED_UNSUBSCRIBE_QUEUE_URL = module.sqs.queue_urls["unsubscribe"]
    BRIEFED_RAW_EMAIL_BUCKET      = module.s3.bucket_names["raw_email"]
    BRIEFED_STORE_RAW_MIME        = "1"
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
    BRIEFED_ENV              = "prod"
    BRIEFED_SSM_PREFIX       = module.ssm.parameter_prefix
    BRIEFED_INGEST_QUEUE_URL = module.sqs.queue_urls["ingest"]
  }
}

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

resource "aws_wafv2_web_acl" "cdn" {
  provider = aws.us_east_1

  name  = "${var.name_prefix}-cdn-acl"
  scope = "CLOUDFRONT"

  default_action {
    allow {}
  }

  rule {
    name     = "rate-limit"
    priority = 1

    action {
      block {}
    }

    statement {
      rate_based_statement {
        limit              = 2000
        aggregate_key_type = "IP"
      }
    }

    visibility_config {
      sampled_requests_enabled   = true
      cloudwatch_metrics_enabled = true
      metric_name                = "rate-limit"
    }
  }

  rule {
    name     = "aws-common"
    priority = 2

    override_action {
      count {}
    }

    statement {
      managed_rule_group_statement {
        vendor_name = "AWS"
        name        = "AWSManagedRulesCommonRuleSet"
      }
    }

    visibility_config {
      sampled_requests_enabled   = true
      cloudwatch_metrics_enabled = true
      metric_name                = "aws-common"
    }
  }

  visibility_config {
    sampled_requests_enabled   = true
    cloudwatch_metrics_enabled = true
    metric_name                = "${var.name_prefix}-cdn-acl"
  }

  tags = local.tags
}

module "cloudfront" {
  source                   = "../../modules/cloudfront"
  name                     = "${var.name_prefix}-cdn"
  pwa_bucket_domain_name   = aws_s3_bucket.pwa.bucket_regional_domain_name
  lambda_function_url_host = replace(replace(module.api.function_url, "https://", ""), "/", "")
  aliases                  = var.domain_name == "" ? [] : [var.domain_name]
  acm_certificate_arn      = null
  web_acl_arn              = aws_wafv2_web_acl.cdn.arn
  tags                     = local.tags
}

# Bucket policy granting the CloudFront distribution's OAC read access
# to the PWA assets. Without this, OAC requests are denied at S3 and
# the PWA returns AccessDenied. Must reference the distribution ARN
# in the SourceArn condition so other CloudFront distributions in the
# account cannot piggyback on the same bucket.
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

# AWS (Oct 2025+) requires BOTH actions on a function URL, and the CloudFront OAC
# guide shows two add-permission calls for the cloudfront.amazonaws.com principal.
# source_arn (= this distribution) scopes both grants. See §2.
resource "aws_lambda_permission" "cloudfront_invoke_url" {
  statement_id           = "AllowCloudFrontInvokeFunctionUrl"
  action                 = "lambda:InvokeFunctionUrl"
  function_name          = module.api.function_name
  qualifier              = module.api.alias_name
  principal              = "cloudfront.amazonaws.com"
  function_url_auth_type = "AWS_IAM"
  source_arn             = "arn:aws:cloudfront::${data.aws_caller_identity.current.account_id}:distribution/${module.cloudfront.distribution_id}"
}

resource "aws_lambda_permission" "cloudfront_invoke_function" {
  statement_id  = "AllowCloudFrontInvokeFunction"
  action        = "lambda:InvokeFunction"
  function_name = module.api.function_name
  qualifier     = module.api.alias_name
  principal     = "cloudfront.amazonaws.com"
  source_arn    = "arn:aws:cloudfront::${data.aws_caller_identity.current.account_id}:distribution/${module.cloudfront.distribution_id}"
}

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
  description = "API Lambda Function URL; kept for reference/debugging and not directly callable without SigV4 signing once AWS_IAM is enabled."
  value       = module.api.function_url
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

output "api_function_name" {
  description = "Lambda function name behind the live alias — used by deploy-prod for blue/green alias swings + rollback."
  value       = module.api.function_name
}

output "worker_function_name" {
  value = module.worker.function_name
}

output "fanout_function_name" {
  value = module.fanout.function_name
}
