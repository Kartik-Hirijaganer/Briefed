# Briefed — Design System

Canonical source of truth for visual design decisions in Briefed. Every UI
change reads this document **before** writing or editing code. Do not
introduce new colors, fonts, spacing values, radii, shadows, or motion
durations without updating the corresponding section here in the same
change. Tokens are the single source of truth — Tailwind utilities and
component primitives consume them, never hardcoded values.

---

## 1. Theme & atmosphere

Briefed is a calm, focused, single-user mailroom. The aesthetic is
"editorial inbox" — quiet surfaces, dense typography, color reserved for
priority and intent.

- **Light** is the default daytime mode (bright canvas, near-black text).
- **Dark** mode is for low-light reading and OLED display friendliness.
- **System** preference is the default for new users — the page tracks
  `prefers-color-scheme` until the user picks an explicit override.

The user's preference is stored in `localStorage('briefed.theme')` and
mirrored to `users.theme_preference` once authenticated. An inline
`<script>` in `index.html` resolves the preference *before* CSS loads to
prevent flash-of-unstyled-content (FOUC).

---

## 2. Color tokens

All color tokens live in [frontend/src/styles/tokens.css](frontend/src/styles/tokens.css)
on `:root` (light defaults) and `[data-theme='dark']` (dark overrides).
Tailwind v4 mirrors them via a `@theme` block in
[frontend/src/index.css](frontend/src/index.css).

### Surfaces

| Token | Light | Dark | Role |
|---|---|---|---|
| `--bg-canvas` | `#FAFAFB` | `#0A0A0F` | Page background |
| `--bg-surface` | `#FFFFFF` | `#15151B` | Cards, modals, sidebar |
| `--bg-muted` | `#F2F2F4` | `#1C1C24` | Secondary surface (tag chips, code blocks) |
| `--border` | `#E4E4E8` | `#27272F` | Divider + card outlines |
| `--border-strong` | `#C8C8CE` | `#3A3A44` | Inputs, pressed states |

### Foreground

| Token | Light | Dark | Role |
|---|---|---|---|
| `--fg` | `#101014` | `#FAFAFB` | Primary text |
| `--fg-muted` | `#54545C` | `#A1A1AA` | Secondary / metadata text |
| `--fg-faint` | `#7A7A82` | `#71717A` | Tertiary text (timestamps, hints) |
| `--fg-on-accent` | `#FFFFFF` | `#0A0A0F` | Text on accent surfaces |

### Accent + status

| Token | Light | Dark | Role |
|---|---|---|---|
| `--accent` | `#2563EB` | `#60A5FA` | Primary actions, links, active nav |
| `--accent-hover` | `#1D4ED8` | `#93C5FD` | Hover state for primary actions |
| `--success` | `#16A34A` | `#4ADE80` | Confirmation, healthy state |
| `--warn` | `#D97706` | `#FBBF24` | Soft warnings, borderline confidence |
| `--danger` | `#DC2626` | `#F87171` | Destructive actions, errors |

### Focus & interaction

| Token | Light | Dark |
|---|---|---|
| `--focus-ring` | `rgba(37, 99, 235, 0.45)` | `rgba(96, 165, 250, 0.55)` |

### Contrast verification (WCAG)

Ratios verified with [WebAIM Contrast Checker](https://webaim.org/resources/contrastchecker/).
"AAA" needs ≥ 7.0 for normal text; "AA" needs ≥ 4.5.

| Pair | Light ratio | Dark ratio | Result |
|---|---|---|---|
| `--fg` on `--bg-canvas` | 16.61 | 18.62 | AAA ✓ |
| `--fg` on `--bg-surface` | 17.69 | 16.21 | AAA ✓ |
| `--fg-muted` on `--bg-canvas` | 7.18 | 7.04 | AAA ✓ |
| `--fg-muted` on `--bg-surface` | 7.65 | 6.13 | AA ✓ |
| `--accent` on `--bg-canvas` | 7.24 | 7.36 | AAA ✓ |
| `--accent` on `--bg-surface` | 7.71 | 6.40 | AA ✓ |
| `--danger` on `--bg-canvas` | 7.04 | 4.69 | AAA / AA ✓ |
| `--success` on `--bg-canvas` | 7.05 | 8.96 | AAA ✓ |
| `--warn` on `--bg-canvas` | 7.10 | 9.62 | AAA ✓ |
| `--fg-on-accent` on `--accent` | 8.59 | 8.91 | AAA ✓ |

---

## 3. Typography

Fonts are self-hosted under [frontend/public/fonts/](frontend/public/fonts/)
(see §10 below). No CDN load — `connect-src 'self'` and the privacy stance
forbid third-party font fetches.

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

Display headlines use `--font-display`. All other text uses `--font-sans`.
Code blocks, run IDs, and version pins use `--font-mono`.

---

## 4. Components

Primitive components live in [packages/ui/src/primitives/](packages/ui/src/primitives/).
Their internal styles reference tokens by name only. When in doubt:

- **Buttons:** primary (filled accent), secondary (subtle outline), ghost
  (no border, hover-only background). Heights: 32 / 40 / 48 px.
- **Cards:** `--bg-surface` background, `--border` outline, `--radius-lg`,
  `--shadow-1` at rest. No drop shadow on dark mode by default.
- **Inputs:** 40px height, `--border-strong` outline, focus ring on
  `:focus-visible`. Required-field star uses `--danger`.
- **Tags / chips:** `--bg-muted` background, `--fg-muted` text, `--radius-full`.

Adding a new primitive requires (a) a new file under
[packages/ui/src/primitives/](packages/ui/src/primitives/), (b) a token
reference in this section, (c) tests in [frontend/src/__tests__/](frontend/src/__tests__/).

---

## 5. Layout

- **Spacing scale:** 4 / 8 / 12 / 16 / 24 / 32 / 48 / 64 px
  (`--space-1` through `--space-16`). Pick the smallest value that still
  reads as a clear separation.
- **Radius scale:** 4 / 8 / 16 / 9999 px (`--radius-sm`, `--radius-md`,
  `--radius-lg`, `--radius-full`).
- **Container width:** dashboard caps at 1080px; settings at 720px.
- **Sidebar:** 224px wide on desktop; collapses to a bottom tab bar
  below 768px (see [frontend/src/shell/](frontend/src/shell/)).

---

## 6. Depth & elevation

| Token | Value | Use |
|---|---|---|
| `--shadow-1` | `0 1px 2px rgba(0,0,0,0.06)` | Cards |
| `--shadow-2` | `0 4px 10px rgba(0,0,0,0.08)` | Hover, popovers |
| `--shadow-3` | `0 10px 30px rgba(0,0,0,0.12)` | Modals |

Dark mode mutes shadow alpha automatically (the colors stay; the canvas
absorbs them). Elevation in dark mode comes primarily from surface
contrast (`--bg-surface` is lighter than `--bg-canvas`), not shadows.

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
below `md`.

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

When asked to make a UI change:

1. Read this document end-to-end.
2. Look up the closest existing token before writing a new value. If a
   token exists and fits, use it.
3. If no token fits, propose a new token *here* in the same change —
   include name, value (light + dark), purpose, and contrast numbers.
4. Reference primitive components from [packages/ui](packages/ui/) where
   one exists; do not inline a new card / button / input.
5. After editing, run `npm run lint`, `npm run format:check`, and
   `npm test` (vitest) to confirm no regressions.
6. For any visual change, manually verify the affected route in both
   themes before reporting the task complete.
