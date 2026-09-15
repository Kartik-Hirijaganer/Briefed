/*
 * API Lambda — FastAPI via Mangum, published versions, Function URL exposed.
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

variable "reserved_concurrent_executions" {
  description = "Reserved API concurrency. Use -1 for unreserved mode in low-quota dev accounts."
  type        = number
  default     = -1

  validation {
    condition     = var.reserved_concurrent_executions >= -1
    error_message = "reserved_concurrent_executions must be -1 or greater."
  }
}

variable "function_url_auth_mode" {
  type    = string
  default = "NONE"
}

variable "keepalive_enabled" {
  description = "Ping the API on a schedule so it never goes Inactive from idleness."
  type        = bool
  default     = true
}

variable "keepalive_schedule_expression" {
  description = "How often to ping. Must stay well under Lambda's idle-reclaim window."
  type        = string
  default     = "rate(1 day)"
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
  function_name                  = var.name
  role                           = aws_iam_role.this.arn
  package_type                   = "Image"
  image_uri                      = var.image_uri
  publish                        = true
  memory_size                    = var.memory_mb
  timeout                        = var.timeout_seconds
  architectures                  = ["x86_64"]
  reserved_concurrent_executions = var.reserved_concurrent_executions

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
  authorization_type = var.function_url_auth_mode
}

# --------------------------------------------------------------------------- #
# Keep-alive                                                                  #
#                                                                             #
# Lambda reclaims the resources of a function left idle for an extended        #
# period and moves it to the Inactive state. The next invocation of an         #
# Inactive function FAILS while Lambda recreates those resources: the          #
# caller gets a generic service error, no handler code runs, so there is       #
# no log line and no AWS/Lambda Errors datapoint. On a low-traffic             #
# deployment that surfaces as "the site is randomly down, then fine on         #
# reload". A cheap scheduled ping keeps the function out of that state.        #
# --------------------------------------------------------------------------- #

data "aws_iam_policy_document" "assume_scheduler" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "scheduler" {
  name               = "${var.name}-keepalive-role"
  assume_role_policy = data.aws_iam_policy_document.assume_scheduler.json
  tags               = var.tags
}

data "aws_iam_policy_document" "scheduler_inline" {
  statement {
    actions   = ["lambda:InvokeFunction"]
    resources = [aws_lambda_alias.live.arn]
  }
}

resource "aws_iam_role_policy" "scheduler_inline" {
  name   = "${var.name}-keepalive-inline"
  role   = aws_iam_role.scheduler.id
  policy = data.aws_iam_policy_document.scheduler_inline.json
}

# The payload is a Lambda Function URL (HTTP API v2) event so Mangum can
# route it like any other request; it hits the app's own GET /health.
resource "aws_scheduler_schedule" "keepalive" {
  name                = "${var.name}-keepalive"
  schedule_expression = var.keepalive_schedule_expression
  state               = var.keepalive_enabled ? "ENABLED" : "DISABLED"

  flexible_time_window {
    mode                      = "FLEXIBLE"
    maximum_window_in_minutes = 15
  }

  target {
    arn      = aws_lambda_alias.live.arn
    role_arn = aws_iam_role.scheduler.arn
    input = jsonencode({
      version        = "2.0"
      routeKey       = "$default"
      rawPath        = "/health"
      rawQueryString = ""
      headers = {
        host         = "keepalive.briefed.internal"
        "user-agent" = "briefed-keepalive"
      }
      requestContext = {
        accountId    = "anonymous"
        apiId        = "keepalive"
        domainName   = "keepalive.briefed.internal"
        domainPrefix = "keepalive"
        http = {
          method    = "GET"
          path      = "/health"
          protocol  = "HTTP/1.1"
          sourceIp  = "127.0.0.1"
          userAgent = "briefed-keepalive"
        }
        requestId = "keepalive"
        routeKey  = "$default"
        stage     = "$default"
        time      = "01/Jan/2026:00:00:00 +0000"
        timeEpoch = 1767225600000
      }
      isBase64Encoded = false
    })
  }
}

output "function_name" {
  value = aws_lambda_function.this.function_name
}

output "function_url" {
  value = aws_lambda_function_url.this.function_url
}

output "alias_name" {
  value       = aws_lambda_alias.live.name
  description = "Alias the Function URL is published on; used for the CloudFront invoke permission qualifier."
}

output "role_arn" {
  value = aws_iam_role.this.arn
}
