# ADR 0008 — KMS CMK for OAuth token-wrap key

- **Date:** 2026-04-19
- **Status:** Accepted
- **Deciders:** Kartik Hirijaganer

## Context

`oauth_tokens.access_token_ct` and `oauth_tokens.refresh_token_ct` must be
encrypted at rest so a Supabase-side read yields ciphertext only. The
original plan (§19.15) stored the envelope wrap key as an SSM Parameter
Store `SecureString` loaded into the app's process memory on cold start.

Peer review flagged this as security theater: an attacker who compromises
the Lambda execution role can read both the ciphertext (Postgres) and the
wrap key (SSM). The envelope adds zero boundary over platform
encryption-at-rest in that threat model.

## Decision

Use a **customer-managed AWS KMS CMK** (alias `alias/briefed-token-wrap`)
per environment:

- Per-token 256-bit DEK, AES-GCM ciphertext in Postgres.
- DEK wrapped by CMK via `kms:Encrypt` at write; unwrapped via
  `kms:Decrypt` at read. **Key material never leaves KMS.**
- App Lambda role has `kms:Decrypt` on this key and nothing else. Key
  administration (`kms:ScheduleKeyDeletion`, `DisableKey`) is a separate
  admin role.
- `EnableKeyRotation = true` — annual AWS-managed rotation.
- Encryption context binds `user_id` + `token_kind` + `purpose="token_wrap"`
  into every call; KMS rejects Decrypts with mismatched context.

A second CMK (`alias/briefed-content-encrypt`) encrypts summaries and
rationale (plan §20.10). Two keys so token compromise and content
compromise have independent revocation paths.

## Consequences

**Benefits**
- Real trust boundary: revoking the app role's `kms:Decrypt` permission
  immediately bricks all token reads without a re-encryption sweep.
- Every unwrap is logged in CloudTrail; an anomalous decrypt alarm is
  cheap to add.
- DEK rotation on re-auth + annual CMK rotation gives us defense in depth.

**Costs**
- ~$1/month per CMK (two CMKs = ~$2/mo). Steady-state plan bumped from
  $6–9 to $8–11 (plan §20.8). Cheap for the boundary it buys.
- Per-call decrypt charges (~$0.03 / 10k) — negligible at personal volume.
- Warm Lambda LRU cache (max 200 DEKs, dropped on cold start) keeps the
  KMS latency off the hot path.

## Alternatives considered

- **SSM SecureString-wrapped DEK (original plan).** Rejected — same
  blast-radius as the ciphertext; not a meaningful boundary.
- **Single CMK for tokens + content.** Rejected — couples two revocation
  surfaces and muddies CloudTrail alarms.
- **AWS-managed KMS key (`alias/aws/ssm`).** Rejected — no granular revoke,
  and the whole point is a revocable boundary the app role cannot bypass.

## Revisit triggers

- HSM-backed CMK becomes a requirement (compliance).
- Multi-region deployment — duplicate keys with replicated grants, or move
  to an AWS KMS multi-region key.
