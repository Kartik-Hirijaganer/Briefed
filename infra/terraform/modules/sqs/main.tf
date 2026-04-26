/*
 * Per-stage SQS queues + shared DLQ.
 *
 * Queues per plan §19.15:
 *   ingest, classify, summarize, jobs, unsubscribe, digest, maintenance
 * Plus one DLQ that every queue redrives to after `max_receive_count` fails.
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
  description = "Prefix for queue names (e.g. 'briefed-dev')."
  type        = string
}

variable "max_receive_count" {
  type    = number
  default = 5
}

variable "visibility_timeout_seconds" {
  description = "Must be >= worker Lambda timeout. Workers run up to 900s."
  type        = number
  default     = 900
}

variable "tags" {
  type    = map(string)
  default = {}
}

locals {
  stages = [
    "ingest",
    "classify",
    "summarize",
    "jobs",
    "unsubscribe",
    "digest",
    "maintenance",
  ]
}

resource "aws_sqs_queue" "dlq" {
  name                      = "${var.name_prefix}-dlq"
  message_retention_seconds = 1209600 # 14 days
  tags                      = var.tags
}

resource "aws_sqs_queue" "stage" {
  for_each                   = toset(local.stages)
  name                       = "${var.name_prefix}-${each.key}"
  visibility_timeout_seconds = var.visibility_timeout_seconds
  message_retention_seconds  = 345600 # 4 days
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq.arn
    maxReceiveCount     = var.max_receive_count
  })
  tags = var.tags
}

output "dlq_arn" {
  value = aws_sqs_queue.dlq.arn
}

output "dlq_name" {
  value       = aws_sqs_queue.dlq.name
  description = "DLQ queue name (used by CloudWatch SQS alarm dimensions)."
}

output "queue_arns" {
  value       = { for k, q in aws_sqs_queue.stage : k => q.arn }
  description = "Map stage → queue ARN. Used by worker Lambda event source mappings."
}

output "queue_urls" {
  value = { for k, q in aws_sqs_queue.stage : k => q.url }
}
