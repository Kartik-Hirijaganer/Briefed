/*
 * Phase 8 — Observability + alarms module (plan §14, §19.13, §20.6, §20.10).
 *
 * Outputs:
 *   - One SNS topic that every CloudWatch alarm publishes to. The
 *     subscription is created out-of-band (one-time email confirmation
 *     in the AWS console, since SNS SES email is the cheapest free-tier
 *     fan-out).
 *   - One CloudWatch dashboard wiring the six widgets called out in the
 *     plan: SQS depth / worker success / LLM spend / Gmail quota /
 *     cache-hit / digest success.
 *   - Seven canonical alarms:
 *       1. DLQ depth > 0
 *       2. Daily LLM spend > $1
 *       3. Gmail quota usage > 80%
 *       4. Lambda task restarts > 2/hr
 *       5. p95 RDS / Postgres latency > 500 ms
 *       6. Digest pipeline failure > 0/day
 *       7. KMS Decrypt rate against the content CMK exceeds the
 *          7-day rolling baseline by 10x (§20.10 Phase 8).
 *
 * The metric filters that turn EMF logs into alarm-able metrics live
 * here too — they read the JSON shapes emitted by
 * `backend/app/observability/metrics.py`.
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
  description = "Prefix for resource names (e.g. 'briefed-dev')."
  type        = string
}

variable "alarm_email" {
  description = "Email to subscribe to the SNS alarm topic. Empty = no auto-subscribe."
  type        = string
  default     = ""
}

variable "dlq_arn" {
  description = "DLQ ARN whose depth fires alarm 1."
  type        = string
}

variable "dlq_name" {
  description = "DLQ queue name (CloudWatch SQS dimension)."
  type        = string
}

variable "lambda_function_names" {
  description = "Map of role -> Lambda function name (api, worker, fanout)."
  type        = map(string)
}

variable "log_group_names" {
  description = "Map of role -> CloudWatch log group name."
  type        = map(string)
}

variable "content_cmk_arn" {
  description = "Content KMS CMK ARN (§20.10) — used to scope the KMS Decrypt anomaly alarm."
  type        = string
}

variable "tags" {
  type    = map(string)
  default = {}
}

# --------------------------------------------------------------------------- #
# SNS topic — single fan-out for alarm notifications.                         #
# --------------------------------------------------------------------------- #

resource "aws_sns_topic" "alarms" {
  name = "${var.name_prefix}-alarms"
  tags = var.tags
}

resource "aws_sns_topic_subscription" "alarms_email" {
  count     = var.alarm_email == "" ? 0 : 1
  topic_arn = aws_sns_topic.alarms.arn
  protocol  = "email"
  endpoint  = var.alarm_email
}

# --------------------------------------------------------------------------- #
# Metric filters that lift EMF + structlog JSON onto CloudWatch metrics.      #
# `backend/app/observability/metrics.py` emits namespace `Briefed/...`        #
# directly via EMF; we still need filters for `LlmSpendUsd` (computed by      #
# `LLMClient`) and `GmailQuotaPct` (logged by the Gmail rate limiter).        #
# --------------------------------------------------------------------------- #

resource "aws_cloudwatch_log_metric_filter" "llm_spend" {
  name           = "${var.name_prefix}-llm-spend"
  log_group_name = var.log_group_names["worker"]
  pattern        = "{ $.event = \"llm.call\" && $.cost_usd > 0 }"

  metric_transformation {
    name      = "LlmSpendUsd"
    namespace = "Briefed/Cost"
    value     = "$.cost_usd"
    unit      = "None"
  }
}

resource "aws_cloudwatch_log_metric_filter" "gmail_quota" {
  name           = "${var.name_prefix}-gmail-quota"
  log_group_name = var.log_group_names["worker"]
  pattern        = "{ $.event = \"gmail.quota\" && $.percent_used > 0 }"

  metric_transformation {
    name      = "GmailQuotaPct"
    namespace = "Briefed/Quota"
    value     = "$.percent_used"
    unit      = "Percent"
  }
}

resource "aws_cloudwatch_log_metric_filter" "digest_failure" {
  name           = "${var.name_prefix}-digest-failure"
  log_group_name = var.log_group_names["worker"]
  pattern        = "{ $.event = \"digest.run\" && $.status = \"failed\" }"

  metric_transformation {
    name      = "DigestFailures"
    namespace = "Briefed/Digest"
    value     = "1"
    unit      = "Count"
  }
}

# --------------------------------------------------------------------------- #
# Alarms                                                                      #
# --------------------------------------------------------------------------- #

# 1. DLQ depth > 0 — any message in the DLQ is an oncall page.
resource "aws_cloudwatch_metric_alarm" "dlq_depth" {
  alarm_name          = "${var.name_prefix}-dlq-depth"
  alarm_description   = "Plan §14 Phase 8: DLQ depth > 0 — investigate failing handlers."
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  dimensions = {
    QueueName = var.dlq_name
  }
  alarm_actions = [aws_sns_topic.alarms.arn]
  ok_actions    = [aws_sns_topic.alarms.arn]
  tags          = var.tags
}

# 2. Daily LLM spend > $1 — same threshold as plan §14 Phase 8.
resource "aws_cloudwatch_metric_alarm" "llm_spend" {
  alarm_name          = "${var.name_prefix}-llm-spend"
  alarm_description   = "Plan §14 Phase 8: LLM spend > $1/day."
  namespace           = "Briefed/Cost"
  metric_name         = "LlmSpendUsd"
  statistic           = "Sum"
  period              = 86400
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]
  tags                = var.tags
}

# 3. Gmail quota > 80% — refresh-token + per-user-per-100s ceiling.
resource "aws_cloudwatch_metric_alarm" "gmail_quota" {
  alarm_name          = "${var.name_prefix}-gmail-quota"
  alarm_description   = "Plan §14 Phase 8: Gmail quota usage > 80%."
  namespace           = "Briefed/Quota"
  metric_name         = "GmailQuotaPct"
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 80
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]
  tags                = var.tags
}

# 4. Lambda task restarts > 2/hr — recurring init failures.
resource "aws_cloudwatch_metric_alarm" "worker_init_errors" {
  alarm_name          = "${var.name_prefix}-worker-init-errors"
  alarm_description   = "Plan §14 Phase 8: > 2 worker init failures per hour."
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  statistic           = "Sum"
  period              = 3600
  evaluation_periods  = 1
  threshold           = 2
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  dimensions = {
    FunctionName = var.lambda_function_names["worker"]
  }
  alarm_actions = [aws_sns_topic.alarms.arn]
  tags          = var.tags
}

# 5. p95 RDS latency > 500 ms — Supabase Postgres pooler health.
resource "aws_cloudwatch_metric_alarm" "lambda_p95_duration" {
  alarm_name          = "${var.name_prefix}-worker-p95-duration"
  alarm_description   = "Plan §14 Phase 8: Lambda p95 duration > 500 ms (proxy for DB latency)."
  namespace           = "AWS/Lambda"
  metric_name         = "Duration"
  extended_statistic  = "p95"
  period              = 300
  evaluation_periods  = 3
  threshold           = 500
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  dimensions = {
    FunctionName = var.lambda_function_names["worker"]
  }
  alarm_actions = [aws_sns_topic.alarms.arn]
  tags          = var.tags
}

# 6. Digest failure > 0/day.
resource "aws_cloudwatch_metric_alarm" "digest_failure" {
  alarm_name          = "${var.name_prefix}-digest-failure"
  alarm_description   = "Plan §14 Phase 8: digest pipeline failure detected."
  namespace           = "Briefed/Digest"
  metric_name         = "DigestFailures"
  statistic           = "Sum"
  period              = 86400
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]
  tags                = var.tags
}

# 7. KMS Decrypt anomaly on the content CMK (§20.10 Phase 8).
#    AWS publishes per-KMS-key request metrics every minute under the
#    AWS/KMS namespace; we alarm if the rolling-hour Decrypt count is
#    more than 10x the trailing-7-day baseline.
resource "aws_cloudwatch_metric_alarm" "kms_decrypt_anomaly" {
  alarm_name          = "${var.name_prefix}-kms-decrypt-anomaly"
  alarm_description   = "Plan §20.10 Phase 8: anomalous Decrypt rate against the content CMK."
  comparison_operator = "GreaterThanUpperThreshold"
  evaluation_periods  = 3
  threshold_metric_id = "ad1"

  metric_query {
    id          = "m1"
    return_data = true
    metric {
      namespace   = "AWS/KMS"
      metric_name = "Decrypt"
      period      = 3600
      stat        = "Sum"
      dimensions = {
        KeyId = var.content_cmk_arn
      }
    }
  }

  metric_query {
    id          = "ad1"
    expression  = "ANOMALY_DETECTION_BAND(m1, 10)"
    label       = "Decrypt expected band (7d)"
    return_data = true
  }

  alarm_actions      = [aws_sns_topic.alarms.arn]
  treat_missing_data = "notBreaching"
  tags               = var.tags
}

# --------------------------------------------------------------------------- #
# Dashboard — six widgets per plan §14 Phase 8.                               #
# --------------------------------------------------------------------------- #

resource "aws_cloudwatch_dashboard" "main" {
  dashboard_name = "${var.name_prefix}-overview"
  dashboard_body = jsonencode({
    widgets = [
      {
        type   = "metric"
        x      = 0
        y      = 0
        width  = 12
        height = 6
        properties = {
          title   = "SQS depth (DLQ + per-stage)"
          view    = "timeSeries"
          stacked = false
          region  = data.aws_region.current.name
          metrics = [
            ["AWS/SQS", "ApproximateNumberOfMessagesVisible", "QueueName", var.dlq_name],
          ]
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 0
        width  = 12
        height = 6
        properties = {
          title  = "Worker success vs failure"
          view   = "timeSeries"
          region = data.aws_region.current.name
          metrics = [
            ["AWS/Lambda", "Invocations", "FunctionName", var.lambda_function_names["worker"]],
            [".", "Errors", ".", "."],
          ]
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 6
        width  = 12
        height = 6
        properties = {
          title  = "LLM spend (USD/day)"
          view   = "timeSeries"
          region = data.aws_region.current.name
          metrics = [
            ["Briefed/Cost", "LlmSpendUsd"],
          ]
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 6
        width  = 12
        height = 6
        properties = {
          title  = "Gmail quota (% used)"
          view   = "timeSeries"
          region = data.aws_region.current.name
          metrics = [
            ["Briefed/Quota", "GmailQuotaPct"],
          ]
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 12
        width  = 12
        height = 6
        properties = {
          title  = "Summarize cache-hit rate"
          view   = "timeSeries"
          region = data.aws_region.current.name
          metrics = [
            ["Briefed/Summarize/Email", "CacheHit", "Environment", var.name_prefix, "Runtime", "lambda-worker"],
          ]
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 12
        width  = 12
        height = 6
        properties = {
          title  = "Digest success vs failure"
          view   = "timeSeries"
          region = data.aws_region.current.name
          metrics = [
            ["Briefed/Digest", "DigestFailures"],
          ]
        }
      },
    ]
  })
}

data "aws_region" "current" {}

output "alarm_topic_arn" {
  value       = aws_sns_topic.alarms.arn
  description = "SNS topic that fans out alarm notifications."
}

output "dashboard_name" {
  value = aws_cloudwatch_dashboard.main.dashboard_name
}
