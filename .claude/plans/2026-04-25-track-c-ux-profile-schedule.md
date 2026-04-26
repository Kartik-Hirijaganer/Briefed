# 2026-04-25 — Track C: UX overhaul (design system + profile + schedule)

Two PR-sized phases that ship in order.

- **Phase Group I — Design system + theme + version.** `DESIGN.md`,
  CSS tokens, theme switching, self-hosted fonts, single-source app
  version. Independent of any backend work.
- **Phase Group II — Profile + schedule.** Schema migration, profile
  API, scheduling helper with explicit idempotency, EventBridge
  cadence, settings UI built on the Group I tokens.

**Independent of Tracks A and B.** Profile fields are *consumed* by
Track B's IdentityScrubber once both have shipped — that's a one-line
swap at the Briefed factory site.

---

## Locked decisions

### Design system

1. **`DESIGN.md` at repo root is canonical.** Agents read it before
   any UI change (enforced via a CLAUDE.md rule).
2. **Inter Display + Inter + JetBrains Mono are self-hosted.** Loading
   from Google Fonts CDN logs IPs upstream — inconsistent with Track
   B's privacy stance. Bundled as static assets in
   `frontend/public/fonts/`.
3. **Token migration is full, not partial.** Either every primary
   surface uses the new tokens or none do. No "migrate dashboard +
   accounts only" half-step (that guarantees a hybrid look forever).
4. **Theme defaults to `system`.** A small inline `<script>` in
   `index.html` reads `localStorage('briefed.theme')` and applies
   `data-theme` *before* React or CSS loads (FOUC mitigation, snippet
   below).
5. **App version is `packages/contracts/version.json`.** Backend
   OpenAPI pin and frontend `APP_VERSION` both read from it.

### Profile + schedule

6. **All user-tunable values live in the user profile**, not env vars:
   display name, email aliases, redaction aliases, schedule frequency,
   schedule times, timezone, theme preference, presidio toggle. Env
   vars stay for infra config only (API keys, runtime mode).
7. **One slot-matching predicate, defined once.** A pure function
   `is_due(now_utc, profile) -> bool` is the *only* place that decides
   whether a user runs in this tick. Consumed by both the fanout
   filter and the "next run preview" UI.
8. **Idempotency via run-id lock.** A new `current_run_id` column on
   the user row is set when fanout enqueues; cleared on success *or*
   timeout. A second tick with `current_run_id IS NOT NULL` skips the
   user. Crash-mid-pipeline does not double-fire.
9. **EventBridge fires every 15 minutes** (not 30). Slot precision is
   `±7.5min`. The current plan's 30/15 mismatch was a bug in the
   original.
10. **Skipped slots are not re-run.** If the worker is down at the
    user's 08:00 slot and recovers at 08:45, we do *not* fire late.
    Wait for the next natural slot. (Predictable behavior > eager
    catch-up; safer for a recommend-only system.)

## Out of scope (here)

- Library extraction.
- Storybook / visual regression.
- Streaming responses.
- Multi-user.

---

## Phase Group I — Design system, theme, version

### I.1 — `DESIGN.md`

- [ ] New file [DESIGN.md](../../DESIGN.md) at repo root.
- [ ] Sections (awesome-design-md format): theme/atmosphere, color,
  typography, components, layout, depth/elevation, do's-and-don'ts,
  responsive, agent-prompt guide.
- [ ] Token palettes for both `light` and `dark` modes.
- [ ] All accent + status colors verified AAA on `bg.canvas` and AA on
  `bg.surface` (WCAG). Use a contrast checker — log the numbers in the
  doc.

### I.2 — CLAUDE.md rule

- [ ] Add §2 bullet to [CLAUDE.md](../../CLAUDE.md): "Before any UI
  change, read [DESIGN.md](DESIGN.md) and use only the tokens defined
  there. Do not introduce new colors, fonts, or spacing values without
  updating DESIGN.md in the same change."
- [ ] Add §10 (new): DESIGN.md is the canonical design source of
  truth.

