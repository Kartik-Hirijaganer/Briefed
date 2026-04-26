# Briefed 1.0.0 — Announcement Draft

**Status:** draft, ready for sign-off.
**Audience:** OSS readers (GitHub release page, project README banner,
HN / Lobsters submission). One-paragraph blurb up top, screenshot
hooks below.

---

## TL;DR

**Briefed 1.0.0 is out — a personal AI email agent that runs a daily
pipeline on your Gmail inbox.** It classifies every new email into
must-read / good-to-read / ignore / waste, summarizes what matters,
extracts job postings into a filterable list, and recommends senders
to unsubscribe from. It never clicks unsubscribe, archives, or sends
on your behalf — recommend-only, by design (ADR 0006). Self-hosted on
AWS Lambda + SnapStart, ~$8–11/month total to run, MIT-licensed.

GitHub: https://github.com/Kartik-Hirijaganer/Briefed
Release notes: [`docs/release/v1.0.0.md`](v1.0.0.md)

## What's new in 1.0.0 (the headline list)

- **Daily pipeline** — EventBridge Scheduler → fan-out Lambda → SQS
  workers → SES digest. Three accounts × ~500 emails/day fits the
  cost envelope.
- **Four-way triage with a user-editable rubric.** Rules first, LLM
  on miss. Every classification ships its `reasons[]` so you can see
  *why* a row landed in a bucket.
- **Tech-news clustering.** Newsletters get summarized as a single
  cluster card, not a wall of repeated snippets.
- **Job extractor with JSONB filters.** `min_salary_usd`, `location`,
  `seniority_in`, etc. — applied at extraction time so the dashboard
  shows post-filter results.
- **Unsubscribe recommender.** Aggregates 30 days of behavior,
  flags high-volume / low-engagement senders, asks an LLM only on
  borderline cases. No auto-action — you click.
- **PWA dashboard.** Works on desktop and iPhone (installable). Full
  offline read-through via Dexie + Workbox; mutations queue and
  replay on reconnect.
- **Two customer-managed KMS CMKs.** OAuth tokens encrypt under one;
  email summaries / classification reasons / job-match reasons /
  unsubscribe rationales encrypt under another. A Supabase-side leak
  yields metadata only.
- **Operator-friendly.** Runbooks, alarms, chaos drills, blue/green
  Lambda deploy, single-command rollback (alias swap), restore-from-
  backup drill that verifies KMS access is required *before* the
  data is decryptable.

## Why a personal email agent?

The existing inbox-AI tools either (a) auto-act on your mail (one
mis-classified "marketing" thread and a customer goes silent) or (b)
hand your full message body to a third party with no boundary on
training. Briefed picks the third option: run on your own AWS
account, two encryption keys you control, recommend-only by policy.

## Architecture in one diagram (text)

```
EventBridge Scheduler  ──▶  fan-out Lambda  ──▶  SQS (per stage)
                                                   │
                                                   ▼
                            ┌────────────────  worker Lambdas (SnapStart)
                            │                   │     │     │
                            │             classify  summarize  jobs
                            │                   │     │     │
                            └─────▶  Postgres (Supabase, KMS-encrypted blobs)
                                                   │
                                                   ▼
                                          SES → digest email
                                          PWA → CloudFront → Function URL
```

## What's deliberately *not* in 1.0.0

- Auto-acting (no auto-archive, no auto-unsubscribe, no auto-reply).
- Hosted/multi-tenant deployment (the `AuthProvider` seam is in place
  for 1.2+).
- SSE progress streaming for manual runs (polling is enough at this
  scale).
- Server-side full-text search (the trade for content-at-rest
  encryption — see plan §20.10).

## Try it

```bash
git clone https://github.com/Kartik-Hirijaganer/Briefed
cd Briefed
cp .env.example .env   # fill in GEMINI_API_KEY + Google OAuth creds
make bootstrap
make migrate
make dev
```

Open http://localhost:5173, connect Gmail, run a manual scan, watch
the digest land.

## Thank-you

This release was built and shipped solo. The plan
([.claude/plans/2026-04-19-release-1-0-0.md](../../.claude/plans/2026-04-19-release-1-0-0.md))
and the ADRs ([docs/adr/](../adr/)) capture every load-bearing
decision; PRs and issues welcome.

---

*Drafted 2026-04-25 alongside Phase 9 of the release plan.*
