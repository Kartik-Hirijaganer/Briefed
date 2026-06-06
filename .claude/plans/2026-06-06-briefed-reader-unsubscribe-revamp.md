# Briefed — Daily Digest reader redesign + Unsubscribe revamp (Release 2)

## Context

The home page ("Today's Digest") and the Unsubscribe page are getting a visual
overhaul: a **two-pane reader** (mockup image 1) and a **multi-select
sender-triage** layout (mockup image 3). Today the home page is a stat-cards +
email **table**; the unsubscribe page is a list of single-action cards. The
redesign aligns both with the Notion design system and makes triage faster.

This is **primarily a UI change**, but two deliberate, user-approved scope
additions push into the backend:

1. **`recent_subjects`** — a small **read-only** field so the unsubscribe cards
   can show recent subjects. The aggregator *already computes this and throws it
   away*; we just persist + expose it. Low risk.
2. **"Actually unsubscribe" (Release 2).** The user wants the bulk red button to
   *perform* the unsubscribe, not just record it. This reverses **ADR 0006**
   (recommend-only) for the unsubscribe action and — per the repo's own rule
   (CLAUDE.md §9) — must be **gated behind explicit confirmation and a new ADR**.
   It is a **destructive, external side-effecting action** and is treated with the
   same care as mark-read (the existing precedent), plus SSRF hardening.

Because the risk profiles differ sharply, this work ships as **five sequenced,
independently-shippable tracks** (each its own PR). The pure-UI redesign lands
with **no execution behavior**; the destructive capability lands last, behind a
flag that defaults **off**.

### Decisions locked in with the user
- **Recent chips:** add a read-only backend field (`recent_subjects`).
- **Home narrative cards:** **remove** them (the reading-pane "why sorted" banner
  replaces per-item reasoning; the API still returns `category_summaries`, we stop
  rendering them).
- **Unsubscribe action:** the bulk red button **actually unsubscribes** (Release 2).
- **Sidebar:** convert the shared sidebar to the icon rail **globally**.

### Guardrails (apply to every track)
- **Design tokens only** — never hardcode colors/px/fonts ([DESIGN.md](DESIGN.md) ↔
  [tokens.css](frontend/src/styles/tokens.css)). Single fixed Notion theme; **no
  dark-mode/theme toggle** — drop the mockup's "sun" icon.
- **No duplicate files/logic — extend.** Reuse `@briefed/ui` primitives, the
  Dashboard selection pattern, the existing query/mutation hooks, the existing
  List-Unsubscribe parser/repo, and the mark-read side-effecting-action precedent.
- **No hardcoded values** — presentational constants → new `frontend/src/config/`;
  backend tunables → `Settings` / `FeatureConfig`.
- **Centralized animation** — one `Spinner` primitive + `MOTION_PRESETS` in
  `@briefed/ui`; reuse `Motion`/`Skeleton`. No scattered `animate-spin`/off-token
  `transition`.
- **Docs:** Google-style JSDoc on every new/changed TS export (CLAUDE.md §2);
  Google docstrings + Pydantic `Field(description=...)` on every new/changed Python
  symbol (CLAUDE.md §1).
- **OpenAPI is generated** — after any backend schema/endpoint change run
  `make docs` (regenerates [openapi.json](packages/contracts/openapi.json) +
  [schema.d.ts](frontend/src/api/schema.d.ts), pinned to `info.version` 1.0.0).
  **Never hand-edit** either. Do **not** bump `version.json` — that's a separate
  coordinated decision (it would break the `make docs` version pin).
- **Git:** feature branches + PRs; do **not** push/commit without explicit ask
  (CLAUDE.md §4).

### Track order & dependencies
```
Track 1 (recent_subjects, BE) ─┐
                               ├─► Track 3 (Unsubscribe UI, FE) ─► Track 5 (execute UX, FE)
Track 2 (UI redesign+foundations, FE) ─┘                          ▲
Track 4 (execute backend, behind off-flag) ───────────────────────┘
```
Tracks 1 and 2 are independent and can go in parallel. Track 3 consumes Track 1's
field (and degrades gracefully if absent). Track 5 requires Tracks 3 + 4.

---

## Track 1 — `recent_subjects` (backend, ship first, low-risk)

