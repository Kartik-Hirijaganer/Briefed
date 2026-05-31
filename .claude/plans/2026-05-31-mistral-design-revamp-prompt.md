# Claude Design Prompt — Briefed × Mistral "Warm Flame" Revamp

> Paste everything below the line into Claude Design. It is self-contained:
> product context, the target design language, hard constraints, screen-by-screen
> direction with real data, fresh concepts to explore, and a definition of done.

---

## Role

You are a senior product designer revamping the visual identity of an existing
web app. Produce **high-fidelity, presentation-ready screen designs plus fresh
layout concepts** — not a wireframe pass. Deliver interactive mockups (HTML +
CSS, or React) for every screen below, in **both light and dark themes** and at
**both mobile (390px) and desktop (1280px)** widths. Lead with strong opinions;
where I give options, design the one you believe is best and note the runners-up.

## The product — "Briefed"

Briefed is a **personal AI email agent**. Once a day it scans the user's Gmail,
scores every message against the user's own priority rubric, and sorts mail into
four buckets — **Must read · Good to read · Ignore · Waste** — then writes short
summaries and extracts things like job leads. It is a calm, single-user
"mailroom": the user opens it in the morning, sees what actually matters, and
gets on with their day.

Two principles define the product's soul — design *with* them, never against:

1. **Recommend-only.** Briefed never sends, archives, replies, or clicks
   unsubscribe on the user's behalf. It *suggests* and links out to Gmail. Every
   action verb in the UI is advisory ("Open in Gmail", "Suggested unsubscribe"),
   never executed-on-your-behalf. Never design a button that implies Briefed
   acted in the user's mailbox.
2. **Explainability.** Every email the agent classified must show *why*: a
   compact "Why" badge exposing the reasons, the decision source (rule vs. LLM),
   and a confidence level. This badge and an "Open in Gmail" link appear on
   **every** email row — treat both as non-removable furniture.

The current look is a cool, blue-accented "editorial inbox" (blue `#2563EB`,
Inter type, light/dark). **We are replacing that identity entirely.**

## The target design language — Mistral "Warm Flame"

Adopt the visual language of **Mistral AI's 2025 identity**: French-engineered
minimalism, warm and optimistic, built from modular blocks, with a **flame
palette running red → orange → yellow**. Think warm paper, black ink, generous
whitespace, sharp/pure color (the rebrand replaced soft gradients with crisp
blocks), big confident headlines, and a quietly technical, developer-portal
undertone.

If you have shell access, you may pull the canonical token file with
`npx getdesign@latest add mistral.ai` and treat its `design.md` tokens as the
binding source. If you cannot, the distilled system below is sufficient and
self-contained.

### The signature idea: map the flame to email priority

Briefed sorts mail by how much it matters. Mistral's palette literally runs from
cool to hot. **Fuse them: the flame gradient encodes priority/"heat."** This is
the spine of the whole redesign — a hotter color means "this matters more."

| Bucket / priority | Heat | Light | Dark |
|---|---|---|---|
| Must read (critical) | 🔥 hottest | `#E1330B` | `#FF5A2C` |
| Good to read (warm) | warm | `#FA6A0F` | `#FF8A2A` |
| (medium signal) | amber | `#FFA200` | `#FFB733` |
| (low signal) | gold | `#F4C430` | `#FFD45E` |
| Ignore / Waste | ash (no heat) | `#B8AE9B` | `#6F6655` |

### Color tokens (map onto Briefed's existing CSS-var names so engineering can swap values in `tokens.css`)

**Surfaces — warm paper, never pure gray:**

| Token | Light | Dark | Role |
|---|---|---|---|
| `--bg-canvas` | `#FBF7EF` | `#14110C` | Page background (warm cream / warm near-black) |
| `--bg-surface` | `#FFFDF9` | `#1F1B14` | Cards, sheets, sidebar |
| `--bg-muted` | `#F3ECDF` | `#2A2419` | Chips, code blocks, secondary fills |
| `--border` | `#E7DDCB` | `#352F22` | Dividers, card outlines |
| `--border-strong` | `#D6C9B0` | `#4A4231` | Inputs, pressed states |

**Ink — warm black, not blue-black:**

