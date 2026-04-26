/*
 * Worker Lambda — SQS event source mapping per pipeline stage.
 *
 * Same container image as the API Lambda; the handler entrypoint selects
 * the SQS dispatcher rather than Mangum. Memory + timeout are higher for
 * ingestion / summarization workloads (up to the Lambda 900 s cap).
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

variable "image_uri" {
  type = string
}

variable "queue_arns" {
  description = "Map of stage → SQS queue ARN; each becomes an event source."
  type        = map(string)
}

variable "ssm_parameter_prefix" {
  type = string
}

variable "kms_key_arns" {
  type = list(string)
}

variable "s3_bucket_arns" {
  description = "S3 bucket ARNs for raw-email / digests / backups (read+write)."
  type        = list(string)
  default     = []
}

variable "memory_mb" {
  type    = number
  default = 1536
}

variable "timeout_seconds" {
  type    = number
  default = 900
}

variable "batch_size" {
  type    = number
  default = 1
}

variable "maximum_batching_window_seconds" {
  type    = number
  default = 2
}

variable "env_vars" {
  type    = map(string)
  default = {}
}

variable "tags" {
  type    = map(string)
  default = {}
}

data "aws_iam_policy_document" "assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "this" {
  name               = "${var.name}-role"
  assume_role_policy = data.aws_iam_policy_document.assume.json
  tags               = var.tags
}

resource "aws_iam_role_policy_attachment" "basic" {
  role       = aws_iam_role.this.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

data "aws_iam_policy_document" "inline" {
  statement {
    sid       = "SqsConsume"
    actions   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes", "sqs:SendMessage"]
    resources = values(var.queue_arns)
  }
  statement {
    sid       = "SsmRead"
    actions   = ["ssm:GetParameter", "ssm:GetParameters", "ssm:GetParametersByPath"]
    resources = ["arn:aws:ssm:*:*:parameter${var.ssm_parameter_prefix}*"]
  }
  statement {
    sid       = "KmsEnvelope"
    actions   = ["kms:Decrypt", "kms:Encrypt", "kms:GenerateDataKey"]
    resources = var.kms_key_arns
  }
  dynamic "statement" {
    for_each = length(var.s3_bucket_arns) > 0 ? [1] : []
    content {
      sid     = "S3ReadWrite"
      actions = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket"]
      resources = concat(
        var.s3_bucket_arns,
        [for arn in var.s3_bucket_arns : "${arn}/*"],
      )
    }
  }
}

resource "aws_iam_role_policy" "inline" {
  name   = "${var.name}-inline"
  role   = aws_iam_role.this.id
  policy = data.aws_iam_policy_document.inline.json
}

resource "aws_lambda_function" "this" {
  function_name = var.name
  role          = aws_iam_role.this.arn
  package_type  = "Image"
  image_uri     = var.image_uri
  publish       = true
  memory_size   = var.memory_mb
  timeout       = var.timeout_seconds
  architectures = ["x86_64"]

  # See lambda-api/main.tf for why SnapStart is intentionally omitted
  # for container-image Lambdas.

  image_config {
    command = ["app.lambda_worker.sqs_dispatcher"]
  }

  environment {
    variables = merge({ BRIEFED_RUNTIME = "lambda-worker" }, var.env_vars)
  }

  tags = var.tags
}

resource "aws_lambda_alias" "live" {
  name             = "live"
  function_name    = aws_lambda_function.this.function_name
  function_version = aws_lambda_function.this.version
}

resource "aws_lambda_event_source_mapping" "stage" {
  for_each                           = var.queue_arns
  event_source_arn                   = each.value
  function_name                      = aws_lambda_alias.live.arn
  batch_size                         = var.batch_size
  maximum_batching_window_in_seconds = var.maximum_batching_window_seconds
  function_response_types            = ["ReportBatchItemFailures"]
}

output "function_name" {
  value = aws_lambda_function.this.function_name
}

output "role_arn" {
  value = aws_iam_role.this.arn
}