The aggregator already builds `SenderStats.recent_subjects` (≤6, plaintext,
truncated 160 chars, newest-first) in
[aggregator.py](backend/app/services/unsubscribe/aggregator.py) and discards it.
Subjects are **plaintext** in `emails.subject` and already exposed via the email
list API → **no encryption** (store plaintext; unlike the encrypted `rationale_ct`).

1. **ORM** — [models.py](backend/app/db/models.py) `UnsubscribeSuggestion`:
   `recent_subjects: Mapped[list[str]] = mapped_column(StringArray(), nullable=False, default=list)`
   (reuse the existing portable type at [types.py:45](backend/app/db/types.py) —
   same pattern as `Email.to_addrs`/`labels`). Google docstring entry.
2. **Migration** — `make migrate-rev MSG="add recent_subjects to unsubscribe_suggestions"`;
   add the column with `server_default` (`'{}'` PG array / `'[]'` SQLite JSON via
   StringArray) so existing rows backfill cleanly; implement downgrade; run
   `make migrate` to confirm up **and** down.
3. **Write payload + repo** — thread `recent_subjects` through
   `UnsubscribeSuggestionWrite` and `UnsubscribeSuggestionsRepo.upsert`
   ([repository.py](backend/app/services/unsubscribe/repository.py)) from
   `SenderStats.recent_subjects`.
4. **Response schema** — [unsubscribe.py](backend/app/schemas/unsubscribe.py)
   `UnsubscribeSuggestionOut`: `recent_subjects: tuple[str, ...] = Field(default=(), description=...)`.
5. **Handler** — [unsubscribes.py](backend/app/api/v1/unsubscribes.py)
   `list_suggestions`: map `row.recent_subjects` into the DTO.
6. `make docs`; verify the `schema.d.ts` diff.
7. **Tests** — extend `backend/tests/integration/test_unsubscribes_api.py`
   (response includes recent_subjects) and `test_unsubscribe_aggregate.py`
   (persisted on upsert, truncation preserved). `make test`, `ruff`, `mypy`,
   `make coverage`.

---

## Track 2 — UI redesign: home reader + sidebar + shared foundations (PURE UI)

No backend dependency. Includes the animation/config foundations consumed by
Track 3.

### 2.0 Shared foundations
**Animation (`packages/ui`):**
- **`Spinner`** — `packages/ui/src/primitives/Spinner.tsx`. Props
  `{ size?: 'sm'|'md'; label?: string; className? }`. Lucide `Loader2` +
  `animate-spin motion-reduce:animate-none`; icon `aria-hidden`, wrapper
  `role="status"` + sr-only label; inherits `currentColor`. Export from
  [index.ts](packages/ui/src/index.ts).
- **Wire `Spinner` into `Button.loading`** —
  [Button.tsx](packages/ui/src/primitives/Button.tsx) currently only sets
  `aria-busy` (its JSDoc line 20 promises a spinner that was never rendered).
  Render a leading `<Spinner size="sm" />` when `loading` (the existing `gap-2`
  handles spacing), keeping children. This fulfils the documented contract and
  centralizes "processing" feedback for every button (scan, bulk actions, etc.).
  Re-run the UI tests for `loading` consumers (ScanNowButton, mark-selected).
- **`MOTION_PRESETS`** — `packages/ui/src/motion/presets.ts`:
  `Object.freeze({ fadeIn, fadeRise, listItem })` (opacity/translate only; `Motion`'s
  `pace` owns duration/easing → reduced-motion inherited). Export from `index.ts`.
  **List stagger** is done at the call site:
  `rows.map((e,i) => <Motion pace="base" {...MOTION_PRESETS.listItem} transition={{delay:i*LIST_STAGGER_SECONDS}}>)`
  — no separate `StaggerList` component (avoids an undefined abstraction).
- **`WhySortedBanner`** — `packages/ui/src/primitives/WhySortedBanner.tsx` (the
  always-visible purple banner; the existing click-to-expand `WhyBadge` is left
  as-is). Props `{ bucketLabel; reasons: readonly string[]; decisionSource:
  'rule'|'llm'|'hybrid'; confidence: number; needsReview: boolean }`. Renders a
  `bg-accent/10` rounded (`--radius-md`) block, `--accent` text/border: lead
  `Marked {bucketLabel} — {reasons.join(' ')}`; when `needsReview`, append
  "…double-check before acting." Export from `index.ts`.
