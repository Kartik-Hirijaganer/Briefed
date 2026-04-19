# ADR 0006 — Recommend-only in release 1.0.0

- **Date:** 2026-04-19
- **Status:** Accepted
- **Deciders:** Kartik Hirijaganer

## Context

Briefed analyzes the user's inbox and can produce actions: archive,
unsubscribe, mark-read, reply-draft. Two philosophies:

- **Recommend-only** — show suggestions; the user takes every irreversible
  action in Gmail themselves.
- **Auto-execute** — Briefed mutates the mailbox under the user's consent
  (with allowlists, dry-runs, undo).

## Decision

Release 1.0.0 is **recommend-only**. Briefed never archives, deletes,
marks-read, sends, or unsubscribes on the user's behalf. Every action card
in the UI is an "Open in Gmail" deep link or an external unsubscribe URL —
the user clicks through and performs the action in Gmail itself.

## Consequences

**Benefits**
- Blast radius is zero. A hallucinated classification cannot lose mail.
- OAuth scope stays at `gmail.readonly` (plus `gmail.modify` is NOT
  requested), which keeps Google OAuth verification cheap.
- No undo subsystem; no "are you sure?" fatigue.
- Legal / policy story is simple: Briefed is an advisor.

**Costs**
- Users who want inbox-zero automation must act on the recommendations
  manually. That's the point — ADR explicitly trades automation for safety.
- Some features that would be trivial with write scope (e.g., bulk archive
  all newsletters from a dismissed sender) are out of scope for 1.0.0.

## Alternatives considered

- **Opt-in auto-execute with a 5-minute undo window.** Rejected for 1.0.0 —
  requires an undo subsystem, an activity feed, and expanded OAuth scopes
  that trigger Google Restricted Scope verification (plan §19.9 cost).
- **Semi-automated (auto-archive with explicit per-sender opt-in).**
  Deferred to 1.1 at earliest, and only after user demand.

## Revisit triggers

- User research shows recommend-only is friction-generating to the point of
  non-use.
- Google OAuth verification path for `gmail.modify` becomes viable for a
  hosted variant (hosted variant itself is out of 1.0.0 scope — plan §19.9).
