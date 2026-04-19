# ADR 0005 — PWA over native iOS

- **Date:** 2026-04-19
- **Status:** Accepted
- **Deciders:** Kartik Hirijaganer

## Context

The dashboard must be usable on a phone, with reasonable offline support
and install-to-home-screen affordances. Two paths:

- **Progressive Web App** — one React codebase, Workbox + IndexedDB offline
  story, `manifest.json` for install prompts.
- **Native iOS (Swift/SwiftUI)** — best-in-class platform integration +
  App Store distribution.

## Decision

Ship 1.0.0 as a PWA only. No native iOS or Android app.

## Consequences

**Benefits**
- One codebase across web + mobile; contributor barrier stays a single `npm`.
- No $99/year developer cert, no App Store review latency.
- `vite-plugin-pwa` + Workbox give us offline reading of the last digest
  and a service-worker update flow we fully control.

**Costs**
- **iOS caveats are real.** Per plan §19.16 §6:
  - iOS Safari freezes long-lived network connections after ~30 s of
    background. Manual-run progress uses polling only (plan §20.5).
  - OAuth redirect must escape the in-app webview via `window.open` →
    external Safari → universal-link callback to the installed PWA.
  - IndexedDB eviction policy is aggressive; Dexie (§19.10) gives us the
    schema clarity to detect and re-seed a cleared cache cleanly.
  - No `navigator.vibrate` (Android only).
- No widgets, no background sync beyond what Safari allows (very little).

## Alternatives considered

- **PWA + Capacitor shell** for App Store presence. Rejected for 1.0.0 —
  doubles the release surface for zero product benefit at single-user scale.
- **Native iOS.** Rejected — would multiply the roadmap (API layer already
  duplicates into Swift bindings) and block Android indefinitely.

## Revisit triggers

- Real demand for iOS widgets, Focus Filters, or background push that PWAs
  can't express.
- App Store distribution becomes necessary (hosted multi-tenant scenario).