- **DESIGN.md §7 — "How to animate in Briefed"** (the single documented home):
  wrap motion in `<Motion>` (never raw `motion.div`); use `MOTION_PRESETS` + the
  config stagger; `<Spinner>` for processing, `<Skeleton>` for placeholders; never
  bare `transition`/`transition-colors` (off-token 150ms) — use
  `duration-[var(--motion-fast)] ease-[var(--ease-standard)]`.
- Tests: `Spinner.test.tsx`, `WhySortedBanner.test.tsx`; reduced-motion mirrors
  `Motion.reduced.test.tsx`.

**Config (`frontend/src/config/` — new):**
- `presentation.ts`: `BUCKET_META`/`BUCKET_ORDER` (**moved verbatim** from
  [DashboardPage.tsx:41-47](frontend/src/pages/DashboardPage.tsx); Dashboard then
  imports them), `FILTER_TABS`, `SORTED_BY_LABEL`, `DECISION_SOURCE_LABEL`,
  `SORT_OPTIONS` (display-only — `/emails` has no `sort` param; comment it),
  `LIST_STAGGER_SECONDS=0.03`, `SKELETON_COUNTS={emails:6,senders:4}`,
  `KEYBOARD_HINT` (static text — there is **no** keyboard infra; do not build one).
- All `Object.freeze`/`as const`, typed, JSDoc'd. Never import feature config into
  `packages/ui` (pass values as props).

### 2.1 Home: decompose the 909-line page
Rewrite [DashboardPage.tsx](frontend/src/pages/DashboardPage.tsx) → thin route
shell (<~120 lines) + `frontend/src/features/dashboard/`:

| File | Responsibility |
|---|---|
| `useDashboardData.ts` | Extract **all** current page-body logic **verbatim** (queries `['digest-today']`, `['emails',params]`; markRead optimistic `onMutate/onError/onSettled`; URL `?bucket=&offset=`; `usePullToRefresh`/`useOnlineStatus`/`useFreshnessState`) + new single-selection state. |
| `DigestOverviewBand.tsx` | Title, `FreshnessBadge`, "Synced {relative} · ${cost}", `FilterTabs`, `ScanNowButton`. |
| `FilterTabs.tsx` | 4 pills (All/Must-read/Good-to-read/Ignore). Reuse `bucketCountForDisplay`. Each pill `<button aria-pressed>` whose accessible name contains its label. |
| `EmailReader.tsx` | Responsive: desktop grid `md:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]`; mobile list→stacked detail with "← Back". Branch on `useBreakpoint()`. |
| `EmailListPane.tsx` | Sort label ("Newest", display-only), `EmailListRow` column with `MOTION_PRESETS.listItem` stagger, `PaginationControls` (moved, logic unchanged). |
| `EmailListRow.tsx` | Selectable row: `--accent` unread dot, sender (bold/truncate), right relative time, one-line subject. `<button aria-pressed aria-current>`; selected `bg-accent/10 text-accent` + accent rule; hover `bg-bg-muted`. |
| `ReadingPane.tsx` | Selected-email view (§2.2); wrap body in `<Motion key={email.id} pace="base" {...MOTION_PRESETS.fadeIn}>`. |
| `ReadingPaneActions.tsx` | `Mark Read` (primary, `loading`), `OpenInGmailLink`, `Unsubscribe` (link → `/unsubscribe`), `Next must-read ↓`. |
| `MarkReadStatus.tsx` | Moved verbatim (reauth/error/success + `apiErrorEnvelope`). |
| `DashboardSkeletons.tsx` | `OverviewBandSkeleton`/`ListPaneSkeleton`/`ReadingPaneSkeleton` (replaces `DigestSkeleton`). |

Behavioral change: **bulk select-all removed** (reader is single-select);
`markRead` still takes `emailIds: string[]` called with one id (optimistic path
fully exercised).

### 2.2 Reading-pane wiring (no body endpoint exists)
Category pill ← `bucket`/`BUCKET_META`; "Sorted by your rules" ←
`SORTED_BY_LABEL[decision_source]`; `<h1>` ← `subject`; avatar ← initials from
`sender`; sender line ← `sender`/`account_email`/`formatReceivedLong(received_at)`
(new absolute formatter in config); **why-sorted banner** ← `<WhySortedBanner>`;
**body** ← `summary_excerpt` via `SafeMarkdown` as the lead, **then** a bordered
"This is a preview — Open in Gmail for the full message" callout with
`OpenInGmailLink`. **Skeleton only while `emailsQuery.isPending`** (never fake
permanent bars); null excerpt → callout only.

