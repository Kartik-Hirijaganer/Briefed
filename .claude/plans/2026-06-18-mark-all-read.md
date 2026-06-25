# Plan: "Mark all read" — multi-select bulk mark-read on the dashboard

## Context

The dashboard inbox currently lets the user open one email at a time (single-select reader) and mark
**that one** email read via the reading pane's "Mark read" button. There is no way to clear several
emails at once — the user must open and mark each individually.

This change adds a **multi-select "Mark all read" affordance** to the email list: a checkbox on every
row, a select-all checkbox, and a button that marks the selected emails read. Marking read removes the
Gmail `UNREAD` label on the real mailbox (per **ADR 0013**), and — only after Gmail confirms — drops
`UNREAD` from the local `emails.labels`, so the row disappears from Briefed's unread-only list and the
two stay in sync.

**The single most important finding: the backend and the data layer are already done.**
`POST /api/v1/emails/mark-read` has accepted a *batch* of `email_ids` since day one (ADR 0013 designed
it that way — it calls Gmail `users.messages.batchModify`, chunked at 1000 ids with per-item failure
isolation), and the frontend `markRead` mutation in
[useDashboardData.ts](../../frontend/src/features/dashboard/useDashboardData.ts) already takes an
**array** of ids with optimistic removal, rollback, and cache invalidation. This feature is therefore
**a frontend selection-UI change** — no backend route work, no DB migration, no OpenAPI/contract
regeneration, no new design tokens, no new ADR. (One small, recommended backend *test* addition is noted
in §7.)

There is a near-exact in-repo pattern to mirror: the **Unsubscribe page** already implements multi-select
(`selectedIds: Set`, `toggleSelected`, `togglePageSelected`, a sticky select-all bar with an
indeterminate header checkbox). We replicate that shape on the dashboard.

### Decisions locked with the user

| Decision | Choice |
|---|---|
| Interaction model | **Checkboxes on each row + a sticky select-all bar** with an adaptive button. Mirrors the Unsubscribe page. |
| Scope of "all" | **Current page only** (the ≤25 visible rows), sent as explicit `email_ids`. Zero backend change. |
| Confirmation | **None** — mark immediately on click, relying on the optimistic update + the existing feedback banner. |

### One deliberate refinement

The button is **disabled when nothing is selected** (tooltip: "Select emails to mark read"), and the
**select-all checkbox is the path to "mark everything."** Safer model over a one-click that fires on all
visible rows from an empty selection — for a Gmail mutation, making the destructive scope explicit is
worth one extra gesture.

**Button states / label**

| Selection | Enabled? | Label |
|---|---|---|
| none | disabled (tooltip) | "Mark all read" |
| subset (`0 < n < total`) | enabled | "Mark N read" |
| all visible | enabled | "Mark all read" |
| any, but offline or pending | disabled / loading (tooltip "You're offline") | unchanged |

---

## Non-negotiable constraints (already enforced; keep them true)

- **Explicit user action only** — never mark read on open/scroll/scan/summarize. Only on the button.
- **Gmail is source of truth** — local `emails.labels` changes only for ids the provider reports as
  `marked` (the route already does this).
- **Narrow write scope** — `removeLabelIds: ["UNREAD"]` only. The Gmail client already rejects anything else.
- **Valid HTML / a11y** — do **not** nest a checkbox inside the row `<button>`; split into sibling controls.
- **Design system** — read DESIGN.md; tokenized classes only; no new colors/px/fonts; no Checkbox
  primitive (use the native-checkbox + indeterminate-ref pattern already in the repo).
- **PWA offline** — do **not** queue mark-read; **disable** the action offline.
- **Git** — no commit/push.

---

## What already exists and is reused (do not rebuild)

| Asset | Path | Reuse |
|---|---|---|
| Batch mark-read endpoint | `POST /api/v1/emails/mark-read` (backend/app/api/v1/emails.py) | Accepts `email_ids: tuple[UUID]`; groups by account; Gmail `batchModify`; drops local `UNREAD` only for `marked`; returns `{marked, failed}`. **No change.** |
| `markRead` mutation (array input + optimistic) | useDashboardData.ts:156 | `markRead.mutate({ emailIds: [...] })` filters the cache, decrements total, rolls back on error, invalidates `['digest-today']` + `['emails']` on settle. **Reuse.** |
| Feedback banner | MarkReadStatus.tsx | Already renders partial-failure, success, generic errors, and the Gmail re-auth recovery. **No change.** |
| Multi-select reference | useUnsubscribeData.ts:204 + UnsubscribeSelectionBar.tsx | Copy the `toggle/toggleAll/clear` shape + sticky bar with indeterminate-via-`useEffect`-ref. |
| `Button` primitive | `@briefed/ui` (packages/ui/src/primitives/Button.tsx) | `variant="primary" size="sm" loading disabled title`. |

---

## Frontend changes

