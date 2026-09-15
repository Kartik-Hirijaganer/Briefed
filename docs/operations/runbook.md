# Briefed runbook

Operator-facing playbook for every CloudWatch alarm wired in
`infra/terraform/modules/alarms`. Each section names the alarm, the
trigger, the immediate response, and the rollback / cleanup step.

The SNS topic that fans out alarm emails is named
`${name_prefix}-alarms`. Subscribe an inbox via the AWS console
(SES email subscription is free-tier).

## DLQ depth

- **Alarm:** `${name_prefix}-dlq-depth`.
- **Trigger:** any message visible in `${name_prefix}-dlq` for ≥ 1 minute.
- **First moves:**
  1. Check the per-stage queue depth (`/admin/runs?status=failed` or
     CloudWatch SQS dashboard widget).
  2. Inspect the most recent failed worker log group
     (`/aws/lambda/${name_prefix}-worker`) for the message ID; the JSON
     `event=sqs_dispatcher.failure` line carries the stage + body
     digest.
  3. Drain the DLQ by triggering manual SQS receive + delete after the
     bug is fixed; never delete a poison message without inspecting it.
- **Rollback:** if the worker code is the cause, alias the prior
  Lambda version (`aws lambda update-alias --name prod
  --function-version <previous>`).
- **Drill:** `backend/tests/chaos/test_dlq_drill.py` proves a poison
  record is redriven.

## LLM spend

- **Alarm:** `${name_prefix}-llm-spend` — daily LLM spend > $1.
- **First moves:**
  1. Open the `LLM spend (USD/day)` widget on the
     `${name_prefix}-overview` dashboard. Identify the surge (Gemini vs
     Anthropic).
  2. If Anthropic is the source, the rate cap (`RateCap(max_calls=100)`)
     should self-correct; verify in the next hour.
  3. If Gemini is the source, check the cache-hit panel — a sudden drop
     usually means a prompt change shipped without bumping the prompt
     version (cache key changed).
- **Rollback:** revert the offending prompt version PR, redeploy.

## Gmail quota

- **Alarm:** `${name_prefix}-gmail-quota` — `>` 80% quota usage.
- **First moves:** confirm the user has not added an account whose
  history backfill is blowing through the per-user-per-100s budget.
  Pause manual runs by leaving `prefers-reduced-motion` on no — the
  app-level limiter already caps to `manual_run_daily_cap`.

## Lambda init errors

- **Alarm:** `${name_prefix}-worker-init-errors` — > 2 errors / hour.
- **First moves:**
  1. Check the worker log group for `MissingSecretError` (rotated SSM
     parameter not yet propagated) or KMS `AccessDeniedException`.
  2. If SSM rotation is the cause, rerun `aws --profile personal-admin ssm
     put-parameter --overwrite` and trigger a fresh deploy so new execution
     environments hydrate the updated value.
- **Drill:** `backend/tests/chaos/test_secret_rotation_drill.py` proves
  the second hydration picks up the new value.

## API edge 5xx

- **Alarm:** `${name_prefix}-api-edge-5xx` — CloudFront `5xxErrorRate`
  above 5% over a 5-minute window.
- **Why this alarm exists:** it is the only signal that catches a
  Lambda *service-level* invoke rejection. If the API function has been
  idle long enough for Lambda to reclaim its resources, it moves to the
  `Inactive` state; the next invocation **fails** while Lambda rebuilds
  the execution environment. No handler code runs, so there is no log
  line in `/aws/lambda/${name_prefix}-api` and no `AWS/Lambda` `Errors`
  or `Throttles` datapoint. The caller sees
  `{"Type":"User","message":"The server encountered an error and could
  not complete your request"}`, and a reload a minute later succeeds.
- **First moves:**
  1. `aws lambda get-function --function-name ${name_prefix}-api
     --qualifier live --query 'Configuration.State'`. `Inactive` or
     `Pending` confirms the reclaim path; it returns to `Active` on its
     own once reactivation finishes.
  2. If `State` is `Active`, the 5xx came from the app instead. Check
     the API log group for the request; application 500s are logged with
     a traceback and the request path.
  3. Confirm the keep-alive schedule is still enabled:
     `aws scheduler get-schedule --name ${name_prefix}-api-keepalive`.
     That ping exists specifically to stop the function going idle long
     enough to be reclaimed, so a disabled or failing schedule makes
     this alarm recur.
- **Note:** CloudFront access logging is disabled on the distribution,
  so a rejected invocation leaves no request-level record anywhere.
  Enable it first if this needs to be reconstructed after the fact.

## Worker p95 duration

- **Alarm:** `${name_prefix}-worker-p95-duration` — p95 > 500 ms over
  3 × 5-min windows.
- **First moves:** Supabase pooler health is the usual cause. Check the
  Supabase dashboard for connection-saturation; if so, lower the
  Lambda concurrency knob temporarily.

## Digest failure

- **Alarm:** `${name_prefix}-digest-failure` — any failed digest run in
  24h.
- **First moves:** locate the `digest_runs` row by `run_id`, inspect
  `stats.error`, and re-enqueue via `POST /api/v1/runs` after fixing
  the root cause.

## KMS decrypt anomaly (token + content CMKs)

- **Alarm:** `${name_prefix}-kms-decrypt-anomaly` — Decrypt rate
  exceeds the 7-day baseline by 10× (plan §20.10 Phase 8).
- **First moves:**
  1. CloudTrail filter by key ARN to identify the principal driving
     the spike.
  2. If the principal is unknown, revoke `kms:Decrypt` from the
     execution role immediately — token reads + content reads will fail
     until restored, but no further data is decrypted.
- **Drill:** `backend/tests/chaos/test_kms_revocation_drill.py` shows
  the application surfaces `CryptoError` rather than leaking plaintext
  when the grant is pulled.

## Token-decrypt anomaly

CloudWatch alarm `${name_prefix}-kms-decrypt-anomaly` covers both CMKs;
filter on the `KeyId` dimension to disambiguate token vs content keys.

## Content-decrypt anomaly

Same alarm, content CMK dimension. Plan §20.10 lists the chaos drill
that prevents regression on this path.

## Lambda init errors

(Cross-linked above for the threat model row 7 entry.)

## Restore drill

See [`restore.md`](restore.md). The drill verifies that
`pg_restore` against a fresh Supabase project requires the CMK grant
*before* the data is decryptable — otherwise the backup is useless to
an attacker.