### 2.3 Selection model (single-select)
URL `?selected=<emailId>` (alongside `?bucket=&offset=`); default first row;
fall back to `emails[0]` if the param isn't in the page. `selectNextMustRead()`
selects the next `must_read` after current; `hasNextMustRead` gates the button.
`markOneRead` captures the next candidate id before mutate then `setSelectedId(next)`.

### 2.4 Removed (home)
Narrative cards (`DigestSummary`/`CategorySummaryCard`), KPI stat cards (→ pills),
the table (`EmailTable`/`EmailTableRow`/`EmailMobileCard`), bulk-select machinery,
`DigestSkeleton`, `formatReceived` (→ `formatReceivedLong` + list relative time),
now-unused imports.

### 2.5 Mobile
`<md`: list-only; tap sets `?selected=`, renders `ReadingPane` full-width above the
hidden list with sticky "← Back". Overview band wraps; pills scroll horizontally;
`ScanNowButton` keeps its mobile card. No AppShell change.

### 2.6 Sidebar icon rail (global; affects History/Settings chrome)
Convert [Sidebar.tsx](frontend/src/shell/Sidebar.tsx) (today `md:w-60`, labeled) to
a narrow icon rail; keep [navItems.ts](frontend/src/shell/navItems.ts) as the
single nav source.
- Width → token-derived narrow (`md:w-16`); keep `bg-sidebar border-r border-sidebar-border`.
- Logo → "B" glyph linking `/`. Each `NavLink` icon-only, centered; active
  `bg-sidebar-active text-sidebar-fg`, inactive `text-sidebar-fg-muted hover:bg-sidebar-hover`.
- **A11y:** every link MUST have `aria-label={item.label}` **and** native
  `title={item.label}`; icons `aria-hidden`. Logout stays bottom, icon-only,
  `aria-label`+`title`, logic verbatim (error → sr-only `role="alert"`).
- **Drop the "sun" icon** (no theme toggle). Render only entries with real
  destinations (`NAV_ITEMS` + logout); do not invent help/avatar routes.
- Replace this file's off-token `transition-colors` with the token-driven form.
- Update [Sidebar.test.tsx](frontend/src/__tests__/Sidebar.test.tsx): swap the
  `getByText('Briefed')` wordmark assertion for the glyph's accessible name; keep
  per-`NAV_ITEMS` link-by-name + active-class + logout; add an icon-only a11y guard
  (every link has a non-empty accessible name + `title`). DESIGN.md sidebar-width
  note (currently "224px") updated.

### 2.7 Home tests
Rewrite [DashboardPage.test.tsx](frontend/src/__tests__/DashboardPage.test.tsx)
preserving coverage on new DOM: overview band; pills change bucket
(`{bucket:'good_to_read',offset:0,limit:25}` etc. unchanged); pagination; row
select→pane; why-sorted banner incl. `needs_review` toggle; pane skeleton;
Next-must-read; **mark-read optimistic removal + selection advance** (replaces the
removed bulk select-all test); reauth 409; auto-scan-off alert; digest error.

---

## Track 3 — Unsubscribe page UI (image 3): cards + multi-select + recommend-only actions (PURE UI)

Ships the full image-3 layout, but the primary action is **capability-driven** and
the execute capability is **off** until Track 5 — so this track is **non-destructive**
(recommend-only, same blast radius as today). New `frontend/src/features/unsubscribe/`;
rewrite [UnsubscribePage.tsx](frontend/src/pages/UnsubscribePage.tsx) as a thin shell.

### 3.1 Components
| File | Responsibility |
|---|---|
| `UnsubscribeSelectionBar.tsx` | Sticky bar: header checkbox (**indeterminate** when partial), "{n} of {total} selected", "Keep selected" (secondary), primary "Unsubscribe N selected" (**destructive/red**, `loading`). Disabled when `n===0`; the primary is also disabled/tooltipped when **offline** (§5) or when the execute capability is off (degrades to recommend-only — see §3.3). |
| `SenderCard.tsx` | Checkbox; initials avatar; `sender_email` (bold) + `sender_domain`; **RECENT chips** (`recent_subjects.slice(0,RECENT_SUBJECTS_DISPLAY)` → `Badge`; render nothing if empty); right stats "{frequency_30d}/mo received · {openedPercent}% opened"; tag badges from `senderTags()`. Selected = `border-accent bg-accent/10`. |
| `SenderCardSkeleton.tsx` | Card-shaped skeleton × `SKELETON_COUNTS.senders`. |
| `unsubscribeDerived.ts` | Pure helpers; thresholds from `config/unsubscribe.ts`. |

