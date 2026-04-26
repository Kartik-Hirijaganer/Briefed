/*
 * API Lambda — FastAPI via Mangum, SnapStart on, Function URL exposed.
 *
 * Container-image packaging (ECR); single image, handler selects entrypoint.
 * CloudFront sits in front of the Function URL (see cloudfront module).
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
  description = "ECR image URI for the app container, tagged with the release sha."
  type        = string
}

variable "ssm_parameter_prefix" {
  description = "SSM prefix the function is allowed to ssm:GetParameter on."
  type        = string
}

variable "kms_key_arns" {
  description = "KMS key ARNs the function may kms:Decrypt / kms:Encrypt (token + content CMKs)."
  type        = list(string)
}

variable "sqs_queue_arns" {
  description = "SQS queue ARNs the function may publish to (fan-out / scan-now path)."
  type        = list(string)
  default     = []
}

variable "memory_mb" {
  type    = number
  default = 1024
}

variable "timeout_seconds" {
  type    = number
  default = 30
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
    sid     = "SsmRead"
    actions = ["ssm:GetParameter", "ssm:GetParameters", "ssm:GetParametersByPath"]
    resources = [
      "arn:aws:ssm:*:*:parameter${var.ssm_parameter_prefix}*",
    ]
  }

  statement {
    sid       = "KmsEnvelope"
    actions   = ["kms:Decrypt", "kms:Encrypt", "kms:GenerateDataKey"]
    resources = var.kms_key_arns
  }

  dynamic "statement" {
    for_each = length(var.sqs_queue_arns) > 0 ? [1] : []
    content {
      sid       = "SqsPublish"
      actions   = ["sqs:SendMessage", "sqs:SendMessageBatch", "sqs:GetQueueAttributes"]
      resources = var.sqs_queue_arns
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

  # SnapStart intentionally omitted: AWS Lambda SnapStart does not
  # support container-image package_type ("ContainerImage is not
  # supported for SnapStart enabled functions"). The codebase still
  # treats module-level init as snapshot-friendly so we can flip back
  # on if AWS adds container support later (or if we move to a ZIP
  # package). Cold start is therefore Mangum + boto3 + httpx warm-up
  # ~600-900 ms instead of the ~200-300 ms target in ADR 0003.

  image_config {
    command = ["app.lambda_api.mangum_handler"]
  }

  environment {
    variables = merge({ BRIEFED_RUNTIME = "lambda-api" }, var.env_vars)
  }

  tags = var.tags
}

resource "aws_lambda_alias" "live" {
  name             = "live"
  function_name    = aws_lambda_function.this.function_name
  function_version = aws_lambda_function.this.version
  description      = "Rolling alias; update-alias is the atomic deploy step."
}

resource "aws_lambda_function_url" "this" {
  function_name      = aws_lambda_function.this.function_name
  qualifier          = aws_lambda_alias.live.name
  authorization_type = "NONE"

  cors {
    allow_origins = ["*"]
    # OPTIONS (7 chars) violates AWS's 6-char-per-method constraint on
    # cors.allowMethods. Browser preflight requests work without it
    # being in this list — the API handles OPTIONS implicitly.
    allow_methods = ["GET", "POST", "PUT", "PATCH", "DELETE"]
    allow_headers = ["content-type", "authorization"]
    max_age       = 86400
  }
}

output "function_name" {
  value = aws_lambda_function.this.function_name
}

output "function_url" {
  value = aws_lambda_function_url.this.function_url
}

output "role_arn" {
  value = aws_iam_role.this.arn
}
