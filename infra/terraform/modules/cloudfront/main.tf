/*
 * CloudFront — fronts both the static PWA (S3 origin) and the API Lambda
 * Function URL, with cache policies that (a) aggressively cache the PWA
 * asset tree and (b) always bypass cache for /api/* + /openapi.json.
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

variable "name" {
  type = string
}

variable "pwa_bucket_domain_name" {
  description = "Regional domain name of the S3 bucket serving the built PWA."
  type        = string
}

variable "lambda_function_url_host" {
  description = "Host portion of the API Lambda Function URL (no scheme, no path)."
  type        = string
}

variable "aliases" {
  description = "CNAMEs (e.g. app.briefed.example). Empty list = CloudFront default domain only."
  type        = list(string)
  default     = []
}

variable "acm_certificate_arn" {
  description = "ACM cert ARN (must live in us-east-1 for CloudFront). Required when aliases is non-empty."
  type        = string
  default     = null
}

variable "tags" {
  type    = map(string)
  default = {}
}

locals {
  s3_origin_id     = "pwa-s3"
  lambda_origin_id = "api-lambda"
}

resource "aws_cloudfront_origin_access_control" "pwa" {
  name                              = "${var.name}-oac"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_distribution" "this" {
  enabled         = true
  is_ipv6_enabled = true
  comment         = var.name
  aliases         = var.aliases

  origin {
    origin_id                = local.s3_origin_id
    domain_name              = var.pwa_bucket_domain_name
    origin_access_control_id = aws_cloudfront_origin_access_control.pwa.id
  }

  origin {
    origin_id   = local.lambda_origin_id
    domain_name = var.lambda_function_url_host
    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "https-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }
  }

  default_cache_behavior {
    target_origin_id       = local.s3_origin_id
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD", "OPTIONS"]
    cached_methods         = ["GET", "HEAD"]
    compress               = true
    # AWS managed CachingOptimized
    cache_policy_id = "658327ea-f89d-4fab-a63d-7e88639e58f6"
  }

  ordered_cache_behavior {
    path_pattern           = "/api/*"
    target_origin_id       = local.lambda_origin_id
    viewer_protocol_policy = "https-only"
    allowed_methods        = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
    cached_methods         = ["GET", "HEAD"]
    compress               = true
    # AWS managed CachingDisabled
    cache_policy_id = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad"
    # AWS managed AllViewerExceptHostHeader
    origin_request_policy_id = "b689b0a8-53d0-40ab-baf2-68738e2966ac"
  }

  ordered_cache_behavior {
    path_pattern             = "/openapi.json"
    target_origin_id         = local.lambda_origin_id
    viewer_protocol_policy   = "https-only"
    allowed_methods          = ["GET", "HEAD", "OPTIONS"]
    cached_methods           = ["GET", "HEAD"]
    cache_policy_id          = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad"
    origin_request_policy_id = "b689b0a8-53d0-40ab-baf2-68738e2966ac"
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = length(var.aliases) == 0
    acm_certificate_arn            = length(var.aliases) > 0 ? var.acm_certificate_arn : null
    ssl_support_method             = length(var.aliases) > 0 ? "sni-only" : null
    minimum_protocol_version       = length(var.aliases) > 0 ? "TLSv1.2_2021" : null
  }

  tags = var.tags
}

output "distribution_domain" {
  value = aws_cloudfront_distribution.this.domain_name
}

output "distribution_id" {
  value = aws_cloudfront_distribution.this.id
}
