# ADR 0003 — AWS Lambda + SnapStart over Fargate / App Runner

- **Date:** 2026-04-19
- **Status:** Accepted
- **Deciders:** Kartik Hirijaganer

## Context

Briefed is a single-user self-hosted tool with bursty daily traffic
(scheduled ingest + a small volume of interactive dashboard requests).
Steady-state traffic is near zero; daily cost dominates.

## Decision

- **API Lambda** — FastAPI wrapped via `Mangum`, exposed via a Lambda
  Function URL behind CloudFront. 1024 MB, SnapStart on.
- **Worker Lambda** — same container image, different handler
  (`lambda_worker.sqs_dispatcher`); triggered by SQS event source mappings
  per pipeline stage. 1536 MB, 900 s timeout, SnapStart on.
- **Fan-out Lambda** — tiny function triggered by EventBridge Scheduler that
  enqueues one ingestion job per connected account.
- **No provisioned concurrency.** SnapStart carries the cold-start budget.

## Consequences

**Benefits**
- Daily cost ≈ $0 under the AWS free tier. Plan §19.15 documents the full
  math — AWS steady-state ~$1–2/month.
- SnapStart takes Python cold starts from 1–3 s to ~200–300 ms post-restore.
  Free; enabled by the Lambda alias publish step.
- Single container image means one build, two handlers. No infra
  duplication between API and worker paths.
- Atomic rollback = one `aws lambda update-alias --function-version <n-1>` call.

**Costs**
- Hard 15-min timeout — big Gmail backfills must be chunked. Ingestion
  handler already respects `bootstrap_lookback_days` caps.
- No persistent DB connection pool across invocations — mitigated by the
  Supabase transaction-mode pooler (pgbouncer) and SQLAlchemy `NullPool`.
- Cold-start-after-deep-idle still visible (~300–500 ms post-snapshot).
  Acceptable for personal use; not for a latency-sensitive public SaaS.

## Alternatives considered

- **Fargate + ALB.** Rejected — persistent task = ~$9/mo minimum, plus ALB
  charges. Operationally heavier (task definitions, autoscaling) with no
  product-level benefit at single-user scale.
- **App Runner.** Rejected — lowest Fargate-tier pricing but still $5–7/mo
  baseline, and caps on concurrency that don't match a batched worker.
- **EC2 + systemd.** Rejected — operational tax too high for a one-person OSS
  project; encourages snowflake servers.

## Revisit triggers

- Hosted multi-tenant deployment (not in 1.0.0 scope) — consider Fargate for
  long-lived WebSocket / SSE workloads.
- SnapStart cold-start p99 post-restore exceeds 500 ms on monitored workload
  — evaluate provisioned concurrency on the API Lambda.
