/*
 * Fan-out Lambda.
 *
 * Target of the EventBridge Scheduler cron. Reads the list of connected
 * accounts for each user and enqueues one ingestion job per account.
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

variable "ingest_queue_arn" {
  type = string
}

variable "ssm_parameter_prefix" {
  type = string
}

variable "kms_key_arns" {
  type = list(string)
}

variable "schedule_expression" {
  description = "EventBridge Scheduler expression, e.g. 'cron(0 6 * * ? *)' for 06:00 UTC daily."
  type        = string
  default     = "cron(0 6 * * ? *)"
}

variable "env_vars" {
  type    = map(string)
  default = {}
}

variable "tags" {
  type    = map(string)
  default = {}
}

data "aws_iam_policy_document" "assume_lambda" {
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
  assume_role_policy = data.aws_iam_policy_document.assume_lambda.json
  tags               = var.tags
}

resource "aws_iam_role_policy_attachment" "basic" {
  role       = aws_iam_role.this.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

data "aws_iam_policy_document" "inline" {
  statement {
    actions   = ["sqs:SendMessage", "sqs:SendMessageBatch"]
    resources = [var.ingest_queue_arn]
  }
  statement {
    actions   = ["ssm:GetParameter", "ssm:GetParameters", "ssm:GetParametersByPath"]
    resources = ["arn:aws:ssm:*:*:parameter${var.ssm_parameter_prefix}*"]
  }
  statement {
    actions   = ["kms:Decrypt"]
    resources = var.kms_key_arns
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
  memory_size   = 512
  timeout       = 60
  architectures = ["x86_64"]

  image_config {
    command = ["app.lambda_worker.fanout_handler"]
  }

  environment {
    variables = merge({ BRIEFED_RUNTIME = "lambda-fanout" }, var.env_vars)
  }

  tags = var.tags
}

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
  name               = "${var.name}-scheduler-role"
  assume_role_policy = data.aws_iam_policy_document.assume_scheduler.json
  tags               = var.tags
}

data "aws_iam_policy_document" "scheduler_inline" {
  statement {
    actions   = ["lambda:InvokeFunction"]
    resources = [aws_lambda_function.this.arn]
  }
}

resource "aws_iam_role_policy" "scheduler_inline" {
  name   = "${var.name}-scheduler-inline"
  role   = aws_iam_role.scheduler.id
  policy = data.aws_iam_policy_document.scheduler_inline.json
}

resource "aws_scheduler_schedule" "daily" {
  name                = "${var.name}-daily"
  schedule_expression = var.schedule_expression
  flexible_time_window {
    mode = "OFF"
  }
  target {
    arn      = aws_lambda_function.this.arn
    role_arn = aws_iam_role.scheduler.arn
  }
}

output "function_name" {
  value = aws_lambda_function.this.function_name
}

output "schedule_name" {
  value = aws_scheduler_schedule.daily.name
}
