# ADR 0004 — Supabase Postgres for 1.0.0, portable to RDS

- **Date:** 2026-04-19
- **Status:** Accepted
- **Deciders:** Kartik Hirijaganer

## Context

Briefed needs a managed Postgres at ~$0 / month for a single-user
self-hosted deployment. Options:

- **Supabase free tier** — 500 MB DB, pgbouncer pooler, 50k monthly active
  users, daily backups. Zero cost.
- **AWS RDS** — no permanent free tier for Postgres at meaningful size.
  Smallest usable instance ~$15/month.
- **Neon** — generous free tier, but adds a third cloud (we're already AWS +
  Google for email).
- **Self-hosted on a VPS** — $5+/mo plus backup discipline.

## Decision

Use Supabase Postgres free tier via the **transaction-mode pooler**
(`aws-0-<region>.pooler.supabase.com:6543`) with SQLAlchemy `NullPool`.
Migrations via Alembic; connection string in SSM Parameter Store.

We treat Supabase as vanilla Postgres: no RLS-dependent logic, no edge
functions, no Supabase SDK in request-path code. Supabase admin SDK is
allowed only for file-storage + user-invite flows (if any).

## Consequences

**Benefits**
- $0/month for the data plane at our volume.
- Transaction-mode pooler handles Lambda connection churn (short-lived
  connections from thousands of cold invocations would overwhelm raw
  Postgres).
- Daily backups included; `pg_dump` + S3 upload for explicit snapshots.
- Migration target is unambiguous: if we outgrow Supabase, point Alembic
  at an RDS instance and re-run. No code changes.

**Costs**
- Content-at-rest encryption is our responsibility — addressed by the
  second KMS CMK in ADR 0008 / plan §20.10.
- Supabase can read plaintext for columns we haven't encrypted; §20.10
  narrows that blast radius to metadata only.
- Free tier has a 1-week inactivity pause. Keep-alive cron (maintenance
  handler) keeps the DB warm.

## Alternatives considered

- **Supabase Pro** ($25/mo) — rejected; not required at scale.
- **Neon free tier** — viable, but we prefer to minimize cloud vendors.
- **RDS Serverless v2** — auto-pause down to 0.5 ACU (~$5/mo minimum); still
  strictly more expensive than Supabase.

## Revisit triggers

- Supabase changes free-tier terms (row count, pause policy, egress).
- Hosted multi-tenant deployment — revisit with RDS + its own KMS CMK.
- Query plan shows we need extensions Supabase doesn't enable on the free
  tier (e.g., `pg_partman` for real partitioning — see plan §20.2).
