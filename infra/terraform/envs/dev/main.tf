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
  region = var.region
}

provider "aws" {
  alias  = "us_east_1"
  region = "us-east-1"
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
    BRIEFED_ENV        = "dev"
    BRIEFED_SSM_PREFIX = module.ssm.parameter_prefix
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
    BRIEFED_ENV        = "dev"
    BRIEFED_SSM_PREFIX = module.ssm.parameter_prefix
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

output "function_url" {
  value = module.api.function_url
}

output "cloudfront_domain" {
  value = module.cloudfront.distribution_domain
}

output "pwa_bucket" {
  value = aws_s3_bucket.pwa.bucket
}