### I.3 — Self-hosted fonts

- [ ] Download Inter Display, Inter, JetBrains Mono variable fonts
  (OFL-licensed).
- [ ] Place under `frontend/public/fonts/`.
- [ ] Add `@font-face` declarations to `frontend/src/styles/fonts.css`
  with `font-display: swap`.
- [ ] Verify license attribution lives in `frontend/public/fonts/LICENSE`.

### I.4 — CSS tokens

- [ ] New file `frontend/src/styles/tokens.css`:

  ```css
  :root {
    --bg-canvas: #FAFAFB;
    /* ...all light tokens... */
  }
  [data-theme="dark"] {
    --bg-canvas: #0A0A0F;
    /* ...all dark tokens... */
  }
  ```

- [ ] Tailwind config consumes them: `theme.extend.colors = { 'bg-canvas': 'var(--bg-canvas)', ... }`.
- [ ] Imported once from [frontend/src/main.tsx](../../frontend/src/main.tsx).

### I.5 — FOUC mitigation

- [ ] Inline `<script>` block in `frontend/index.html`, **before** any
  CSS link or JS module:

  ```html
  <script>
    (function () {
      try {
        var pref = localStorage.getItem('briefed.theme') || 'system';
        var resolved = pref === 'system'
          ? (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
          : pref;
        document.documentElement.setAttribute('data-theme', resolved);
      } catch (e) {}
    })();
  </script>
  ```

- [ ] This runs synchronously at parse time, before any token-consuming
  CSS loads. Failure mode is silent (light wins by default).

### I.6 — `useTheme` hook

- [ ] New file `frontend/src/hooks/useTheme.ts`.
- [ ] Returns `{ resolved: 'light' | 'dark', preference: 'system' | 'light' | 'dark', setPreference }`.
- [ ] Reads `localStorage('briefed.theme')`; falls back to `'system'`.
- [ ] When preference is `'system'`, listens on
  `window.matchMedia('(prefers-color-scheme: dark)')` and updates
  `<html data-theme="…">` and `<meta name="theme-color">` immediately
  on flip.
- [ ] Once auth resolves, hydrates from `user.theme_preference` (server
  overrides client). Mutating preference PATCHes `/profile/me`.
- [ ] Tests (vitest + jsdom): defaults to system, switches when media
  query flips, persists to localStorage, resyncs after profile load.

### I.7 — `<ThemeToggle>` component

- [ ] New file `frontend/src/components/ThemeToggle.tsx`. Three-state
  segmented control: System / Light / Dark.
- [ ] Used in Group II Settings UI and the user menu.
- [ ] Tests: cycles correctly, calls profile mutation.

### I.8 — Version display

- [ ] New file [packages/contracts/version.json](../../packages/contracts/version.json):
  `{ "version": "1.0.0" }`.
- [ ] Backend: [backend/app/api/v1/frontend.py](../../backend/app/api/v1/frontend.py)
  reads from this file at module import (matches the existing
  OpenAPI pin pattern).
- [ ] Frontend: [frontend/vite.config.ts](../../frontend/vite.config.ts)
  exposes `APP_VERSION` via
  `define: { __APP_VERSION__: JSON.stringify(versionJson.version) }`.
- [ ] New file `frontend/src/components/AppVersion.tsx` — single
  `<span class="font-mono text-muted text-xs">v{APP_VERSION}</span>`.
- [ ] Placed in app shell footer (right-aligned) and Settings page
  header.

### I.9 — Full token migration

- [ ] Sweep every primary surface: app shell, dashboard, accounts,
  settings, login, errors. All hardcoded colors → tokens.
- [ ] Visual diff vs. main on each route — fix anything that looks
  wrong.
- [ ] Snapshot tests updated.

### I.10 — Tests + docs

- [ ] `frontend/src/__tests__/useTheme.test.ts`.
- [ ] `frontend/src/__tests__/ThemeToggle.test.tsx`.
- [ ] `frontend/src/__tests__/AppVersion.test.tsx`.
- [ ] [README.md](../../README.md) mentions `DESIGN.md` and the
  version-bump workflow.