### 3.2 Config + derived helpers
- `frontend/src/config/unsubscribe.ts`: `UNSUBSCRIBE_TAG_CONFIG =
  { noisyFreq30d:20, disengagedEngagement:0.10, lowValueWaste:0.70 }`,
  `UNSUBSCRIBE_TAG_TONE`, `RECENT_SUBJECTS_DISPLAY=3`.
  **Important:** these thresholds are **purely presentational** (descriptive
  chips), intentionally distinct from the backend's authoritative recommend
  criteria (volume≥5 / waste≥50% / engagement≤20% in the aggregator). Document this
  in the file header so the two are never conflated.
- `unsubscribeDerived.ts`:
  - `flaggedCount(s) = s.length` (source of truth = what's shown; `hygiene/stats`
    is wired for freshness/future use but does **not** gate the header).
  - `wastedEmailsPerMonth(s) = Math.round(Σ frequency_30d × Number(waste_rate))`
    with `Number.isFinite` guard per term → "~{n} wasted emails / month".
  - `openedPercent(s) = Math.round(Number(engagement_score)*100)`.
  - `senderTags(s)`: noisy/disengaged/low_value per the config thresholds, fixed
    display order.

### 3.3 Actions (recommend-only in this track)
- Mirror the Dashboard selection pattern (`selectedIds:Set`, `toggleSelected`,
  `togglePageSelected`).
- **Single capability-aware primary action** behind the
  `unsubscribeExecute` capability (read from the bootstrap endpoint, §4.4):
  - **capability OFF (this track / prod default):** clicking "Unsubscribe N
    selected" opens each selected sender's `list_unsubscribe.preferred_url` in a new
    tab **on the user's click** (synchronous with the gesture → no popup-blocker
    issues) and fires the existing `POST /confirm` per id to **mark handled**. This
    is exactly today's recommend-only model, just bulk.
  - **capability ON (Track 5):** routes to the `/execute` flow (Track 5 §5).
- **"Keep selected"** → existing `POST /dismiss` per id (`Promise.allSettled`),
  optimistic removal via the shared `removeSuggestionFromCache`.
- Keep `dismiss`/`confirm` offline-capable (local state) via the existing
  `enqueueMutation`. **Do not** add an offline type for execute (Track 5).
- Invalidate `['unsubscribes']` + `['hygiene']` after batches (one hygiene key,
  used consistently).

### 3.4 `/confirm` semantics (clarified, not changed)
`/confirm` is repurposed in copy as **"mark handled / I've unsubscribed"**: it
records that the user completed the unsubscribe themselves. Used by the
recommend-only primary (§3.3) and by Track 5's `manual_required` follow-up. `/dismiss`
remains **"Keep"**. No backend change to either in this track.

