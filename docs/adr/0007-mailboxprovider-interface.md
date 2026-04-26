# ADR 0007 — `MailboxProvider` interface

- **Date:** 2026-04-19
- **Status:** Accepted
- **Deciders:** Kartik Hirijaganer

## Context

Release 1.0.0 only supports Gmail. Hard-coding the ingestion pipeline
against Gmail's API shapes — `messageId`, `historyId`, `labels`, header
conventions — would make future Outlook or IMAP support a rewrite rather
than a drop-in.

## Decision

All mailbox access flows through a `MailboxProvider` Protocol:

```python
class MailboxProvider(Protocol):
    async def list_new_ids(self, cursor: SyncCursor) -> list[MessageId]: ...
    async def get_messages(self, ids: list[MessageId]) -> list[RawMessage]: ...
    async def refresh_cursor(self, cursor: SyncCursor) -> SyncCursor: ...
    async def revoke(self, credentials: ProviderCredentials) -> None: ...
```

`GmailProvider` is the sole 1.0.0 implementation. The ingestion worker,
cursor store, and OAuth refresh paths all depend on the protocol rather
than the concrete class.

## Consequences

**Benefits**
- Swapping providers is additive: `OutlookProvider` lands as a new class
  selected via `settings.mailbox.provider`; no pipeline changes.
- `MailboxProvider` is trivially mockable in unit tests; no Gmail fixtures
  needed for classifier / summarizer tests.
- Shared types (`MessageId`, `SyncCursor`, `RawMessage`) become the contract,
  which forces us to keep the ingestion layer's vocabulary clean.

**Costs**
- The protocol imposes a small ongoing tax: every new Gmail-specific
  capability must be reframed as a provider-agnostic concept or relegated
  to a Gmail-specific extension point.
- Shared `RawMessage` has to accommodate the widest common subset of
  mailbox semantics (`Message-ID`, `List-Unsubscribe`, `References`,
  thread identity). Not a hard cost — these are all RFC 5322.

## Alternatives considered

- **Hard-code Gmail; refactor when Outlook lands.** Rejected — the cost of
  defining the seam is ~200 lines of Python; the cost of retrofitting it
  across 30+ call sites later is measured in weeks.
- **Do-nothing abstract base class.** Rejected — `Protocol` is cheaper and
  runtime-checked by mypy, no inheritance coupling.

## Revisit triggers

- Second provider lands (Outlook / IMAP) — confirm the protocol holds up; if
  not, evolve it with a new ADR before shipping.
