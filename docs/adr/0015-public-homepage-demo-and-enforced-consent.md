# ADR 0015 - Public homepage, demo, and enforced consent

- **Date:** 2026-06-13
- **Status:** Accepted
- **Deciders:** Kartik Hirijaganer
- **Related:** ADR 0008, ADR 0009, ADR 0011, ADR 0013, ADR 0014

## Context

Briefed originally treated `/` as the authenticated dashboard. That made the
product difficult to review publicly: recruiters, hiring managers, and other
external reviewers had no public product surface, and the real Gmail OAuth path
was blocked for anyone who was not an OAuth test user while the app remained
unverified.

The real Gmail path also requests restricted Gmail scopes: `gmail.readonly` for
ingestion and `gmail.modify` for user-initiated mark-read actions. Those scopes
require clear Limited Use disclosures and informed user consent before mailbox
data is processed. A UI-only acknowledgement is insufficient because scheduled
workers, offline replay, and direct API calls can process Gmail-derived data
without mounting the consent UI.

## Decision

Split public review from real Gmail processing.

1. `/` is a public homepage. `/about`, `/privacy`, and `/terms` are public
   content routes. These routes render without authenticated API calls.
2. `/demo/*` is a public synthetic workspace that reuses the real app pages but
   seeds TanStack Query with fixture data and blocks every `/api/*` request,
   including reads. Demo mutations are disabled at the UI entry points.
3. The authenticated product moves under `/app/*`. App routes use centralized
   route-base helpers so the same page components can render under `/app` and
   `/demo` without hardcoded links.
4. Real Gmail processing is gated by versioned legal consent. The backend owns
   `CURRENT_PRIVACY_POLICY_VERSION` and `CURRENT_TERMS_VERSION`; the frontend
   mirrors them in its legal content constants and sends those versions when a
   user accepts.
5. The app shell hard-branches while consent is required: the consent dialog
   renders, but child routes do not mount. The backend independently enforces
   current consent before manual scans, scheduled fanout/ingest work, and
   Gmail-affecting mutations such as mark-read and unsubscribe actions.
6. The public legal copy describes the actual runtime: OpenRouter routes model
   calls to Google Gemini 2.5 Flash first and Anthropic Claude Haiku 4.5 as
   fallback; prompt redaction is best-effort identity and pattern-based removal,
   not a guarantee that all personal information is removed.

## Consequences

**Benefits**

- Reviewers can evaluate Briefed immediately through synthetic data without a
  Google account, OAuth test-user access, or restricted-scope verification.
- Real Gmail users see the policy, scope, no-HIPAA, and LLM-processing
  disclosures before mailbox data is processed.
- Consent enforcement does not depend on React state. Workers and API mutation
  paths reject or skip Gmail-derived work when consent is stale or absent.
- Public routes become crawler- and recruiter-friendly while the app dashboard
  remains behind `/app/*`.

**Costs**

- Route generation must stay centralized so shared app/demo pages do not drift.
- Demo fixtures must stay aligned with API query keys and page expectations.
- Privacy and Terms version bumps now require coordinated backend and frontend
  constant updates plus a published effective date.
- Public legal copy must be maintained when Gmail scopes, subprocessors, LLM
  routes, retention, or destructive-action behavior changes.

## Alternatives considered

- **Keep `/` authenticated.** Rejected. It leaves no public face for the
  project and makes recruiter review depend on a real OAuth path most reviewers
  cannot complete.
- **Make real Gmail OAuth the primary demo.** Rejected. Unverified restricted
  Gmail scopes limit OAuth to configured test users, and full verification
  requires custom-domain setup plus CASA assessment for stored restricted-scope
  data.
- **Use UI-only consent.** Rejected. Workers, queued mutations, and direct API
  calls can process Gmail-derived data without mounting the consent component.
- **Build a separate demo-only UI.** Rejected. It would drift from the real
  product and make demo verification weaker. Reusing real pages with a seeded,
  network-blocked query client keeps the demo representative.
- **Serve the frontend and API as cross-origin deployments.** Rejected for this
  phase. Keeping `/api/*` same-origin through the frontend host preserves the
  existing session-cookie and CSRF assumptions.

## Revisit triggers

- Google OAuth verification and CASA assessment are complete and the public
  Connect Gmail path can be enabled broadly.
- New Gmail scopes, new destructive actions, or new subprocessors change the
  Privacy Policy or Terms obligations.
- The demo needs to support workflows that cannot be represented with static
  seeded data.
- A future deployment intentionally chooses cross-origin frontend/API hosting.