**Phase Group I exit**: themes auto-switch with system preference,
`v1.0.0` visible in shell + Settings, every primary surface uses
tokens, no FOUC observed.

---

## Phase Group II — Profile + schedule

### II.1 — Alembic migration

One revision adds:

| Column | Type | Default | Purpose |
|---|---|---|---|
| `display_name` | `text` | nullable | IdentityScrubber name |
| `email_aliases` | `text[]` | `'{}'` | Extra emails to scrub |
| `redaction_aliases` | `text[]` | `'{}'` | Free-form strings to scrub |
| `schedule_frequency` | `text` (`once_daily` \| `twice_daily` \| `disabled`) | `'once_daily'` | Cadence |
| `schedule_times_local` | `text[]` | `'{08:00}'` | `HH:MM` in local tz |
| `schedule_timezone` | `text` | `'UTC'` | IANA tz |
| `presidio_enabled` | `boolean` | `true` | Add Presidio to chain |
| `theme_preference` | `text` (`system` \| `light` \| `dark`) | `'system'` | UI override |
| `last_run_finished_at` | `timestamptz` | nullable | Schedule cursor |
| `current_run_id` | `text` | nullable | Idempotency lock |
| `current_run_started_at` | `timestamptz` | nullable | Lock timeout cursor |

CHECK constraint:
`(schedule_frequency = 'once_daily' AND array_length(schedule_times_local, 1) = 1) OR
 (schedule_frequency = 'twice_daily' AND array_length(schedule_times_local, 1) = 2) OR
 (schedule_frequency = 'disabled')`.

### II.2 — Slot-matching predicate

- [ ] New file `backend/app/core/scheduling.py`.
- [ ] Pure functions:

  ```python
  def is_due(now_utc: datetime, profile: UserScheduleView) -> bool: ...
  def next_slot_utc(now_utc: datetime, profile: UserScheduleView) -> datetime | None: ...
  ```

- [ ] `is_due` returns True iff:
  - schedule is not `disabled`
  - **any** of `schedule_times_local` falls within `±7.5min` of
    `now_utc` (when interpreted via `schedule_timezone`)
  - `last_run_finished_at IS NULL OR last_run_finished_at < (now_utc - 1 hour)`
  - `current_run_id IS NULL OR current_run_started_at < (now_utc - 30 min)` (stale lock)
- [ ] **This is the only function that decides "should this user run
  now?"** Both fanout and the "next run preview" UI consume it.
- [ ] Unit tests: cross-tz, DST spring-forward + fall-back,
  once vs twice, disabled, stale-lock recovery, last-run-finished
  lockout.

### II.3 — Profile API

- [ ] New module `backend/app/api/v1/profile.py`.
- [ ] Endpoints:
  ```
  GET   /api/v1/profile/me
  PATCH /api/v1/profile/me
  GET   /api/v1/profile/me/schedule    # frequency, times_local, timezone, next_run_at_utc preview
  PATCH /api/v1/profile/me/schedule
  ```
- [ ] Validation (Pydantic):
  - Each time matches `^([01]\d|2[0-3]):[0-5]\d$`.
  - `timezone` ∈ `zoneinfo.available_timezones()`.
  - `email_aliases` valid email syntax (IDN-aware).
  - `theme_preference` ∈ `{system, light, dark}`.
  - `schedule_frequency` / `len(times_local)` consistency.
- [ ] Wired into [backend/app/main.py](../../backend/app/main.py).

### II.4 — Fanout filter

- [ ] [backend/app/lambda_worker.py](../../backend/app/lambda_worker.py)
  `fanout_handler` selects users where the SQL equivalent of `is_due`
  holds. Keep the SQL filter narrow; recheck `is_due` in Python after
  loading the row to avoid edge cases (UTC rounding).
- [ ] On enqueue: set `current_run_id` to the message id and
  `current_run_started_at = now()`.
- [ ] On final-stage completion: clear both `current_run_*` columns and
  set `last_run_finished_at = now()`.
