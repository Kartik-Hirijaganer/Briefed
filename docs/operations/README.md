# Operations

Runbook, alarms, and recovery drills for Briefed production.

## Contents

- [`runbook.md`](runbook.md) — page-by-page response playbook for each
  CloudWatch alarm.
- [`alarms.md`](alarms.md) — alarm catalog with thresholds and links to
  runbook entries.
- [`restore.md`](restore.md) — Postgres restore drill (includes the
  KMS-access-first requirement for content-encrypted backups, plan
  §20.10).
- [`rollback.md`](rollback.md) — blue/green rollback playbook +
  pre-cut rehearsal script (plan §14 Phase 9).
- [`secrets-rotation.md`](secrets-rotation.md) — quarterly rotation
  procedure for SSM + CMKs (plan §14 Phase 8).
- `ios-oauth.md` — notes on the iOS PWA OAuth external-Safari gotcha
  (Phase 6 owner; not gating Phase 8).

The Phase 8 chaos drills exercise the alarm classes documented above —
see `backend/tests/chaos/`.
