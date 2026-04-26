# Threat model

Phase 8 expansion (plan §11, §14, §19.9, §20.10). Each row carries a
mitigation, an owner, and a pointer to the alarm + runbook entry that
fires when the mitigation degrades.

| #  | Asset                  | Actor                | Threat                                            | Mitigation                                                                                       | Owner   | Alarm + runbook                                                                              |
|----|------------------------|----------------------|---------------------------------------------------|--------------------------------------------------------------------------------------------------|---------|----------------------------------------------------------------------------------------------|
| 1  | OAuth refresh tokens   | Compromised app role | Read + use tokens directly                        | Envelope crypto under CMK `alias/briefed-token-wrap` (ADR 0008 + plan §20.3)                     | Owner   | `kms-decrypt-anomaly` alarm → [`runbook.md#token-decrypt-anomaly`](../operations/runbook.md) |
| 2  | OAuth refresh tokens   | Malicious DB insider | Read plaintext from Postgres                      | Same as #1 — CMK lives in the operator's AWS account, not Supabase's                             | Owner   | Same as #1                                                                                   |
| 3  | Summaries / rationale  | Malicious DB insider | Read plaintext email content                      | Content CMK `alias/briefed-content-encrypt` (plan §20.10)                                        | Owner   | `kms-decrypt-anomaly` alarm scoped to content CMK → [`runbook.md#content-decrypt-anomaly`](../operations/runbook.md) |
| 4  | Email metadata         | Malicious DB insider | Build social graph, infer content from subjects   | Accepted residual risk; `settings.security.encrypt_subject` opt-in for high-threat operators     | Owner   | n/a                                                                                          |
| 5  | Prompt inputs          | Email sender         | Prompt injection via body                         | `<untrusted_email>` delimiters + Promptfoo adversarial fixtures (`backend/eval/golden/*_adversarial.jsonl`) | Owner   | Promptfoo eval threshold breach → CI fails on PR                                             |
| 6  | Rendered summaries     | Email sender (HTML)  | XSS via malicious summary markup                  | `SafeMarkdown` (`react-markdown` + `rehype-sanitize` allowlist) + CSP `default-src 'self'`        | Owner   | CSP report-only header → CloudWatch logs (Phase 9 candidate)                                 |
| 7  | Lambda execution role  | Credentials leak     | Sign arbitrary AWS calls                          | OIDC-only CI; no long-lived keys; CloudTrail anomaly alarms                                      | Owner   | `worker-init-errors` alarm → [`runbook.md#lambda-init-errors`](../operations/runbook.md)     |
| 8  | Supabase backups       | Operator exfiltration | Offline decrypt of backup                        | Ciphertext only; restore drill verifies CMK access first                                         | Owner   | Restore drill in [`restore.md`](../operations/restore.md)                                    |
| 9  | LLM cost / availability | Provider outage     | Loop, hot key, or 100% failure pages oncall       | Circuit breaker (5 failures → open) + Anthropic Haiku fallback + 100/day cap                     | Owner   | `llm-spend` alarm + chaos drill in `backend/tests/chaos/test_llm_circuit_drill.py`           |
| 10 | DLQ depth              | Pipeline poison-pill | Stuck retries silently lose work                  | Max-receive=5 → DLQ; chaos drill asserts redelivery                                              | Owner   | `dlq-depth` alarm → [`runbook.md#dlq-depth`](../operations/runbook.md)                       |
| 11 | Manual-run abuse       | Compromised session  | Drains daily LLM budget via repeated POST /runs   | Per-user 24h sliding-window limiter (`Settings.manual_run_daily_cap`)                            | Owner   | App-level 429 + `llm-spend` alarm                                                            |

Key rotations (token-wrap, content) are tracked in
[`secrets-rotation.md`](../operations/secrets-rotation.md). The KMS
revocation chaos drill (`backend/tests/chaos/test_kms_revocation_drill.py`)
exercises rows 1–3 by simulating the IAM grant being pulled and asserting
the application surfaces a `CryptoError` instead of leaking plaintext.
