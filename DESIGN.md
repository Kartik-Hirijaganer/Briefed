# Briefed — Design System

Canonical source of truth for visual design decisions in Briefed. Every UI
change reads this document **before** writing or editing code. Do not
introduce new colors, fonts, spacing values, radii, shadows, or motion
durations without updating the corresponding section here in the same
change. Tokens are the single source of truth — Tailwind utilities and
component primitives consume them, never hardcoded values.

---

## 1. Theme & atmosphere

Briefed ships a **single, fixed Notion-style theme** — there is no
light / dark / system mode and no theme toggle. The aesthetic is the Notion
design language: warm off-white main surfaces, charcoal ink, a signature
purple accent (`#5645d4`), and a distinct link blue (`#0075de`), with soft
hairline-driven elevation rather than heavy shadows.

- **Main content is light** — warm off-white canvas (`--bg-canvas`), white
  cards (`--bg-surface`), charcoal text (`--fg`).
- **The desktop sidebar is dark** — a warm charcoal surface defined solely by
  the `--sidebar-*` token group (see §2). It is the only dark surface.
- **The mobile bottom tab bar stays light** — it is the mobile main chrome,
  not a sidenav, so it uses the light `--bg-*` tokens.

**Do not reintroduce dark mode, a theme toggle, `data-theme`, or
`prefers-color-scheme`.** There is exactly one `:root` palette: no preference
to persist, and no FOUC script to resolve.

---

## 2. Color tokens

All color tokens live in [frontend/src/styles/tokens.css](frontend/src/styles/tokens.css)
on a **single `:root`** — there are no `[data-theme='dark']` or
`@media (prefers-color-scheme: dark)` blocks. Tailwind v4 mirrors them via a
`@theme` block in [frontend/src/index.css](frontend/src/index.css). The
desktop sidebar's dark surface is expressed purely through the `--sidebar-*`
group below — it is the one and only dark region.

### Main surfaces (light — Notion warm neutrals)

| Token | Value | Role |
|---|---|---|
| `--bg-canvas` | `#fafaf9` | Page background (warm off-white) |
| `--bg-surface` | `#ffffff` | Cards, modals, popovers |
| `--bg-muted` | `#f6f5f4` | Chips, code, secondary fills |
| `--border` | `#e5e3df` | Dividers, card outlines (hairline) |
| `--border-strong` | `#c8c4be` | Inputs, pressed states |

### Foreground

| Token | Value | Role |
|---|---|---|
| `--fg` | `#37352f` | Primary text (signature Notion ink) |
| `--fg-muted` | `#5d5b54` | Secondary / metadata text |
| `--fg-faint` | `#787671` | Tertiary hints (timestamps; non-essential) |
| `--fg-on-accent` | `#ffffff` | Text on accent / purple surfaces |

For max-contrast display headings, `#1a1a1a` on `--bg-canvas` is available
(16.66, AAA) — reserve it for hero headings only.

### Accent, link & status

Notion keeps **accent ≠ link**: the purple accent is for actions, the blue is
for inline text links. Do not mix them.

| Token | Value | Role |
|---|---|---|
| `--accent` | `#5645d4` | Primary buttons, active nav, focus |
| `--accent-hover` | `#4534b3` | Hover / pressed |
| `--link` | `#0075de` | Inline text links only |
| `--success` | `#1aae39` | Healthy / confirm — fills, icons, status dots |
| `--success-strong` | `#137a28` | Success **text** / badges on light (deeper green) |
| `--warn` | `#dd5b00` | Warning fills / icons |
| `--danger` | `#e03131` | Destructive / errors |
| `--focus-ring` | `rgba(86, 69, 212, 0.45)` | Focus ring |
| `--overlay-scrim` | `rgba(25, 25, 25, 0.45)` | Dialog / sheet scrim |

### Sidebar group (dark charcoal — desktop sidebar only)

Consumed **only** by `Sidebar.tsx` (desktop). This is the single place the
dark sidebar is defined; no other surface may use these tokens.