| Token | Light | Dark | Role |
|---|---|---|---|
| `--fg` | `#1B1712` | `#F6F0E4` | Primary text |
| `--fg-muted` | `#6A6253` | `#B3AA98` | Metadata, secondary |
| `--fg-faint` | `#908775` | `#837A68` | Timestamps, hints |
| `--fg-on-accent` | `#1B1712` | `#1B1712` | **Black ink on orange** (Mistral hallmark — never white) |

**Accent + status:**

| Token | Light | Dark | Role |
|---|---|---|---|
| `--accent` | `#FA520F` | `#FF6A1F` | Flame orange — primary actions, links, active nav |
| `--accent-hover` | `#E0440A` | `#FF8038` | Hover |
| `--success` | `#2F8F4E` | `#5BC47E` | Healthy / confirmed |
| `--warn` | `#B7791F` | `#E0A93B` | Soft warning (ochre — keep visually distinct from accent; pair with icon + label, never color alone) |
| `--danger` | `#C2300B` | `#FF6B4A` | Errors, destructive confirmations |

**Contrast is a hard gate:** maintain WCAG **AA minimum** for all text (the
current app hits AAA on body text — aim to keep that on body copy). Black ink on
flame orange passes; white-on-orange does not — use black on every orange
surface. Verify every new pairing before presenting.

### Typography

- **Display / wordmark** — a neutral grotesque to echo Mistral's Arial wordmark:
  `'Helvetica Neue', Arial, 'Inter Variable', system-ui, sans-serif`. Tight
  tracking, heavy weight; consider an **uppercase, blocky wordmark** for
  "BRIEFED". Push hero headlines large (40–48px) for an editorial "front page"
  feel.
- **Body / UI** — keep **Inter** (already self-hosted). Clean, neutral, dense.
- **Mono** — keep **JetBrains Mono** (already self-hosted) for cost figures, run
  IDs, timestamps, version pins. Lean into it — the technical mono detailing is
  very on-brand for Mistral's developer-portal tone.

(Self-hosted/system fonts only — see constraints. Arial/Helvetica are
system-available, so no web-font CDN is introduced.)

### Shape, depth, motion, motif

- **Radius — sharper than today.** Mistral's identity is built from crisp
  modular blocks. Tighten the scale: `--radius-sm: 2px`, `--radius-md: 6px`,
  `--radius-lg: 10px`, `--radius-full: 9999px` (chips/avatars only). Favor square
  corners on "block" elements.
- **Depth — flat.** Prefer 1px borders + surface contrast over shadows. Keep
  shadows whisper-light in light mode; **no shadows in dark mode** (use surface
  contrast). No glows.
- **Motion** — keep it quick and purposeful (≈120/200/400ms). One allowed flourish:
  a subtle "ember" shimmer on the hottest priority element. Everything collapses
  to 0ms under `prefers-reduced-motion: reduce`.
- **Motifs to invent and reuse:**
  - **Modular block grid** — a faint square lattice as texture on the login hero
    and empty states (nods to the block-built "M").
  - **Flame heat pips/bars** — the priority encoding above, as small square pips
    or a thin heat bar on each email row.
  - **Square monogram avatars** for senders (rounded-square, not circles).
  - **An original Briefed mark** — design a small blocky logomark (e.g. a stack
    of three blocks, or a block-built envelope/"B"). **Do NOT reproduce Mistral's
    "M" or the Le Chat pixel-cat — those are their trademarks.** Borrow the
    *language* (modular blocks, flame), create original assets.

## Hard constraints (non-negotiable)

1. **Both themes.** Every screen in light AND dark. Dark mode is warm near-black,
   not cool gray.
2. **Mobile-first PWA.** This is an installed PWA. Design mobile (390px) and
   desktop (1280px). Respect iOS safe areas. Below 768px the left **sidebar
   collapses to a bottom tab bar**; at ≥768px it's a 224px sidebar. Keep
   **pull-to-refresh** and tap targets ≥44px.
3. **No web-font / icon CDNs.** Privacy stance forbids third-party fetches. Use
   the self-hosted/system fonts above and an inline SVG icon set (no icon CDN).
