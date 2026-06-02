# ADR 0013 - Gmail mark-read write scope

- **Date:** 2026-05-31
- **Status:** Accepted
- **Deciders:** Kartik Hirijaganer
- **Supersedes:** ADR 0006 and ADR 0007, only for explicit Gmail mark-read

## Context

The daily-triage dashboard needs a way to clear reviewed mail so unread
messages do not reappear in later briefs. Gmail represents unread state as
the `UNREAD` label. Removing that label requires the restricted
`gmail.modify` OAuth scope; Gmail does not offer a narrower labels-only
write scope.

ADR 0006 made release 1.0.0 recommend-only and explicitly prohibited
mark-read. ADR 0007 kept the mailbox interface read-oriented. Those
choices made sense before the dashboard became the primary working
surface, but they now block the core review loop: read the brief, clear
reviewed messages, and keep future scans focused on unread mail.

## Decision

Permit exactly one mailbox write in 1.0.0: a user-initiated mark-read
action that removes `UNREAD` from selected Gmail messages.

The allowed mutation is constrained as follows:

1. The API endpoint is `POST /api/v1/emails/mark-read`.
2. The action requires an explicit user request by email ids or category.
3. The provider call uses Gmail `users.messages.batchModify`.
4. The only allowed mutation is `removeLabelIds: ["UNREAD"]`.
5. The action never archives, deletes, sends, drafts, labels, or
   unsubscribes.
6. Local `emails.labels` is updated only after Gmail reports success.
7. Existing accounts must re-consent to grant `gmail.modify`.

`MailboxProvider` now exposes `mark_read(message_ids) -> MarkReadResult`
so future providers must model the capability at the same abstraction
level rather than leaking Gmail API shapes into the API layer.

## Consequences

**Benefits**

- Reviewed mail leaves the Briefed dashboard and future unread-only scans.
- The write surface is narrow, explicit, reversible in Gmail, and easy to
  audit.
- Gmail-specific mechanics stay behind `MailboxProvider`.

**Costs**

- Google OAuth consent now requests `gmail.modify`, a broader restricted
  scope than read-only ingest needs.
- Existing connected accounts must reconnect before mark-read works.
- Any hosted distribution has a more expensive Google verification path.

## Alternatives considered

- **Keep recommend-only and open Gmail links.** Rejected. It preserves the
  old safety posture but leaves the dashboard unable to close the review
  loop.
- **Use archive instead of mark-read.** Rejected. Archiving is a stronger
  mailbox mutation and is outside the release goal.
- **Add a local-only dismissed flag.** Rejected. It would hide mail in
  Briefed but leave Gmail unread, causing mismatch and future sync
  ambiguity.

## Revisit triggers

- Gmail adds a narrower labels-only scope.
- Users ask for archive/delete/send actions, which require a separate ADR
  and explicit confirmation/undo design.
- A second mailbox provider cannot support reversible unread-state removal
  cleanly through `MailboxProvider.mark_read`.
