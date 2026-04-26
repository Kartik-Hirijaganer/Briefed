/*
 * Route 53 — hosted zone + alias records pointing to the CloudFront dist.
 *
 * Optional: plan §19.15 notes Cloudflare DNS is a viable $0 alternative.
 * When `create_hosted_zone = false`, pass in an externally-managed zone_id.
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

variable "zone_name" {
  description = "Root domain (e.g. briefed.example)."
  type        = string
}

variable "create_hosted_zone" {
  type    = bool
  default = true
}

variable "existing_zone_id" {
  type    = string
  default = null
}

variable "app_hostname" {
  description = "Fully-qualified hostname for the PWA + API (e.g. app.briefed.example)."
  type        = string
}

variable "cloudfront_domain" {
  description = "aws_cloudfront_distribution.this.domain_name"
  type        = string
}

variable "tags" {
  type    = map(string)
  default = {}
}

resource "aws_route53_zone" "this" {
  count = var.create_hosted_zone ? 1 : 0
  name  = var.zone_name
  tags  = var.tags
}

locals {
  zone_id = var.create_hosted_zone ? aws_route53_zone.this[0].zone_id : var.existing_zone_id
  # CloudFront's fixed hosted zone id (same in every AWS region).
  cloudfront_zone_id = "Z2FDTNDATAQYW2"
}

resource "aws_route53_record" "app" {
  zone_id = local.zone_id
  name    = var.app_hostname
  type    = "A"
  alias {
    name                   = var.cloudfront_domain
    zone_id                = local.cloudfront_zone_id
    evaluate_target_health = false
  }
}

output "zone_id" {
  value = local.zone_id
}
