# Threat model

Phase 0 seed. Phase 8 expands each row with mitigations, owners, and alarm
pointers.

| Asset                     | Actor               | Threat                                          | Current mitigation                                              |
|---------------------------|---------------------|-------------------------------------------------|-----------------------------------------------------------------|
| OAuth refresh tokens      | Compromised app role | Read + use tokens directly                     | Envelope crypto under CMK `alias/briefed-token-wrap` (ADR 0008) |
| OAuth refresh tokens      | Malicious DB insider | Read plaintext from Postgres                    | Same — CMK is in operator's AWS account, not Supabase's         |
| Summaries / rationale     | Malicious DB insider | Read plaintext email content                    | Content CMK `alias/briefed-content-encrypt` (§20.10)            |
| Email metadata            | Malicious DB insider | Build social graph, infer content from subjects | Accepted residual risk; documented trade-off in §20.10          |
| Prompt inputs             | Email sender        | Prompt injection via body                       | `<untrusted_email>` delimiters + Promptfoo adversarial fixtures |
| Rendered summaries        | Email sender (HTML) | XSS via malicious summary markup                | Markdown-only rendering + CSP + `react-markdown` allowlist      |
| Lambda execution role     | Credentials leak    | Sign arbitrary AWS calls                        | OIDC-only CI; no long-lived keys; CloudTrail alarms on anomalies |
| Supabase backups          | Operator exfiltration | Offline decrypt of backup                      | Ciphertext only; restore drill verifies CMK access first        |

Phase 8 adds: prompt-injection adversarial eval fixtures; KMS-revocation
chaos drill; CSP enforcement in e2e; secret-rotation dry run.