- [ ] On any worker exception: do *not* clear the lock; let the 30-min
  stale-lock window release it.

### II.5 — EventBridge cadence

- [ ] Update Terraform under [infra/terraform/](../../infra/terraform/)
  to fire fanout every 15 minutes UTC (was 30 in the prior plan; the
  ±7.5min slot-window math requires 15).
- [ ] Plan + apply via the existing workflow.

### II.6 — Settings UI

- [ ] [frontend/src/pages/settings/AccountsPage.tsx](../../frontend/src/pages/settings/AccountsPage.tsx)
  gains:
  - Profile section (display name, email aliases, redaction aliases).
  - Schedule section (radio: once/twice/disabled, time pickers,
    timezone dropdown, "next run" preview computed from `next_slot_utc`).
  - Appearance section using `<ThemeToggle>` from Group I.
  - Privacy section (Presidio toggle).
  - Page header shows `<AppVersion>` from Group I.
- [ ] Built on Group I tokens.
- [ ] React Query invalidates the user profile cache on success;
  `useTheme` resyncs with the new `theme_preference`.

### II.7 — "Run now" path

- [ ] Existing manual-run endpoint continues to bypass the schedule
  filter but still respects the run-id lock (set + clear).

### II.8 — Tests

- [ ] `tests/unit/test_scheduling.py` — `is_due` + `next_slot_utc`
  across DST, leap day, lock semantics.
- [ ] `tests/unit/test_profile_validation.py` — invalid tz, bad time
  format, length mismatch, theme enum, IDN email.
- [ ] `tests/integration/test_profile_api.py`.
- [ ] `tests/integration/test_fanout_schedule_filter.py` — verifies
  `is_due` is the single source of truth.
- [ ] `frontend/src/__tests__/SettingsPage.test.tsx`.

**Phase Group II exit**: user can change schedule, theme, and privacy
from the UI; lock semantics provably idempotent under crash; one slot
predicate consumed by fanout and UI.

---

## Risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Theme flicker on first paint (FOUC) | Med | Low | Inline script in `<head>` before CSS; tested via visual smoke |
| Token contrast fails WCAG | Low | Med | Verify all combinations in Group I.1 with a contrast checker; numbers in DESIGN.md |
| Schedule clock drift / DST bugs | Med | Med | `is_due` unit-tested across DST; `zoneinfo` not pytz |
| Crash-mid-pipeline double-fires | Med | Med | `current_run_id` lock + 30-min stale-lock release |
| Skipped slot is silently dropped | Med | Low | Documented behavior; user can manual-run |
| Partial token migration leaves hybrid look | Med | Low | Phase I.9 is a single sweep; PR blocks until done |
| Version drift between OpenAPI + frontend | Low | Low | Single source: `packages/contracts/version.json` |
| Inter Display licensing | Low | Low | Self-hosted with OFL attribution |

## Estimated effort

| Phase | Effort |
|---|---|
| I.1 — DESIGN.md | ½ day |
| I.2 — CLAUDE.md rule | 10 min |
| I.3 — Self-hosted fonts | ¼ day |
| I.4 — CSS tokens | ¼ day |
| I.5 — FOUC script | 10 min |
| I.6 — useTheme hook | ¼ day |
| I.7 — ThemeToggle | ¼ day |
| I.8 — Version display | ¼ day |
| I.9 — Full token migration | 1 day |
| I.10 — Tests + docs | ¼ day |
| **Group I subtotal** | **~3 days** |
| II.1 — Alembic migration | ¼ day |
| II.2 — Slot predicate | ½ day |
| II.3 — Profile API | ½ day |
| II.4 — Fanout filter | ½ day |
| II.5 — EventBridge cadence | ¼ day |
| II.6 — Settings UI | 1 day |
| II.7 — Run-now path | ¼ day |
| II.8 — Tests | ½ day |
| **Group II subtotal** | **~3.5 days** |

**Total: ~6.5 days**, shippable as two PRs (Group I first).
