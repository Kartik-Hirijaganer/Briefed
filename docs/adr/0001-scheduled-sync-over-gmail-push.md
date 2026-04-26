# ADR 0001 — Scheduled sync over Gmail push

- **Date:** 2026-04-19
- **Status:** Accepted
- **Deciders:** Kartik Hirijaganer

## Context

Briefed needs to reliably pick up new Gmail messages for the connected
accounts. Google offers two paths:

1. **Gmail push notifications** — Pub/Sub watch + webhook, near-real-time.
2. **Scheduled incremental sync** — EventBridge Scheduler fires a fan-out
   Lambda that calls `users.history.list` starting at
   `sync_cursors.history_id` for each account.

## Decision

Release 1.0.0 uses scheduled incremental sync only. The daily cron fires
once per user; the fan-out Lambda enqueues one ingestion job per
connected account. No Pub/Sub watch, no webhook endpoint.

## Consequences

**Benefits**
- Simpler surface: no webhook auth, no Pub/Sub topic, no GCP billing path.
- Deterministic cost envelope. Personal scale costs cents; see plan §19.15.
- Cursor-driven fetches (`historyId`) are idempotent; re-runs are no-ops.
- Lambda 15-minute budget is enough for bounded backfills (lookback capped
  via `settings.ingestion.bootstrap_lookback_days`).

**Costs**
- Up to 24 hours of latency between inbox arrival and Briefed surfacing.
  Acceptable for a daily-digest product; unacceptable if real-time triage
  becomes a goal.
- Stale-cursor edge cases require a bounded full resync fallback (plan §16).

## Alternatives considered

- **Push + scheduled sync as a redundant pair.** Rejected for 1.0.0 — doubles
  the failure surface without a product-level latency requirement driving it.
- **Gmail IMAP IDLE.** Rejected — Google has deprecated IMAP for new OAuth
  consumers; out of scope.

## Revisit triggers

- Product opens real-time intake (e.g., meeting-prep triage) — revisit push.
- Cold-start latency post-SnapStart exceeds user tolerance — consider push to
  avoid waking Lambda on a schedule.
