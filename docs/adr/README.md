# Architecture Decision Records

Each ADR captures one decision: context, options considered, the choice,
and its consequences. We use the lightweight Michael Nygard template —
short, dated, numbered, immutable once accepted.

- **Immutable.** Once an ADR is accepted, the decision is recorded; later
  reversals land as a new ADR that supersedes the old one. Never edit
  an accepted ADR in place.
- **Status values.** `Proposed` → `Accepted` → `Superseded by ADR-NNNN` /
  `Deprecated`.
- **Numbering.** Monotonic; do not reuse numbers.
- **Naming.** `NNNN-short-slug.md`.

| ADR  | Title                                                 | Status   |
|------|-------------------------------------------------------|----------|
| 0001 | Scheduled sync over Gmail push                        | Accepted |
| 0002 | Gemini Flash primary, Claude Haiku fallback           | Accepted |
| 0003 | AWS Lambda + SnapStart over Fargate                   | Accepted |
| 0004 | Supabase for 1.0.0, portable to RDS                   | Accepted |
| 0005 | PWA over native iOS                                   | Accepted |
| 0006 | Recommend-only in release 1.0.0                       | Accepted |
| 0007 | `MailboxProvider` interface                           | Accepted |
| 0008 | KMS CMK for token-wrap key                            | Accepted |