4. **Recommend-only language** everywhere (see product principle #1).
5. **Explainability furniture** on every email row: "Why" badge (reasons +
   decision source + confidence) and "Open in Gmail" (see principle #2).
6. **Preserve the information architecture & real data fields** below — redesign
   the presentation, don't invent new data or rename routes.
7. **Accessibility:** visible `:focus-visible` rings (flame, low-alpha), reduced-
   motion support, AA+ contrast, semantic headings, full keyboard reachability.
8. **Tokens are the source of truth.** Express the design as the token set above;
   don't scatter one-off hex values. Provide a token map at the end.

## Screens to design (in depth)

For each: I give the **real data**, **today's state**, and **fresh directions**.
Redesign the presentation; explore the concepts; keep the constraints.

### 1) Login / landing (`/login`)

- **Real data / actions:** single action — "Continue with Google" (read-only
  Gmail OAuth, handled server-side). Privacy microcopy: read-only access; never
  sends/archives/unsubscribes.
- **Today:** a lone centered white card with a heading, a paragraph, and one
  button. Functional, forgettable.
- **Fresh directions (pick the strongest, show 1–2):**
  - **"Warm doormat" split hero.** Left: oversized editorial headline on warm
    paper over a faint block-grid texture, a one-line value prop ("Your inbox,
    briefed every morning."), the single Google button, and the privacy promise
    as quiet mono footnotes. Right (desktop): a **living preview** — a stylized
    mini "morning briefing" with flame-heat email rows, so the value is shown,
    not told. On mobile it stacks, preview above the fold-break.
  - **"Single ember" minimalist.** Near-empty warm canvas, the blocky Briefed
    mark with one animated ember, headline, one button. Confidence through
    restraint.
  - Make the privacy/recommend-only promise feel like a *feature*, not legal fine
    print — it's a trust differentiator.

### 2) Home — "Today's Digest" (`/`)

- **Real data:** `counts` per bucket (must_read / good_to_read / ignore);
  `cost_cents_today`; `must_read_preview` (list of email rows);
  `last_successful_run_at` (drives a freshness badge); a "Scan now" trigger;
  warns if no successful scan in 7 days.
- **Today:** an H1 "Today's Digest", a freshness badge, a "Scan now" button, a
  4-up grid of stat tiles, then an H2 "Must-read preview" list of email cards.
- **Fresh directions:**
  - **The "morning briefing" front page.** Treat Home like the cover of a daily
    paper. A dateline ("Saturday, May 31") and a one-sentence, agent-written
    **lead line** ("3 things need you today; the rest can wait."). A **hero lead
    story** — the single hottest must-read, rendered large with its summary and
    Why badge — then the remaining must-reads as a tighter list below.
  - **Flame-meter counts.** Replace the flat stat tiles with the heat scale: the
    Must-read count glows hottest, Waste is cool ash. Make "how hot is today"
    legible at a glance.
  - **Cost as a quiet mono ticker**, not a loud tile — "$0.04 today" in
    JetBrains Mono, tucked near the freshness badge. It's reassurance, not a KPI.
  - **A real "quiet day" state.** When `must_read_preview` is empty, this should
    feel *earned and calm* — a warm, generous "You're clear for today" moment
    with the block-grid motif, not a sad empty box. Design this state explicitly.
  - **Scan now** should show live progress (scanning → classifying → done) since
    a scan is the core daily ritual — design the in-progress and freshness states.

### 3) Triage list — "Must read" & buckets (`/must-read`, `/good-to-read`, `/ignore`, `/waste`)

- **Real data per row (`EmailRow`):** `subject`, `sender`, `account_email`,
  `summary_excerpt` (2-line clamp), `received_at`, `bucket`,
  `reasons` + `decision_source` + `confidence` (→ Why badge), `thread_id`
  (→ Open in Gmail). List also shows a `total` count + freshness badge.
- **Interaction (keep it):** swipe right → promote to Must read, swipe left →
  Ignore. Must stay keyboard/AT accessible (current code exposes SR-only
  move buttons — preserve an accessible equivalent).
- **Today:** a header (bucket name + total + freshness) over a vertical list of
  uniform email cards.
- **Fresh directions:**
  - **Heat-railed card deck.** Each row carries a **left flame-heat rail**
    encoding its priority; the list reads as a temperature gradient. Sender in a
    square monogram avatar, subject bold, `summary_excerpt` in muted ink, the Why
    badge as a compact pill ("Rule · high" / "AI · 0.82"), "Open in Gmail" as a
    quiet trailing link.
  - **Designed swipe affordances.** The swipe reveal should use heat color +
    block motif: a warm "Must read" action revealing on the right, cool "Ignore"
    on the left — show the mid-swipe state in the mockup.
  - **Bucket switcher as heat segments** — Must read / Good / Ignore / Waste as a
    segmented control colored along the flame→ash scale, so the user always knows
    where they are on the heat map.
  - Design the **empty** and **loading skeleton** states in-language too.

### 4) Email detail (new/expanded — the explainability moment)

- **Real data:** everything on the row plus room for the fuller summary and the
  complete "why" rationale (reasons list, decision source, confidence). The
  primary action remains **"Open in Gmail"** (recommend-only — no archive/reply
  here).
- **Today:** there is no dedicated rich detail view — rows link straight out.
  This is a chance to add a focused reading surface.
- **Fresh directions:**
  - **"Why this matters" first.** Lead with the agent's reasoning — a prominent,
    confident explanation block (reasons as a list, decision source + confidence
    as mono detailing, a heat indicator for the bucket) — *above* the email
    summary. This is the product's trust core; make it the hero of the screen.
  - **Reading view** for the summary with comfortable measure and editorial type;
    the original-email actions are clearly delegated to Gmail (one obvious "Open
    in Gmail" button, styled as the primary flame action).
  - Show how a **low-confidence** classification looks vs. a **high-confidence**
    one — the UI should be honest about uncertainty.

### 5) Shared shell & system pieces (design these once, apply across screens)

- **App shell:** 224px left sidebar (≥768px) with the blocky Briefed mark and nav
  (Home, Must read, Jobs, News, Unsubscribe, History, Settings); collapses to a
  **bottom tab bar** on mobile (Home, Must read, Jobs, Settings). Replace the
  current emoji glyphs with an **original inline-SVG block icon set**. Include a
  light/dark theme toggle and a mono version pin in the footer.
- **Email card** (the atom reused on Home + every triage list) — design the
  canonical component: heat rail, square avatar, subject/sender/summary, Why
  badge, Open-in-Gmail, swipe states.
- **Why badge** — the signature explainability chip. Design rule-vs-AI and
  high-vs-low-confidence variants.
- **Freshness badge** — "fresh / stale / updating", tied to last scan time.
- **System states** — loading skeletons, error state, and warm empty states, all
  in-language (block grid, warm paper, no generic spinners).

## Deliverables

1. **A "style tile"** first: the warm-flame palette (light + dark swatches with
   hex), the flame heat scale, type specimens (display/body/mono), the block
   motif, the new Briefed logomark, and the core button/input/chip/card states.
2. **High-fidelity mockups** of screens 1–4 plus the shell, each in **light and
   dark** and at **mobile + desktop** widths.
3. **The key system states**: Home "quiet day", a triage loading skeleton, an
   error state, and the mid-swipe affordance.
4. **Short annotations** per screen explaining the concept choices and how each
   maps to a Mistral principle.
5. **A token map** at the end: every value expressed against Briefed's existing
   CSS-var names (`--bg-canvas`, `--accent`, `--radius-md`, …) plus the new
   `--heat-*` group, ready to drop into `tokens.css`, with a Tailwind v4
   `@theme` block if convenient.
6. Build as **interactive HTML/CSS or React artifacts** so I can click between
   screens and toggle the theme.

## Definition of done

- [ ] Warm paper + flame identity fully replaces the blue/editorial look.
- [ ] Flame heat scale encodes priority consistently across Home, triage, detail.
- [ ] Every screen shown in light **and** dark, mobile **and** desktop.
- [ ] Every email row keeps a Why badge **and** an Open-in-Gmail link.
- [ ] No UI implies Briefed sent/archived/unsubscribed on the user's behalf.
- [ ] Black ink on all orange; every text pairing passes WCAG AA (AA+ on body).
- [ ] No web-font/icon CDN; original logomark (not Mistral's M or the cat).
- [ ] Mobile = bottom tab bar; desktop = 224px sidebar; pull-to-refresh present.
- [ ] Quiet-day, loading, error, and mid-swipe states all designed.
- [ ] A token map ready for `tokens.css` accompanies the mockups.

## Do not

- Reproduce Mistral's logo, the "M", or the Le Chat pixel-cat (trademarks) —
  create original assets in their language.
- Introduce a third color story; the flame/ash scale + warm neutrals is the
  whole palette.
- Drop dark mode, weaken contrast, or use white text on orange.
- Add actions that execute changes in the user's mailbox.
- Invent data fields not listed above.
