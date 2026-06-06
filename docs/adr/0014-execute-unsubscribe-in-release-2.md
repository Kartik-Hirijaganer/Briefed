# ADR 0014 - Execute unsubscribe in release 2

- **Date:** 2026-06-06
- **Status:** Accepted
- **Deciders:** Kartik Hirijaganer
- **Supersedes:** ADR 0006, only for the explicit unsubscribe action

## Context

ADR 0006 made release 1.0.0 recommend-only: the agent never clicks
unsubscribe, archives, or sends on the user's behalf. The unsubscribe page
therefore only ever opened the sender's link in a new tab and recorded that
the user handled it themselves.

The redesigned unsubscribe page (Release 2) introduces a bulk "Unsubscribe N
selected" action. Users asked for that button to *actually* unsubscribe where
the sender supports it, not merely open links. That reverses ADR 0006 for one
action — exactly the kind of destructive, externally side-effecting capability
ADR 0006 guarded — so it follows the same pattern ADR 0013 used for mark-read:
a narrow, explicit, gated write, recorded in a new ADR.

Unlike mark-read (which mutates the user's mailbox via `gmail.modify`), an
unsubscribe is an outbound request to a *sender-controlled* URL. That URL is
attacker-influenced data: a malicious or compromised sender can advertise a
`List-Unsubscribe` HTTP target pointing at internal infrastructure (SSRF), so
the executor needs deliberate network hardening.

## Decision

Permit exactly one new external side effect in Release 2: a user-initiated
unsubscribe that posts to (or surfaces) the sender-advertised
`List-Unsubscribe` target.

The capability is constrained as follows:

1. The API endpoint is `POST /api/v1/unsubscribes/{suggestion_id}/execute`
   and requires an explicit `{"confirm": true}` body per action.
2. It is gated behind the `FeatureConfig.unsubscribe_execute` flag, which
   defaults **off**. With the flag off the endpoint is not available.
3. It acts **only** via the sender-advertised `List-Unsubscribe` header that
   Briefed already parsed and stored — Briefed never invents a target.
4. When the sender advertises RFC 8058 one-click over HTTPS, the executor
   sends a single `POST` with `List-Unsubscribe=One-Click`. Otherwise the
   action is `manual_required`: Briefed surfaces the link/`mailto:` for the
   user to finish themselves and never auto-acts.
5. It is **online-only**. A destructive external action must not be queued and
   replayed later without fresh confirmation.
6. It requests **no new Gmail/OAuth scope** and performs **no mailbox
   mutation** (no archive, delete, label, or send). `mailto:`-only senders are
   `manual_required` — adding `gmail.send` would trigger Google
   Restricted-Scope review and is out of scope.
7. The outbound request is SSRF-hardened: scheme restricted to http/https;
   the resolved host is rejected if any resolved address is
   private/loopback/link-local/reserved/CGNAT/metadata (IPv4 and IPv6);
   redirects are not followed; proxy env vars are ignored; the response body
   read is bounded; and the request runs under a configurable timeout.

## Consequences

**Benefits**

- The bulk red button does what users expect where senders support it, while
  still closing the loop safely for senders that do not.
- The write surface stays narrow, explicit, per-action confirmed, flagged off
  by default, and easy to audit via the row lifecycle columns.
- No broader OAuth scope and no mailbox mutation, so the Google verification
  posture is unchanged.

**Costs**

- Briefed now makes outbound requests to sender-controlled URLs, which
  requires the SSRF validator and ongoing care as a security-sensitive path.
- A real execute lifecycle (`pending` / `unsubscribed` / `manual_required` /
  `failed`) must be persisted and surfaced, adding schema + UI state.

## Alternatives considered

- **Stay recommend-only (ADR 0006).** Rejected for the unsubscribe action: it
  leaves the bulk button unable to do what users asked for.
- **Follow redirects / use a shared HTTP client.** Rejected. A 3xx to an
  internal address is a classic SSRF bypass; redirects are treated as
  `manual_required`/`failed` and the executor uses a dedicated
  `trust_env=False` client.
- **Add `gmail.send` to satisfy `mailto:` unsubscribes.** Rejected. It expands
  the restricted-scope surface for a minority of senders; `mailto:` stays
  `manual_required`.

## Revisit triggers

- A sender ecosystem shift makes `mailto:`-only unsubscribes common enough to
  justify a separate send-scope ADR.
- Pinned-IP connect (resolve once, connect to that IP, send `Host`) is needed
  to fully close the DNS-rebinding window noted as optional future hardening.