| Token | Value | Role |
|---|---|---|
| `--sidebar-bg` | `#191919` | Desktop sidebar surface (warm near-black) |
| `--sidebar-bg-elevated` | `#202020` | Active / hover row background |
| `--sidebar-fg` | `#f7f6f3` | Active / primary label |
| `--sidebar-fg-muted` | `#a4a097` | Inactive labels, section headers |
| `--sidebar-border` | `#2f2f2e` | Sidebar dividers / right edge |
| `--sidebar-hover-bg` | `rgba(255, 255, 255, 0.05)` | Hover row |
| `--sidebar-active-bg` | `rgba(255, 255, 255, 0.08)` | Active row |
| `--sidebar-accent` | `#9a7cf0` | Active indicator (lightened purple) |

### Contrast verification (WCAG)

Ratios computed with the WCAG 2.1 relative-luminance formula (the same math
as the [WebAIM Contrast Checker](https://webaim.org/resources/contrastchecker/)).
"AAA" needs ≥ 7.0 for normal text; "AA" needs ≥ 4.5; large text / UI graphics
need ≥ 3.0.

| Pair | Ratio | Result |
|---|---|---|
| `--fg` on `--bg-canvas` | 11.74 | AAA ✓ |
| `--fg` on `--bg-surface` | 12.26 | AAA ✓ |
| `--fg-muted` on `--bg-canvas` | 6.51 | AA ✓ |
| `--fg-muted` on `--bg-surface` | 6.80 | AA ✓ |
| `--fg-faint` on `--bg-surface` | 4.54 | AA ✓ (non-essential hints) |
| `--fg-faint` on `--bg-canvas` | 4.34 | AA-large — hints only, never body |
| `--accent` on `--bg-canvas` | 6.29 | AA ✓ |
| `--accent` on `--bg-surface` | 6.57 | AA ✓ |
| `--fg-on-accent` on `--accent` | 6.57 | AA ✓ (button labels) |
| `--link` on `--bg-surface` | 4.57 | AA ✓ |
| `--link` on `--bg-canvas` | 4.37 | AA-large — for body links on canvas use `#005bab` (6.81, AAA) |
| `--danger` on `--bg-canvas` | 4.32 | AA-large — fills/icons; near-AA for text |
| `--warn` on `--bg-canvas` | 3.61 | AA-large — fills/icons; for warn text deepen to `#793400` (8.73, AAA) |
| `--success` on `--bg-canvas` | 2.81 | fills / icons / status dots only — never text on light |
| `--success-strong` on `--bg-surface` | 5.47 | AA ✓ — success text / badges (4.93 on the success tint) |
| `--sidebar-fg` on `--sidebar-bg` | 16.27 | AAA ✓ |
| `--sidebar-fg-muted` on `--sidebar-bg` | 6.74 | AA ✓ |
| `--sidebar-accent` on `--sidebar-bg` | 5.45 | AA ✓ |

**Status colors (`--success`, `--warn`, `--danger`) are intended as fills,
icons, and status dots** — or as text on their own tinted chip background
(see §4) — not as small body text on the raw canvas. When status text on a
light surface is needed, use a deeper shade — `--success-strong` for success,
`#793400` for warn — and re-verify the ratio here.

---

## 3. Typography

Fonts are self-hosted under [frontend/public/fonts/](frontend/public/fonts/)
(see §10 below). No CDN load — `connect-src 'self'` and the privacy stance
forbid third-party font fetches. Notion-Sans is Inter-based, so the existing
self-hosted Inter / Inter Display families are spec-accurate — **no new fonts**.

| Variable | Stack |
|---|---|
| `--font-display` | `'Inter Display', 'Inter Variable', system-ui, sans-serif` |
| `--font-sans` | `'Inter Variable', system-ui, -apple-system, sans-serif` |
| `--font-mono` | `'JetBrains Mono Variable', ui-monospace, SFMono-Regular, monospace` |

### Type scale (px)

| Token | Size | Line-height | Use |
|---|---|---|---|
| `--fs-xs` / `--lh-xs` | 12 | 16 | Captions, timestamps |
| `--fs-sm` / `--lh-sm` | 14 | 20 | Secondary text, table cells |
| `--fs-base` / `--lh-base` | 16 | 24 | Body |
| `--fs-lg` / `--lh-lg` | 18 | 28 | Card titles |
| `--fs-xl` / `--lh-xl` | 20 | 28 | Section heads |
| `--fs-2xl` / `--lh-2xl` | 24 | 32 | Page headers |
| `--fs-3xl` / `--lh-3xl` | 32 | 40 | Hero / login splash |

### Letter-spacing (tracking)

Notion sets large display headings slightly tighter. Apply these tokens to
`--font-display` headings only; body text keeps default (`0`) tracking.

| Token | Value | Use |
|---|---|---|
| `--tracking-tight` | `-0.01em` | Page headers (`--fs-2xl`) |
| `--tracking-tighter` | `-0.02em` | Hero / display headings (`--fs-3xl`) |

### Weight

Headings 600 (semibold), emphasized / medium 500, body 400. Display headlines
use `--font-display`; all other text uses `--font-sans`; code blocks, run IDs,
and version pins use `--font-mono`.

---

## 4. Components

Primitive components live in [packages/ui/src/primitives/](packages/ui/src/primitives/).
Their internal styles reference tokens by name only — never a hardcoded hex,
rgb, or px. Notion component conventions:

- **Buttons:** primary = filled `--accent` purple with a `--fg-on-accent`
  label at `--radius-md` (8px); secondary = transparent with a
  `--border-strong` outline; ghost = transparent, `--bg-muted` on hover;
  **link variant = `--link` blue** (no fill); destructive = `--danger`.
  Heights 32 / 40 / 48 px.
- **Cards:** `--bg-surface` background, a single `--border` hairline,
  `--radius-lg` (12px), and **no shadow at rest** (Notion elevation is
  border-driven). `--shadow-2` only on hover or for popovers.
- **Inputs / fields:** 44px height, `--border-strong` outline, focus = a 2px
  `--accent` ring + `--focus-ring`. Use `--control-height` for the 44px
  control height. Required-field star uses `--danger`.
- **Badges / chips:** tinted background + matching tinted text; `--radius-sm`
  for tags, `--radius-full` for status pills.
- **Alerts:** soft tinted tones — default / `--warn` / `--danger` / `--success`
  background + border, with readable `--fg` body text. The tone is carried by
  the tint + border, not the body copy: status colors fail contrast as small
  text on light (§2), so they are not used for alert text.
- **Switch:** track-on uses `--accent`.
- **Dialog / Sheet:** `--shadow-3` with the `--overlay-scrim` behind.

Adding a new primitive requires (a) a new file under
[packages/ui/src/primitives/](packages/ui/src/primitives/), (b) a token
reference in this section, (c) tests in [frontend/src/__tests__/](frontend/src/__tests__/).

---

## 5. Layout

- **Spacing scale:** 4 / 8 / 12 / 16 / 24 / 32 / 48 / 64 px
  (`--space-1` through `--space-16`). Pick the smallest value that still
  reads as a clear separation.
- **Radius scale:** 6 / 8 / 12 / 16 / 9999 px (`--radius-sm`, `--radius-md`,
  `--radius-lg`, `--radius-xl`, `--radius-full`). Buttons use `--radius-md`
  (8px); cards use `--radius-lg` (12px); `--radius-xl` (16px) is for large
  modals.
- **Container width:** data screens cap at `--container-wide` (1440px)
  with page gutters; settings caps at `--container-settings` (960px).
- **Readable measure:** narrative summaries cap at `--measure` (72ch) so
  generated prose stays scannable on wide displays.
- **Form control height:** `--control-height` is 44px for text inputs,
  selects, and time controls.
- **Compact forms:** settings forms use 1 column below `md`, 2 columns at
  `md`, and 3 columns at `lg` / `xl` when the fields are independent.
- **Sidebar:** 224px wide on desktop and **dark** (the `--sidebar-*` group,
  §2); collapses to a **light** bottom tab bar below 768px
  (see [frontend/src/shell/](frontend/src/shell/)).

---

## 6. Depth & elevation

Notion elevation is **low, soft, and border-driven**. A resting card carries a
single `--border` hairline and **no shadow**; shadows appear only on hover and
for floating surfaces (popovers, dialogs).

| Token | Value | Use |
|---|---|---|
| `--shadow-1` | `0 1px 2px rgba(15,15,15,0.04)` | Subtle lift (rarely needed; cards rest border-only) |
| `--shadow-2` | `0 4px 12px rgba(15,15,15,0.08)` | Hover, popovers |
| `--shadow-3` | `0 24px 48px -8px rgba(15,15,15,0.2)` | Modals / dialogs only |

Prefer a hairline `--border` over a shadow for separation. Reach for
`--shadow-2` / `--shadow-3` only when a surface genuinely floats above the page.

---

## 7. Motion

| Token | Value | Use |
|---|---|---|
| `--motion-fast` | 120 ms | Button press, tab swap |
| `--motion-base` | 200 ms | Card open, modal fade |
| `--motion-slow` | 400 ms | Page transition, drawer slide |

Easing: `--ease-standard: cubic-bezier(0.2, 0, 0, 1)`. All motion tokens
collapse to `0ms` under `prefers-reduced-motion: reduce`.

---

## 8. Do's and don'ts

**Do**

- Use tokens for every color, font size, spacing, radius, shadow, or
  motion duration.
- Pick the lowest-priority intent color you can — accent is loud, status
  colors louder still.
- Verify any new token contrasts against `--bg-canvas` and `--bg-surface`
  before merging.

**Don't**

- Inline hex colors, raw px values, or hardcoded font stacks. If you need
  a new token, define it here and in `tokens.css` first.
- Mix Tailwind defaults with custom tokens — Tailwind utilities resolve
  to tokens via the `@theme` block, so always prefer the named token.
- Animate without checking `prefers-reduced-motion`.
- Add a third-party font or icon CDN.

---

## 9. Responsive breakpoints

| Name | Min width | Use |
|---|---|---|
| `sm` | 0 | Default — phone portrait |
| `md` | 768px | Tablet, narrow desktop |
| `lg` | 1024px | Standard desktop |
| `xl` | 1280px | Wide desktop |

Sidebar appears at `md`. Dense data tables collapse to stacked cards
below `md`. Settings forms switch from 1 → 2 → 3 columns across
`sm` / `md` / `lg` while preserving `--measure` for long help text and
generated narrative copy.

---

## 10. Self-hosted fonts

The PWA bundles three font families under
[frontend/public/fonts/](frontend/public/fonts/):

- **Inter Display** — display headlines (variable axis: `wght 100..900`)
- **Inter** — body text (variable axis: `wght 100..900`)
- **JetBrains Mono** — monospace runs / code (variable axis: `wght 100..800`)

All three are licensed under the SIL Open Font License (OFL); the
`LICENSE` file lives in the same directory. Files are served with
`font-display: swap` and `Cache-Control: public, max-age=31536000` via
the standard PWA static asset rules.

The page never fetches `fonts.googleapis.com` or any other CDN — that
would log the user's IP upstream and conflict with the privacy stance
described in ADR 0008 / Track B.

---

## 11. Versioning & version display

The single source of truth for the application version is
[packages/contracts/version.json](packages/contracts/version.json).

- Backend: [backend/app/api/v1/frontend.py](backend/app/api/v1/frontend.py)
  reads this file at module import and exposes the value where needed.
- Frontend: [frontend/vite.config.ts](frontend/vite.config.ts) defines
  `__APP_VERSION__` from this file; `<AppVersion>` renders it as a
  monospace span.

Version is shown in the app shell footer (right-aligned) and the
Settings page header. Bump it with a single edit to `version.json` —
do not change `__version__` strings in scattered files.

---

## 12. Agent prompt guide

Briefed ships a **single fixed Notion theme.** The desktop sidebar uses the
`--sidebar-*` tokens (dark); all other surfaces use `--bg-*` (light); the
mobile bottom bar is light. **Never hardcode a color, px, radius, shadow, or
font — use a token.** Do not reintroduce dark mode, a theme toggle,
`data-theme`, or `prefers-color-scheme`.

When asked to make a UI change:

1. Read this document end-to-end.
2. Look up the closest existing token before writing a new value. If a
   token exists and fits, use it.
3. If no token fits, propose a new token *here* in the same change —
   include name, value, purpose, and WCAG contrast numbers (§2).
4. Reference primitive components from [packages/ui](packages/ui/) where
   one exists; do not inline a new card / button / input.
5. After editing, run `npm run lint`, `npm run format:check`, and
   `npm test` (vitest) to confirm no regressions.
6. For any visual change, manually verify the affected route before
   reporting the task complete.
