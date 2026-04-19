# Operations

Runbook, alarms, and recovery drills for Briefed production.

## Contents (target — Phase 8 populates these)

- `runbook.md` — page-by-page response playbook for each CloudWatch alarm.
- `alarms.md` — alarm catalog with thresholds and links to runbook entries.
- `restore.md` — Postgres restore drill (includes the KMS-access-first
  requirement for content-encrypted backups, plan §20.10).
- `secrets-rotation.md` — quarterly rotation procedure for SSM + CMKs.
- `ios-oauth.md` — notes on the iOS PWA OAuth external-Safari gotcha.

Phase 0 ships only this README so links in ADRs and plan docs resolve.