### 3.5 States + header + tests
Header: "Unsubscribe suggestions" + `FreshnessBadge` (the existing "FRESH" pill —
reuse, don't reinvent) + subtitle "{flaggedCount} senders flagged · ~{wasted}
wasted emails / month". Loading → `SenderCardSkeleton`; error → `ErrorState`; empty
→ existing `EmptyState`. Cards stagger via `MOTION_PRESETS.listItem`.
Rewrite [UnsubscribePage.test.tsx](frontend/src/__tests__/UnsubscribePage.test.tsx):
derived header counts; per-card stats/tags; selection bar counts + indeterminate;
selected highlight class; **bulk recommend-only** fires N `confirm` POSTs + opens
links; bulk keep fires N dismiss; offline keep/confirm enqueue; RECENT chips from
`recent_subjects`; empty/error/loading. New `unsubscribeDerived.test.ts` (pure
units incl. NaN guard + threshold boundaries).

---

## Track 4 — Backend: execute capability behind an off-flag (ADR 0014 + executor + endpoint)

No user-facing change while the flag is off. Precedent = mark-read
([emails.py](backend/app/api/v1/emails.py)): ownership-checked router → side-effecting
call → state update → typed error envelope.

### 4.1 ADR 0014 first (the policy gate)
`docs/adr/0014-execute-unsubscribe-in-release-2.md` (repo template; Date 2026-06-06;
Status Accepted; Deciders Kartik Hirijaganer; **Supersedes: ADR 0006, for the
unsubscribe action only** — mirrors how ADR 0013 partially superseded 0006 for
mark-read). Decision: execute **only** on explicit per-action confirmation, **only**
via the sender-advertised List-Unsubscribe (RFC 8058 one-click POST; else surface
the link for the user), **online-only**, gated by a feature flag, no new Gmail scope,
no mailbox mutation. Update `docs/adr/README.md` (0006 → "Superseded in part by
0014"; add 0014) and CLAUDE.md §9.

### 4.2 SSRF-safe executor (net new)
`backend/app/services/unsubscribe/executor.py`:
`async def execute_unsubscribe(action, *, http_client, timeout) -> ExecuteOutcome`.
- **Dedicated URL validator** (own function + unit tests):
  - scheme ∈ {http, https} only; reject anything else (incl. `data:`, `file:`).
  - parse host; **resolve DNS and reject if any resolved address is**
    private/loopback/link-local/reserved/CGNAT/metadata — IPv4 (`127/8`, `10/8`,
    `172.16/12`, `192.168/16`, `169.254/16`, `0/8`, `100.64/10`) and IPv6 (`::1`,
    `fc00::/7`, `fe80::/10`, IPv4-mapped). Reject malformed/IDN-suspicious hosts.
- `httpx.AsyncClient(trust_env=False, follow_redirects=False)` — ignore proxy env
  vars; **do not follow redirects** (a 3xx → treat as `manual_required`/`failed`, a
  classic SSRF bypass). Bounded streaming read (cap body, e.g. 64 KB) under the
  configurable timeout. Validate the host **immediately before** the request
  (rebinding mitigation); note pinned-IP connect as optional future hardening.
- **Decision tree:**
  - `one_click` + HTTPS url → `POST` `List-Unsubscribe=One-Click`
    (`application/x-www-form-urlencoded`); 2xx → `unsubscribed (via=one_click)`,
    non-2xx → `failed`.
  - has url but not one-click → `manual_required` + the url (frontend has the user
    complete it).
  - mailto only → `manual_required` + mailto (no `gmail.send` scope; adding it
    triggers Google Restricted-Scope review — out of scope).
- Reuse the `httpx.AsyncClient` context pattern from mark-read; reuse
  `core/errors.py`.

### 4.3 DB state (real lifecycle, not a bool)
`UnsubscribeSuggestion` (migration via `make migrate-rev`, separate from Track 1):
`execute_status: Mapped[str]` (Literal `pending`/`unsubscribed`/`manual_required`/`failed`,
default `pending`), `executed_via: Mapped[str | None]` (`one_click`/`none`),
`execute_attempted_at`, `executed_at`, `execute_error: Mapped[str | None]`,
`manual_url: Mapped[str | None]`. Idempotent: re-executing an already-`unsubscribed`
row is a no-op. On `unsubscribed`, also set `dismissed=True` (drops from active list);
on `manual_required`/`failed`, leave the row active.

### 4.4 Endpoint, schemas, single gate, capability exposure
- [unsubscribes.py](backend/app/api/v1/unsubscribes.py):
  `POST /api/v1/unsubscribes/{suggestion_id}/execute`, handler `execute_suggestion`
  — ownership check (join `ConnectedAccount.user_id`); **gate on
  `FeatureConfig.unsubscribe_execute`** (the single source of truth — same
  `get_app_config()` pattern this file already uses; return 404/403 when off);
  reconstruct `UnsubscribeAction` from stored JSON (reuse `_action_from_json`); call
  executor; persist outcome; return the response model. Require body
  `{confirm: true}`.
- [schemas/unsubscribe.py](backend/app/schemas/unsubscribe.py): frozen
  `UnsubscribeExecuteRequest { confirm: bool = Field(..., description=...) }` and
  `UnsubscribeExecuteResponse { status: Literal["unsubscribed","manual_required","failed"];
  executed_via: Literal["one_click","none"]; manual_url: str | None; message: str }`.
- **Gate (one only):** `FeatureConfig.unsubscribe_execute: bool = False` in
  [app_config.py](backend/app/core/app_config.py). Operational tunable
  `unsubscribe_execute_timeout_seconds: float = 10.0` in
  [config.py](backend/app/core/config.py) `Settings` (`Field(description=...)`; add
  to `_SSM_FIELD_MAP` only if SSM-hydrated). The timeout is **not** a second gate.
- **Expose capability to the frontend:** add an `unsubscribe_execute` boolean to the
  existing frontend bootstrap/config response in
  [frontend.py](backend/app/api/v1/frontend.py) (it already reads
  `get_app_config()`), so the UI can switch the primary action (§3.3 / Track 5)
  without guessing. `make docs` after.
- **Tests** (`respx`): one-click 2xx → unsubscribed; no-one-click → manual_required
  + url; 4xx/5xx → failed; **SSRF rejections** (IPv4/IPv6 private, link-local,
  metadata 169.254.169.254, localhost, malformed, non-http scheme,
  redirect-to-private not followed, oversized body); flag-off → gated; ownership
  isolation; idempotent re-execute. `make coverage` (no regression on pinned-100%).

---

## Track 5 — Frontend execute UX (destructive; ships last, flips behavior behind the capability)

When the bootstrap capability `unsubscribeExecute` is **on**, the primary
"Unsubscribe N selected" action routes here instead of §3.3's recommend-only path.

- **Confirmation gate (required by ADR 0014):** click → `Dialog` ("Unsubscribe from
  N senders? Briefed sends one-click requests where supported; others open for you
  to finish."). Confirm → `Promise.allSettled(ids.map(execute.mutateAsync))` calling
  `POST /api/v1/unsubscribes/{id}/execute {confirm:true}`. `Spinner` in the button
  while busy; clear selection.
- **Online-only:** the primary action is **disabled when offline** with a tooltip
  ("Reconnect to unsubscribe"). **No offline queue for execute** — a destructive
  external action must not replay later without fresh confirmation.
- **Per-result state transitions (no blanket optimistic removal):**
  - `unsubscribed` → remove the card (server already set `dismissed`).
  - `manual_required` → **keep the card**, render an explicit "Open unsubscribe
    page" link/button (from `manual_url`) in the card; after the user opens it they
    click "I've unsubscribed" → `POST /confirm` removes it. **Do not** auto-open
    tabs and **do not** auto-dismiss.
  - `failed` → keep the card, show the error inline, offer retry.
  - Aggregate the batch into a results `Alert`/panel: "X unsubscribed · Y need a
    manual step · Z failed", with the manual links listed explicitly (no tab spam).
- Invalidate `['unsubscribes']` + `['hygiene']` after the batch.
- **Tests:** capability-on renders the execute path; Dialog gates the POSTs; N
  `execute` calls fire; `unsubscribed` removes / `manual_required` keeps + shows
  link / `failed` keeps + error; offline disables the button; manual links are
  rendered (not auto-opened); capability-off still uses §3.3 recommend-only.
- **Enable the flag** (`FeatureConfig.unsubscribe_execute=true`) only after Track 5
  verification passes.

---

## Cross-cutting: dead code

Remove only what each track orphans (confirm no other importer first via
`semantic_search_nodes`/`query_graph` + `npm run lint`):
- Home (Track 2): `DigestSummary`, `CategorySummaryCard`, `KpiButton`, `EmailTable`,
  `EmailTableRow`, `EmailMobileCard`, `CategoryBadge`, `DigestSkeleton`,
  `formatReceived`, bulk-select machinery, now-unused imports.
- Unsubscribe (Track 3): the `score X.XX` badge; the per-card single-action buttons
  (`Keep`/`Open unsubscribe link`/`Mark unsubscribed`) replaced by the bar +
  card-level affordances; consolidate (don't duplicate) `removeSuggestionFromCache`.
- `ScanNowButton` ad-hoc `animate-spin` blocks → `Spinner` (Track 2).
- Off-token `transition-colors` in touched files.

## Cross-cutting: documentation
JSDoc on every new/changed TS export; Google docstrings + Pydantic
`Field(description=...)` on every new Python symbol (executor, schemas, ORM columns,
Settings/FeatureConfig fields, endpoint, frontend-bootstrap capability). DESIGN.md:
"How to animate in Briefed" + icon-rail width + `WhySortedBanner` note. ADR 0014 +
`docs/adr/README.md` + CLAUDE.md §9. `.env.example`: add
`UNSUBSCRIBE_EXECUTE_TIMEOUT_SECONDS` (and note the feature flag lives in
`app_config`). README: no change required (no new top-level dep/dir/command) — state
this explicitly.

---

## Verification (per track; validate before declaring done)

**Backend (Tracks 1, 4):** `make migrate` (up **and** down clean); `make docs`
(diff sane; `info.version` still 1.0.0); `make test` (the canonical filter
`-m "not e2e and not eval"`; or targeted e.g.
`pytest backend/tests/integration/test_unsubscribes_api.py -q`); `ruff format
--check`, `ruff check`, `mypy --strict`; `make coverage` (≥80%, no regression on
the pinned-100% modules).

**Frontend (Tracks 2, 3, 5):** `make bootstrap` first (FRONTEND_READY gate);
`npm run lint`, `npm run format:check`, `tsc -b`/build; `npm test` (vitest — the
rewritten/added suites above).

**Interactive (this harness's `mcp__Claude_Preview__*` tools — use these, not
Browser-MCP):** `preview_start`; `/` vs image 1 (overview band, pills, list,
reading pane, why-sorted banner, skeletons), `preview_click` a row → pane updates,
trigger Scan now → `Spinner` visible, `preview_console_logs`/`preview_network`
clean, `preview_resize` → mobile list→detail→back; `/unsubscribe` vs image 3 (FRESH
badge, subtitle counts, sticky bar, cards, RECENT chips, stats, tags, purple
selected highlight), select → bar count, primary action → (Track 3) opens links +
confirm POSTs / (Track 5) confirm Dialog → `execute` POSTs in `preview_network`,
`manual_required` keeps card + shows link; icon rail on `/`,`/history`,`/settings/*`
(tooltips, active state, logout, **no theme toggle**).

**Automated e2e (optional, repo's own suite):** the repo has Playwright e2e behind
the `e2e` marker / `PLAYWRIGHT=1`; add/extend specs there for the unsubscribe
execute happy-path + manual-required if e2e coverage is desired (gated, opt-in).

---

## Critical files
- Home: [DashboardPage.tsx](frontend/src/pages/DashboardPage.tsx),
  [ScanNowButton.tsx](frontend/src/features/dashboard/ScanNowButton.tsx),
  [DashboardPage.test.tsx](frontend/src/__tests__/DashboardPage.test.tsx)
- Unsubscribe FE: [UnsubscribePage.tsx](frontend/src/pages/UnsubscribePage.tsx),
  [UnsubscribePage.test.tsx](frontend/src/__tests__/UnsubscribePage.test.tsx),
  [offline/mutations.ts](frontend/src/offline/mutations.ts) (keep/confirm only — no execute)
- Unsubscribe BE: [unsubscribes.py](backend/app/api/v1/unsubscribes.py),
  [schemas/unsubscribe.py](backend/app/schemas/unsubscribe.py),
  [aggregator.py](backend/app/services/unsubscribe/aggregator.py),
  [repository.py](backend/app/services/unsubscribe/repository.py),
  [parser.py](backend/app/services/unsubscribe/parser.py),
  new `backend/app/services/unsubscribe/executor.py`,
  [models.py](backend/app/db/models.py), [types.py](backend/app/db/types.py),
  [config.py](backend/app/core/config.py), [app_config.py](backend/app/core/app_config.py),
  [frontend.py](backend/app/api/v1/frontend.py) (capability),
  precedent [emails.py](backend/app/api/v1/emails.py)
- Shell: [Sidebar.tsx](frontend/src/shell/Sidebar.tsx),
  [navItems.ts](frontend/src/shell/navItems.ts)
- UI pkg: [index.ts](packages/ui/src/index.ts),
  [Button.tsx](packages/ui/src/primitives/Button.tsx),
  [Motion.tsx](packages/ui/src/primitives/Motion.tsx),
  [Skeleton.tsx](packages/ui/src/primitives/Skeleton.tsx); new `Spinner.tsx`,
  `WhySortedBanner.tsx`, `motion/presets.ts`
- New FE config: `frontend/src/config/presentation.ts`, `frontend/src/config/unsubscribe.ts`
- Docs: new `docs/adr/0014-execute-unsubscribe-in-release-2.md`,
  [docs/adr/README.md](docs/adr/README.md), [DESIGN.md](DESIGN.md), [CLAUDE.md](CLAUDE.md)