### 1. useDashboardData.ts — bulk-selection state + action
- `import { useEffect, useMemo, useState } from 'react';`
- `selectedIds` state; derived `visibleIds`, `selectedVisibleIds`, `selectedCount`, `allSelected`, `someSelected`.
- Prune effect: drop selected ids not in `visibleIds` when `emails` changes (Scan Now refetch).
- `toggleSelected`, `toggleAllSelected`, `clearSelection`.
- `markSelectedRead`: mark `selectedVisibleIds`; if the reader's `selectedId` is in the set, advance to
  next surviving row (then previous, then null) before removal; `clearSelection()`; `markRead.mutate(..., { onError: restore previousSelection })`.
- Reset selection inside `setBucket`/`setOffset`.
- Expose all on `DashboardData` (JSDoc each).

### 2. EmailSelectionBar.tsx — NEW
Sticky bar modeled on `UnsubscribeSelectionBar`: select-all checkbox (indeterminate via ref+useEffect),
count label (`{selectedCount} selected` else `{total} unread`), and primary Button labeled
`selectedCount > 0 && !allSelected ? 'Mark N read' : 'Mark all read'`.

### 3. EmailListRow.tsx — leading checkbox (split controls)
Flex container with a sibling `<input type="checkbox">` (`aria-label="Select email from {sender}: {subject}"`)
+ the existing body `<button>`. New props `bulkSelected`, `onToggleBulk`. Keep accent + aria on the button.

### 4. EmailListPane.tsx — render bar, wire rows
Extend props with selection state + bar handlers + `online`. Render `<EmailSelectionBar>` in the
`emails.length > 0` branch with `indeterminate={someSelected && !allSelected}`,
`markReadDisabled={selectedCount === 0 || !online || markReadLoading}`, and tooltip. Pass
`bulkSelected`/`onToggleBulk` per row. Fold the `{total} unread` count into the bar; keep sort caption.

### 5. EmailReader.tsx — thread props from `data` into the list pane; pass `online` to reading pane.

### 6. ReadingPaneActions.tsx — disable single Mark read offline (parity).

### 7. DashboardPage.tsx — no change (bulk reuses `data.markRead`).

### Optional hardening (not required)
Switch `onMutate`/`onError` to `getQueriesData`/`setQueriesData(['emails'])` to span all cached email
views immediately. Marginal given `onSettled` invalidation already refetches; leaving as-is is fine.

---

## Edge cases
Empty list → bar hidden. Nothing selected → button disabled (tooltip). Offline → both buttons disabled,
not queued. Paging/bucket switch → selection cleared. In-place refetch → prune effect. Reader email in
set → advance before removal. Error → cache rollback + selection restore. Partial failure → failed rows
reappear on refetch; banner reports counts. 409 → existing reconnect flow. Idempotency/large batches →
handled server-side.

---

## Out of scope
Backend route/provider/schemas (already batch-capable), DB/Alembic, OpenAPI regen (**do not run `make docs`**),
DESIGN.md/tokens, new ADR. Deferred: category-across-pages (needs confirm modal), mailbox/all-accounts,
cross-page selection persistence, offline-queued mark-read.

---

## Backend: recommended test hardening (small, existing helpers)
In backend/tests/integration/test_emails_api.py, confirm/add: multiple ids (one account), **partial
provider failure** (marked loses UNREAD, failed keeps it + reported), multi-account grouping. Existing
tests cover single-id, category, unowned 404, exactly-one-selector 422, and 409 reconnect.

---

## Testing & verification (frontend)
Mirror DashboardPage.test.tsx / UnsubscribePage.test.tsx patterns (vi.hoisted api mock + QueryClientProvider
+ MemoryRouter + userEvent). Cover: checkboxes + select-all/indeterminate; adaptive label + disabled-at-0;
correct `email_ids` POST; optimistic removal; partial failure banner; error rollback + selection restore;
reset on bucket/page; **a11y independence** (checkbox doesn't open reader, body does); offline disabled.

### Commands
```bash
make bootstrap                          # only if frontend/package-lock.json is missing
cd frontend && npm run lint
cd frontend && npm run format:check
cd frontend && npm run test
pytest backend/tests/integration/test_emails_api.py -q -m "not e2e and not eval"
make test
```

### Manual (preview tools)
`docker compose up -d`, `preview_start`, load `/`, snapshot, select rows ("Mark 2 read"), select-all
("Mark all read"), click → snapshot (rows gone) + network (correct `email_ids`) + screenshot.

---

## Implementation order
1. useDashboardData (state, prune, reset, markSelectedRead).
2. EmailSelectionBar (new) + EmailListRow checkbox split.
3. EmailListPane + EmailReader + ReadingPaneActions wiring.
4. Frontend tests + backend tests.
5. Quality gates + manual preview.

---

## Acceptance criteria
- Select ≥1 visible unread email; button marks exactly those via `POST /api/v1/emails/mark-read` with the
  selected `email_ids`.
- Gmail gets `removeLabelIds: ["UNREAD"]` only; locally only provider-confirmed ids lose `UNREAD`.
- Marked rows disappear; failed rows remain/reappear; banner reports both.
- Re-auth flow works; action disabled offline.
- Checkbox and row-open button are separate accessible controls; single reader Mark read still works;
  filters/pagination/reader selection unaffected.
- All tests pass; no commits/pushes.
