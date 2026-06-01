# Briefed — Notion-style UI/UX Theme Revamp

> **Plan doc.** Canonical copy lives at `.claude/plans/2026-06-01-notion-ui-theme-revamp.md`
> and is mirrored to `.codex/plans/2026-06-01-notion-ui-theme-revamp.md` (Briefed keeps both
> in sync, per CLAUDE.md §3 / AGENTS.md §3). This is a planning document only — no code has
> been changed yet.

---

## Context

Briefed's UI is a generic blue-accent "editorial inbox" with a full light/dark/system theme
system. We are re-skinning it to the **Notion design language** (authoritative spec:
[VoltAgent/awesome-design-md → notion/DESIGN.md](https://github.com/VoltAgent/awesome-design-md/blob/main/design-md/notion/DESIGN.md),
surfaced via [getdesign.md/notion](https://getdesign.md/notion/design-md)): warm off-white
surfaces, charcoal text, the signature **purple `#5645d4`** accent, a distinct **link blue
`#0075de`**, soft hairline-driven elevation, 8px buttons / 12px cards, and Notion-Sans —
which is Inter-based, and Briefed already self-hosts Inter, so **no new fonts**.

**Three confirmed product decisions** (asked & answered):
1. **Single fixed theme** — collapse light/dark/system to one look; delete the toggle + all
   dark-mode machinery.
2. **Dark sidebar / light main** — desktop sidebar uses a **warm charcoal `#191919`**; all
   main content stays light (Notion warm-white). *(Navy was considered and rejected.)*
3. **All-Inter typography** — keep self-hosted Inter / Inter Display (spec-accurate, no CDN).

**Why now / outcome.** The recent `daily-triage-revamp` left dead frontend code behind. We
fold the re-skin, a dead-code cleanup, and a **centralization pass** (one token source, not
two) into one change, plus durable rules so Claude *and* Codex agents keep to the new theme.

**Non-negotiable principle: centralize, do not duplicate.** Today two token files exist —
`frontend/src/styles/tokens.css` (the one that actually loads) and the **unused, divergent**
`packages/ui/src/tokens.css` (e.g. `--color-fg #18181b` vs the live `--fg #101014`). After
this change, token **values live in exactly one runtime sheet**, documented in exactly one
spec (DESIGN.md), mirrored once into Tailwind, consumed everywhere by name. The
dark-sidebar/light-main split is expressed purely as a semantic `--sidebar-*` token group.

### Verified facts shaping this plan (read-only investigation)
- `main.tsx` imports `./styles/tokens.css`, `./styles/fonts.css`, `./index.css` — the app
  loads **only** `frontend/src/styles/tokens.css`. `packages/ui/src/tokens.css` is **aliased
  in `vite.config.ts` but never imported** → unused, stale, safe to delete.
- **No Storybook** anywhere (no `.storybook/`, no dep) → nothing needs the package sheet standalone.
- `packages/ui/package.json` `exports` maps `"./tokens.css": "./src/tokens.css"` (dead export).
- **Knip is configured** (`knip.json` + `frontend` `dead-check: knip` script) → use it to confirm orphans.
- `lucide-react` is **not** a dependency; nav/empty-state icons are emoji/string glyphs today.
- PWA manifest in `vite.config.ts` sets `theme_color`/`background_color` to `#09090b` (dark) —
  must change with the meta tag.
- Offline replay (`offline/db.ts` + `offline/mutations.ts`) has a live `email_bucket_update`
  mutation type + replay + invalidation. The **hook** `useEmailBucketMutation.ts` is its only
  enqueuer and is imported by **nothing but its own test** → hook is dead; the type/replay/endpoint stay.
- FOUC script SHA-256 is pinned in **both** `frontend/index.html` and
  `backend/app/core/security_headers.py` (`_FOUC_SCRIPT_HASH`).

---

## Token mapping — Notion → Briefed (the single source)

All values land in **`frontend/src/styles/tokens.css` `:root`** (one block only — no
`[data-theme='dark']`, no `@media (prefers-color-scheme: dark)`) and are documented in
DESIGN.md §2. Verify every text/background pair with WebAIM and update the DESIGN.md §2
contrast table before merge.

### Main content — light (Notion warm neutrals)
| Token | New value | Notion source | Role |
|---|---|---|---|
| `--bg-canvas` | `#fafaf9` | surface-soft | Page background (warm off-white) |
| `--bg-surface` | `#ffffff` | canvas | Cards, modals, popovers |
| `--bg-muted` | `#f6f5f4` | surface | Chips, code, secondary fills |
| `--border` | `#e5e3df` | hairline | Dividers, card outlines |
| `--border-strong` | `#c8c4be` | hairline-strong | Inputs, pressed states |
| `--fg` | `#37352f` | charcoal | Primary text (signature Notion ink; `#1a1a1a` available for max-contrast headings) |
| `--fg-muted` | `#5d5b54` | slate | Secondary / metadata |
| `--fg-faint` | `#787671` | steel | Tertiary hints (verify ≥4.5 if essential) |
| `--fg-on-accent` | `#ffffff` | on-primary | Text on accent/purple |

### Accent, link, status (Notion separates accent ≠ link — do **not** mix)
| Token | New value | Notion source | Role |
|---|---|---|---|
| `--accent` | `#5645d4` | primary (purple) | Primary buttons, active nav, focus |
| `--accent-hover` | `#4534b3` | primary-pressed | Hover/pressed |
| **`--link`** (NEW) | `#0075de` | link-blue | Inline text links only (use `#005bab` for body links if 4.5 fails) |
| `--success` | `#1aae39` | semantic-success | Healthy / confirm |
| `--warn` | `#dd5b00` | semantic-warning | Warning fills/icons (text: deepen to `#793400` for AA) |
| `--danger` | `#e03131` | semantic-error | Destructive / errors |
| `--focus-ring` | `rgba(86,69,212,0.45)` | derived | Focus ring |
| `--overlay-scrim` | `rgba(25,25,25,0.45)` | — | Dialog/sheet scrim |

### Sidebar group — dark charcoal (NEW; centralization keystone)
Consumed **only** by `Sidebar.tsx` (desktop). The single place "dark sidebar" is defined.
| Token | Value | Role |
|---|---|---|
| `--sidebar-bg` | `#191919` | Desktop sidebar surface (warm near-black) |
| `--sidebar-bg-elevated` | `#202020` | Active/hover row background |
| `--sidebar-fg` | `#f7f6f3` | Active / primary label — AAA on `#191919` |
| `--sidebar-fg-muted` | `#a4a097` | Inactive labels, section headers — AA on `#191919` |
| `--sidebar-border` | `#2f2f2e` | Sidebar dividers / right edge |
| `--sidebar-hover-bg` | `rgba(255,255,255,0.05)` | Hover row |
| `--sidebar-active-bg` | `rgba(255,255,255,0.08)` | Active row |
| `--sidebar-accent` | `#9a7cf0` | Active indicator (lightened purple, reads on dark) |

> **Mobile `BottomTabBar` stays light** — it is the mobile main chrome, not a sidenav. "Dark
> sidenav" applies to the desktop sidebar only; a light bottom bar keeps the mobile app cohesive.

### Radius, shadow, type, spacing
- **Radius**: `--radius-sm 6px` (was 4), `--radius-md 8px` (buttons), `--radius-lg 12px`
  (was 16; cards), add `--radius-xl 16px`, `--radius-full 9999px`.
- **Shadow** (Notion is low/soft, border-driven — *cards rest with a hairline border, no shadow*):
  `--shadow-1 0 1px 2px rgba(15,15,15,0.04)`, `--shadow-2 0 4px 12px rgba(15,15,15,0.08)`,
  `--shadow-3 0 24px 48px -8px rgba(15,15,15,0.20)` (popovers/modals only).
- **Typography**: keep Inter / Inter Display. Add `--tracking-tight -0.01em`,
  `--tracking-tighter -0.02em` for large display headings (Notion uses negative tracking).
  Headings weight 600, medium 500, body 400.
- **Spacing**: keep `--space-1..16`; optionally add `--space-5 20px`, `--space-10 40px`.

---

## Phases

### Phase 0 — Spec & token foundation (single source of truth)
1. **DESIGN.md** — rewrite §1 (single fixed theme; explicitly *no dark mode / no toggle*),
   §2 (new palette + `--link` + `--sidebar-*` group + refreshed contrast table), §3 (tracking
   tokens), §4 (component specs to Notion), §5 (radius), §6 (shadow: cards border-only at rest),
   §12 (agent guide — see Phase 7). Canonical token path stays `frontend/src/styles/tokens.css`.
2. **`frontend/src/styles/tokens.css`** — collapse to one `:root`: Notion light palette +
   `--sidebar-*` + radius/shadow/tracking. **Delete** the `[data-theme='dark']` and
   `@media (prefers-color-scheme: dark)` blocks; set `color-scheme: light`. Keep the legacy
   `--color-*` aliases (primitives resolve through them) pointing at the new canonical vars.
3. **De-duplicate (core "no duplication" action)** — **delete** the unused, divergent
   `packages/ui/src/tokens.css`; remove its `"./tokens.css"` entry from `packages/ui/package.json`
   `exports`; remove the dead `@briefed/ui/tokens.css` alias from `frontend/vite.config.ts`.
   (Keep the `@briefed/ui` → `index.ts` and `@briefed/contracts` aliases.) End state: one runtime
   sheet, zero divergent hex. *(Diverges from the teammate's "promote the package sheet" — that
   file is unused and there's no Storybook, so promoting it would move the live file + rewire
   `main.tsx` for no benefit; deleting it removes real dead code + a footgun.)*
4. **`frontend/src/index.css` `@theme`** — add Tailwind utilities for the new tokens:
   `--color-sidebar`, `--color-sidebar-fg`, `--color-sidebar-fg-muted`, `--color-sidebar-border`,
   `--color-link`, `--radius-xl`. Keep existing mappings + base rules.

### Phase 1 — Collapse the theme system (delete dark-mode machinery)
1. **Delete** `frontend/src/hooks/useTheme.ts`, `frontend/src/components/ThemeToggle.tsx`, and
   tests `frontend/src/__tests__/useTheme.test.ts`, `…/ThemeToggle.test.tsx`.
2. **`frontend/index.html`** — remove the inline FOUC `<script>` + comment (nothing to resolve);
   remove the `'sha256-fR2NY…'` token from the meta CSP `script-src`; set
   `<meta name="theme-color" content="#fafaf9">` and `<meta name="color-scheme" content="light">`.
   Consider `apple-mobile-web-app-status-bar-style: default` (was black-translucent).
3. **`backend/app/core/security_headers.py`** — remove `_FOUC_SCRIPT_HASH`; reduce directive to
   `script-src 'self'`; update the docstring. Update `backend/tests/integration/test_security_headers.py`
   if it asserts the hash.
4. **`frontend/vite.config.ts`** — set PWA `manifest.theme_color` and `background_color` to
   `#fafaf9` (light canvas).
5. **`frontend/src/pages/settings/PreferencesPage.tsx`** — remove the `useTheme`/`ThemeToggle`
   imports, the `hydrateFromProfile` effect (lines ~57–59), and the entire **Appearance** `<Card>`
   (lines ~117–128). Grid drops to the remaining cards.
6. Remove any other `data-theme` / `prefers-color-scheme` / `briefed.theme` references (docs,
   README, `packages/ui/README.md` light/dark note).

### Phase 2 — Re-skin the shell (dark sidebar / light main)
1. **`Sidebar.tsx`** — swap `md:bg-bg-muted md:border-border` → `bg-sidebar border-sidebar-border`;
   logo + labels `text-sidebar-fg`; inactive items `text-sidebar-fg-muted hover:bg-sidebar-hover`,
   active `bg-sidebar-active text-sidebar-fg` (optional `--sidebar-accent` left-border). 8px radius.
   Tokens only.
2. **`AppShell.tsx`** — confirm `<main>` on `bg-canvas` (light); adjust gutters/footer to the
   Notion spacing. Structure unchanged. **`BottomTabBar.tsx` stays light** (light main tokens).

### Phase 3 — Re-skin primitives (token-only, per DESIGN.md §4)
Re-skin each `packages/ui/src/primitives/*` referencing tokens only:
- **Button** — primary = filled `--accent` purple @ `--radius-md`; secondary = transparent +
  `--border-strong`; ghost = transparent, hover `--bg-muted`; **link variant = `--link` blue**;
  destructive = `--danger`.
- **Card** — `--bg-surface` white, `--border` hairline, `--radius-lg` (12px), **no rest shadow**;
  `--shadow-2` on hover/popover.
- **Field / inputs** — 44px height, `--border-strong`, focus = 2px `--accent` + `--focus-ring`.
- **Badge / chips** — tinted bg + tinted text; `--radius-sm` tags / `--radius-full` status pills.
- **Alert** — soft tinted tones default/`--warn`/`--danger`/`--success`. **Switch** — track-on `--accent`.
- **Dialog/Sheet** — `--shadow-3` + `--overlay-scrim`. **FreshnessBadge/WhyBadge/Skeleton/Empty/Error** — token refresh.
- Audit every primitive for stray hardcoded hex/rgb → replace with tokens.

### Phase 4 — Re-skin pages (mostly automatic via tokens)
Spot-fix hardcoded utilities, page-title headings (`--font-display` + tracking), and spacing
rhythm across: Dashboard, History, HistoryRunDetail, Unsubscribe, Accounts, Schedule, Rules,
Preferences, Login, OAuthCallback. Settings: underline tabs, white form panels, no Appearance card.
Grep each page dir for literal colors.

### Phase 5 — Delete dead code (confirmed orphans)
- `frontend/src/features/settings/ProfileSettings.tsx` + `frontend/src/__tests__/SettingsPage.test.tsx`
  (superseded by split settings pages; only a test imports it).
- `frontend/src/features/email/EmailCard.tsx` + `frontend/src/__tests__/EmailCard.test.tsx`
  (not imported by any component).
- `frontend/src/features/email/useEmailBucketMutation.ts` (only its test imports it).
  ⚠️ **Preserve** the `email_bucket_update` type + replay + invalidation in `frontend/src/offline/db.ts`
  and `frontend/src/offline/mutations.ts`, the `QueuedActionsSheet` label, and the backend
  `PATCH /api/v1/emails/{email_id}/bucket` endpoint — offline replay of queued records depends on them.
- Confirm with `cd frontend && npm run dead-check` (knip) + import search; treat the code-review-graph
  as advisory. Adjust `knip.json` entry globs only if it yields false positives.

### Phase 6 — Backend `theme_preference` cleanup (isolated; the one destructive DB step)
Deferrable — if zero schema risk is preferred, stop after Phase 1's frontend removal (column is harmless).
- `backend/app/schemas/profile.py` — drop `ThemePreference` + the field from `UserProfileOut` /
  `UserProfilePatchRequest`.
- `backend/app/api/v1/profile.py` — drop the `theme_preference` read/write branch.
- `backend/app/db/models.py` — remove the column + `ck_users_theme_preference` constraint.
- New `backend/alembic/versions/0014_drop_theme_preference.py` — drop column + constraint; downgrade
  re-adds with default `'system'`. `make migrate` to confirm up/down.
- Update `backend/tests/unit/test_profile_validation.py` + `…/integration/test_profile_api.py`.
- `make docs` (pins `1.0.0`, refreshes `frontend/src/api/schema.d.ts`).

### Phase 7 — Rules & guardrails (centralized; future agents stick to the theme)
1. **DESIGN.md §12 (agent guide)** — add: *"Briefed ships a single fixed Notion theme. The desktop
   sidebar uses `--sidebar-*` tokens (dark); all other surfaces use `--bg-*` (light); the mobile
   bottom bar is light. Never hardcode a color/px/radius/shadow/font — use a token. Do not
   reintroduce dark mode, a theme toggle, `data-theme`, or `prefers-color-scheme`."*
2. **CLAUDE.md §2+§10** and **AGENTS.md §2+§10** (Codex's file) — add the **same one-line pointer**
   to each (a pointer, not a copy of the palette):
   > Briefed ships a **single fixed Notion theme**: dark desktop sidebar (`--sidebar-*`), light
   > main (`--bg-*`). Never hardcode colors/px/fonts — use DESIGN.md tokens. Do not reintroduce
   > dark-mode / theme-switching (`data-theme`, `prefers-color-scheme`, a toggle).

   `.codex/` has no separate rules file → AGENTS.md is Codex's centralized rule surface.
3. **CI/Makefile guard (mechanical enforcement)** — add `make lint-tokens`: grep `frontend/src` +
   `packages/ui/src` for raw hex (`#[0-9a-fA-F]{3,8}`) and `rgb(`/`rgba(` **outside** `tokens.css`,
   failing on a hit. Wire into the lint aggregate + CI (Makefile is CI's source of truth, §8).
4. **README.md** (CLAUDE.md §5 triggers) — remove the dark-mode/appearance mention; note the single
   Notion theme; document `make lint-tokens` and `dead-check`; add `lucide-react` if Phase 8 runs.

### Phase 8 — Icon system: emoji → lucide-react (recommended; adds one dependency)
*Optional but recommended for Notion fidelity — emoji glyphs are off-brand. Self-contained (no CDN),
tree-shakeable.*
- Add `lucide-react` to `frontend/package.json` (README dep update per §5).
- Change `NavItem.glyph: string` → a typed icon component in `frontend/src/shell/navItems.ts`; render
  in `Sidebar` (and `BottomTabBar`) as monochrome icons inheriting `currentColor`.
- Migrate the string `icon="…"` props (DashboardPage, HistoryPage, Unsubscribe, Accounts, Rules, …)
  and the `EmptyState`/`ErrorState` icon prop from string to lucide components. **Blast radius:** the
  `icon` prop type change touches every call site — update them in this phase.
- If the user declines, keep emoji glyphs (restyled) and drop this phase entirely.

### Phase 9 — Verification
- `cd frontend && npm run typecheck && npm run lint && npm run format:check && npm test && npm run dead-check`.
- `make lint-tokens`. If Phase 6 ran: `make migrate` (up+down) + `make docs`. `make test`
  (`-m "not e2e and not eval"`) + `make coverage` (≥80%; pinned-100% modules unchanged).
- **Manual (required, DESIGN.md §12):** `docker compose up -d` then `npm run dev` (or the `run`
  skill); verify each route — dark desktop sidebar + light main, light mobile bottom bar, purple
  primary buttons, blue inline links, hairline cards (no heavy shadow), 44px inputs + purple focus
  ring. Capture before/after screenshots via the Claude Preview MCP tools.
- `grep -r` to confirm no `data-theme` / `briefed.theme` / `prefers-color-scheme` references remain.

---

## Interface & contract changes
- **Token sheet:** `packages/ui/src/tokens.css` deleted; `@briefed/ui/tokens.css` export + vite
  alias removed. Single runtime sheet = `frontend/src/styles/tokens.css`.
- **Removed exports:** `useTheme`, `ThemePreference`, `ResolvedTheme`, `UseThemeResult`, `ThemeToggle`.
- **`NavItem`** (Phase 8): `glyph: string` → typed icon component; `EmptyState`/`ErrorState` `icon`
  prop string → component.
- **API (Phase 6 only):** profile GET/PATCH drop `theme_preference`; OpenAPI + generated
  `schema.d.ts` regenerated via `make docs`.
- **CSP:** `script-src` drops the inline-script hash (now `'self'`), in `index.html` + backend lockstep.
- **PWA manifest:** `theme_color`/`background_color` `#09090b` → `#fafaf9`.

## Risks & mitigations
- **CSP drift** — FOUC hash in two files; remove from both in lockstep (Phase 1).
- **Token de-dup** — verified the package sheet is unused at runtime and no Storybook consumes it →
  deletion is safe; primitives keep resolving via the frontend sheet's `--color-*` aliases.
- **Offline replay** — keep the `email_bucket_update` type/replay/endpoint when deleting the hook (Phase 5).
- **Contrast** — Notion orange (`#dd5b00`) and link-blue (`#0075de`) are borderline for text on light;
  use deeper shades (`#793400` / `#005bab`) for text and re-verify the DESIGN.md §2 table.
- **Migration risk (Phase 6)** — the only irreversible-on-prod step; isolated and deferrable.
- **Icon swap (Phase 8)** — `icon` prop type change has wide call-site blast radius; optional/droppable.

## Out of scope
Serif fonts; new routes/features; backend logic beyond `theme_preference`; the `/emails/{id}/bucket`
endpoint (kept for offline replay).
