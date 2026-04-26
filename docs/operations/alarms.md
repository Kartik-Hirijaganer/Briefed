# Alarm catalog

Every CloudWatch alarm wired in `infra/terraform/modules/alarms` with
threshold, evaluation window, and the runbook section that handles the
page. Mirrors the table in plan §14 Phase 8.

| #  | Alarm name                              | Source                | Threshold                                       | Window     | Runbook section |
|----|-----------------------------------------|-----------------------|-------------------------------------------------|------------|-----------------|
| 1  | `${name_prefix}-dlq-depth`              | AWS/SQS               | `ApproximateNumberOfMessagesVisible > 0`        | 1 × 60s    | [DLQ depth](runbook.md#dlq-depth) |
| 2  | `${name_prefix}-llm-spend`              | Briefed/Cost EMF      | `LlmSpendUsd > 1` per day                       | 1 × 86400s | [LLM spend](runbook.md#llm-spend) |
| 3  | `${name_prefix}-gmail-quota`            | Briefed/Quota EMF     | `GmailQuotaPct > 80`                            | 1 × 300s   | [Gmail quota](runbook.md#gmail-quota) |
| 4  | `${name_prefix}-worker-init-errors`     | AWS/Lambda            | `Errors > 2` per hour                           | 1 × 3600s  | [Lambda init errors](runbook.md#lambda-init-errors) |
| 5  | `${name_prefix}-worker-p95-duration`    | AWS/Lambda            | `Duration p95 > 500ms`                          | 3 × 300s   | [Worker p95 duration](runbook.md#worker-p95-duration) |
| 6  | `${name_prefix}-digest-failure`         | Briefed/Digest EMF    | `DigestFailures > 0` per day                    | 1 × 86400s | [Digest failure](runbook.md#digest-failure) |
| 7  | `${name_prefix}-kms-decrypt-anomaly`    | AWS/KMS               | `Decrypt > anomaly band(10)` (7d baseline)      | 3 × 3600s  | [KMS decrypt anomaly](runbook.md#kms-decrypt-anomaly-token--content-cmks) |

All alarms publish to the single SNS topic `${name_prefix}-alarms` so
operators can subscribe one inbox and route via SES rules.

## Tuning notes

- The plan budgets one week of post-Phase-8 burn-in for threshold
  tuning. The defaults above are conservative; expect the
  `worker-p95-duration` alarm to false-positive during the first cold
  burst after each deploy and to settle after SnapStart warms up.
- Replacement of `EXTENDED_STATISTIC=p95` with `p99` is reserved for a
  Phase 9 follow-up if oncall confirms the p95 line is too noisy.
