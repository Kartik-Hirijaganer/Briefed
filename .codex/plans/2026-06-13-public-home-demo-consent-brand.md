# Briefed — Public Homepage, Demo/Gmail Paths, Enforced Consent, Branding & Vercel

## Context

Briefed is a personal portfolio project being prepared for Google OAuth
verification and for sharing with recruiters. Today `/` is the authenticated
dashboard (no public face) and the OAuth consent screen's privacy/terms fields are
empty — which is where the owner is stuck.

Two audiences:
1. **Recruiters / hiring managers** must be able to *test and verify* the product.
   While the app is unverified, Google only lets **test users** complete the real
   Gmail OAuth flow, so a recruiter realistically **cannot** connect their own
   inbox. A **synthetic demo** is what lets them actually try Briefed — and it lets
   us ship a fully testable product **without** completing Google's costly
   restricted-scope verification.
2. **Real users** connecting their own Gmail must give **informed, server-enforced**
   consent before any mailbox data is processed.

Restricted Gmail scopes are requested — `gmail.readonly` + `gmail.modify`
(user-initiated mark-read, ADR 0013) — plus `userinfo.email`, `userinfo.profile`,
`openid` ([oauth.py:48](backend/app/services/gmail/oauth.py:48)). Restricted scopes
force verification, which **requires** the Google "Limited Use" disclosure.

**Outcome:** `/` becomes a public homepage with **Try Demo** / **Connect Gmail**;
the authenticated app moves to `/app/*`; public `/about`, `/privacy`, `/terms` ship;
a server-backed, **enforced** consent gate protects the real path; the app is
re-skinned with the **Ranked Brief** brand; and the frontend is deployed on
**Vercel** (clean shareable URL; CloudFront becomes the internal API origin).

---

## Review fixes incorporated (from the senior review)

| Pri | Fix | Phase |
|---|---|---|
| P0 | Backend `sanitize_return_to()` — reject `//evil`, `https://`, allow only `/app[/*]` | **2** |
| P0 | Consent gate **hard-branches**; `<Outlet/>` never mounts while consent required | **8** |
| P0 | Demo blocks **all** `/api/*` (incl. GET); any network call = test failure | **6** |
| P0 | `DemoShell` omits `OfflineBanners`/`QueuedActionsSheet`/logout/sync-drain | **6** |
| P1 | Manual-run: enforce consent **before** rate limiting (don't burn quota) | **9** |
| P1 | Enforce consent on Gmail-**affecting mutations** + pause offline replay | **8, 9** |
| P1 | Centralize route prefixing (`RouteBaseProvider`/`appPath()`); test `/app` + `/demo` | **2** |
| P1 | Centralized query-key module (fixes `['config']` vs `['client-config']`) | **2** |
| P1 | Legal copy = actual runtime: OpenRouter + **Gemini 2.5 Flash / Claude Haiku 4.5**; no over-promised "PII scrubbed" | **3** |
| P2 | Plan location + real effective date | below |
| — | Vercel deployment (replaces CloudFront-URL sharing) | **12** |
| — | Verification: CASA security assessment is **required** for stored restricted-scope data | **13** |

---

## Decisions & divergences (owner gave me final say)

- **Demo = one router + a `DemoShell` + a non-persisted, pre-seeded demo QueryClient,
  with the API client hard-blocking every `/api/*` under `/demo`.** Reuses the real
  page components; guarantees zero network.
- **Route prefixing is centralized** via a `RouteBaseProvider` so the *same* page
  renders `/app/...` links under the app and `/demo/...` under the demo — instead of
  hardcoding `/app` everywhere.
- **Consent is enforced server-side** (gate + processing paths + Gmail-affecting
  mutations), not UI-only.
- **About is public** at `/about`; separate **privacy vs terms versions**; single
  highest-accepted version per policy on `User` (no audit table) — proportionate.
- **Vercel hosts the frontend**; the backend stays on Lambda/CloudFront as an
  **API-only origin** that Vercel **proxies** (`/api/*`) so cookies/CSRF stay
  first-party — no cross-origin cookie changes.

---

## Assumptions

1. **Hosting:** frontend → Vercel; backend (FastAPI/Lambda) stays put as the API
   origin. Vercel **proxies `/api/*`** to that origin (Phase 12), so the browser
   only ever talks to the Vercel origin → existing session-cookie + CSRF design is
   unchanged and **no `VITE_*` API-URL env var is needed**. (The owner's note used
   CRA `REACT_APP_*`; this app is **Vite** — proxy avoids env vars entirely.)
2. **Shareable URL vs Google domain:** `*.vercel.app` (like `*.cloudfront.net`) is
   on the Public Suffix List and **cannot be a Google "Authorized domain."** So:
   - Recruiters get a clean `briefed.vercel.app` and use the **demo** → no Google
     verification needed at all.
   - **Full restricted-scope verification needs a custom domain** (e.g.
     `briefed.email`) added in Vercel → Domains. The owner named `briefed.email`;
     assume it's available/owned. All in-app links are **relative**, so code is
     domain-agnostic; only Google Console values + the OAuth redirect URI depend on
     the final domain.
3. **Strategy:** the demo means the owner can ship a testable product immediately;
   completing Google verification (custom domain + **CASA security assessment**) is
   only required to let *arbitrary* real users on the Gmail path. Until then keep the
   OAuth app in **Testing** (real path works for added test users) and **feature-flag
   the "Connect Gmail" CTA** (Phase 5) so production advertises demo-first.
4. **Brand:** "Ranked Brief" mark is final; assets exist in `Brefied/briefed-icons/`
   (`favicon.svg`, `icon-192/512/maskable.png`, brand purple `#5645d4`). All
   colors/fonts already in `frontend/src/styles/tokens.css` / `frontend/public/fonts/`
   — **no new design tokens**. `Brefied/` is design handoff, not shipped code.
5. **Legal:** operator = Kartik Hirijaganer (individual), contact
   `kartikhirijaganer@gmail.com`; governing law = **Maryland + applicable U.S.
   federal law**; **not for HIPAA/PHI**; text is a tailored template (owner reviews,
   not legal advice). `POLICY_EFFECTIVE_DATE` = the **actual deploy date** (set at
   publish; placeholder `2026-06-13`).
6. **Plan location:** per [CLAUDE.md](CLAUDE.md) §3, copy the approved plan to
   `.claude/plans/2026-06-13-public-home-demo-consent-brand.md` (if implementing via
   Codex, mirror to `.Codex/plans/`).
7. **Git:** feature branch; **no commit/push without explicit ask**.

---

## Target route map (single `frontend/src/router.tsx`)

| Path | Auth | Element | Notes |
|---|---|---|---|
| `/` | public | `HomePage` | marketing + Try Demo / Connect Gmail. **Zero API calls.** |
| `/demo`, `/demo/*` | public | `DemoShell` → real pages | synthetic; **all `/api/*` blocked** |
| `/about`, `/privacy`, `/terms` | public | content pages | **Zero API calls** |
| `/login` | public | `LoginPage` | Gmail disclosure + checkbox → OAuth (flagged) |
| `/oauth/callback` | public | `OAuthCallbackPage` | transitional |
| `/app`, `/app/unsubscribe`, `/app/history`, `/app/history/:runId`, `/app/settings/*` | auth | `AppShell` → pages | **consent-gated** |
| `/app/*` (unknown) | auth | `NotFoundPage` | |

**Public pages must make ZERO authenticated API calls** (else `csrfMiddleware`
[client.ts:66](frontend/src/api/client.ts:66) bounces a logged-out reviewer to
`/login`).

---

# PHASE 1 — Brand assets (logo, favicon, PWA icons)

**Goal:** Replace placeholder blue identity with the purple "Ranked Brief" mark.

**Mark** (from `Brefied/marks.jsx`, viewBox `0 0 100 100`): 4 rounded bars
`(x=23; y=25/43/61/79; w=54/42/30/18; h=11; rx=5.5)` with opacity `1/.78/.54/.32`,
`fill="currentColor"`.

**Create `frontend/src/components/brand/BriefedLogo.tsx`** — `BriefedMark({size?,
className?, title?})` and `BriefedWordmark({size?})` ("Briefed" in Inter Display 600,
tracking `-0.02em`). Tokens only; named exports; JSDoc.

**Replace** (copy `Brefied/briefed-icons/*` → `frontend/public/`, overwrite blue):
`favicon.svg`, `icon-192.png`, `icon-512.png`, `icon-maskable.png` (regenerate any
missing PNG from the SVG; maskable ≥20% safe-zone).

**Modify:** `Sidebar.tsx:44` text "B" → `<BriefedMark size={24}>` linking `/app`;
`index.html` title/`theme-color #5645d4`/`meta description`; `vite.config.ts` PWA
manifest name "Briefed" + purple `theme_color`/`background_color`.

**Done when:** purple favicon in tab; manifest purple; sidebar mark; no `#2563eb`.

---

# PHASE 2 — Foundations: routing, route-base helper, query keys, redirect safety

**Goal:** Free `/` for the homepage, move the app under `/app`, and put in the
abstractions the demo/app reuse depends on. **Do this before pages.**

### 2a. Centralized query keys (P1) — `frontend/src/api/queryKeys.ts`
Export every key as a typed factory: `digestToday`, `emails(params)`,
`unsubscribes`, `clientConfig` (= `['client-config']`), `history`, `run(id)`,
`accounts`, `preferences`, `schedule`, `rubric`, `legalConsent`. **Refactor existing
hooks** ([useDashboardData.ts], [useUnsubscribeData.ts:149], history/settings) to
import from it. Fixtures + demo seeding use the same module → no drift.

### 2b. Route-base helper (P1) — `frontend/src/routing/routeBase.tsx`
`RouteBaseProvider({base})` + `useRouteBase(): {base}` + `useAppPath(): (sub:string)
=> string`. `AppShell` provides `base="/app"`, `DemoShell` provides `base="/demo"`.
**Replace hardcoded in-app paths** with `appPath('history')` etc. Known sites:
`navItems.ts`, `SettingsLayout.tsx:14`, `ScanNowButton.tsx:128`
(`navigate(appPath('?bucket=must_read'))`), `HistoryRunDetailPage.tsx:68`,
`ReadingPaneActions.tsx`, `Sidebar.tsx`. The same page component then renders
correct links under `/app` and `/demo`.

### 2c. Router — `frontend/src/router.tsx`
Public routes at top level (`/`, `/demo` w/ children, `/about`, `/privacy`,
`/terms`, `/login`, `/oauth/callback`); `AppShell` parent at `path:'/app'` with
children (`index→Dashboard`, `unsubscribe`, `history`, `history/:runId`,
`settings/*`, `*→NotFound`); settings index → `appPath('settings/accounts')`.

### 2d. Auth redirect plumbing
`client.ts` `buildLoginRedirectPath`/`LOGIN_PATH`: preserve `/app/*` in `?next=`,
treat `/app` as home sentinel. `useAddGmailFlow.ts`/`OAuthCallbackPage.tsx`/
`AccountsPage.tsx`/`AccountCard.tsx` defaults → `/app/settings/accounts`.
`LoginPage` `sanitizeReturnTo` fallback → `/app`.

### 2e. **P0 — Backend open-redirect fix** — `backend/app/api/v1/oauth.py`
Add `sanitize_return_to(value: str|None) -> str`: return `/app` unless `value`
matches `^/app(/[^/].*)?$` (internal path, **rejects** `//evil`, `https://evil`,
`/\evil`, scheme-relative). Use it at **both** [oauth.py:162](backend/app/api/v1/oauth.py:162)
(cookie payload) and [oauth.py:317](backend/app/api/v1/oauth.py:317) (callback
redirect default `/app`). Tests: `//evil.example`, `https://evil`, `/app`,
`/app/settings/accounts`, `/etc`, `""` → only `/app[/*]` survive.

**Done when:** `grep -rn "to=\"/\"\|'/settings\|'/history\|'/unsubscribe\|navigate('/'" frontend/src`
is clean (all via `appPath`); login lands `/app`; `//evil` return_to → `/app`;
401 under `/app/x` → `/login?next=/app/x` → back to `/app/x`.

---

# PHASE 3 — Legal content + Privacy/Terms/About pages

**Goal:** Three public content pages; copy lives once and is reused by the gate.

**Pre-step (P1 accuracy):** read `backend/app/llm/redaction/{chain,identity,regex_sanitizer}.py`
and the UI redaction copy (`UserPreference.redact_pii`, `secure_offline_mode`) so
claims are exact. Privacy copy says LLM processing via **OpenRouter** with **Google
Gemini 2.5 Flash (primary)** and **Anthropic Claude Haiku 4.5 (fallback)** (per
[catalog.yml](packages/config/llm/catalog.yml)); describe redaction as **best-effort
identity + pattern-based** removal before send — **do not** claim guaranteed PII
removal.

**Create:**
- `frontend/src/content/legal.ts` — `PRIVACY_POLICY_VERSION=1`, `TERMS_VERSION=1`,
  `POLICY_EFFECTIVE_DATE` (deploy date); `PRIVACY_POLICY`, `TERMS_OF_SERVICE`,
  `ABOUT_CONTENT` as structured `LegalContent`; `CONSENT_SUMMARY: string[]`.
- `frontend/src/components/LegalDocument.tsx` — `<h1>/<h2>/<p>` renderer, capped to
  `--measure`. **Not** `SafeMarkdown` (it strips headings). Tokens only.
- `frontend/src/pages/{PrivacyPolicyPage,TermsOfServicePage,AboutPage}.tsx` — default
  exports, **zero API calls**, chrome = `BriefedWordmark`→`/` + cross-links.

**Privacy must include:** identity/contact; what Briefed does; **Demo (synthetic) vs
Connect-Gmail (real data)** distinction; **exact scopes** + plain purpose
(`gmail.modify` = user-initiated mark-read only); data stored (KMS-encrypted tokens +
content, ADR 0008); OpenRouter + the two model routes; **Google Limited Use
disclosure** + 4 commitments (only-for-features / no-sale / no-ads / no-human-reads);
sub-processors; retention; deletion & revocation (actual path, no over-promise);
security; **"we do not sell your data"**; **no-HIPAA**; changes/versioning; contact.

**Terms must include:** acceptance; service description; as-is/no-warranty +
liability limit; **AI-output disclaimer**; acceptable use; **no HIPAA-regulated
use**; Google API compliance; termination; **Maryland + U.S. federal law**; contact.

**Done when:** pages render logged-out; hard-refresh works (Vercel SPA fallback,
Phase 12); `preview_network` shows no `/api/*`; Privacy contains the Limited Use clause.

---

# PHASE 4 — Public Home page (`/`)

**Create `frontend/src/pages/HomePage.tsx`** (default export, **zero API calls**):
hero `BriefedWordmark` + headline "Briefed" + subhead "AI inbox triage for Gmail.
Preview it with demo data, or connect your own mailbox when you're ready."; 2–3
"what it does" sections (`Card`/tokens); **Primary CTA "Try Demo"** → `/demo`
("Explore Briefed with synthetic inbox data. No Google account required.");
**Secondary "Connect Gmail"** → `/login` ("…after reviewing the policies."), **behind
the Phase-5 flag**; footer links Privacy/Terms/About; trust notes ("Read-only-first
Gmail access", "Not for HIPAA-regulated healthcare data", "Demo uses synthetic data
only"). Never say "real mode."

**Done when:** both CTAs route correctly logged-out; zero `/api/*`; meta description present.

---

# PHASE 5 — Real Gmail login (`/login`) with informed pre-consent

**Modify `frontend/src/pages/LoginPage.tsx`:** Gmail-access explanation (exact scopes
in plain language via `CONSENT_SUMMARY`); **no-HIPAA** warning; AI/OpenRouter summary;
links to `/privacy`+`/terms` (new tab); **required checkbox** "I understand Briefed
will process my Gmail data under the Privacy Policy and Terms" gating the
**disabled-until-checked** "Continue with Google" (→ `useAddGmailFlow`, returns
`/app/...`); secondary "Try Demo instead" → `/demo`. Gate the live OAuth wiring behind
`VITE_ENABLE_GMAIL_CONNECT` (default off until Phases 7–9 ship); when off, the CTA
shows "Available soon — try the demo."

**Done when:** OAuth disabled until checkbox; scopes + no-HIPAA shown; flag toggles the CTA.

---

# PHASE 6 — Demo workspace (`/demo`)

**Goal:** Read-only, synthetic, **network-free** tour reusing real pages.

**Create:**
- `frontend/src/demo/fixtures.ts` — synthetic data typed to `schema.d.ts`, content
  based on `backend/scripts/seed_local_demo.py`. Keyed via `queryKeys` (2a) so they
  can't drift: digestToday, emails(bucket variants the UI requests), unsubscribes,
  clientConfig, history, run(id), accounts, preferences, schedule, rubric.
- `frontend/src/demo/demoQueryClient.ts` — singleton; defaults `staleTime:Infinity,
  gcTime:Infinity, retry:false, refetchOnMount/WindowFocus/Reconnect:false`; default
  `queryFn` **throws**. `seedDemoCache(qc)` pre-loads every key.
- `frontend/src/demo/DemoModeProvider.tsx` — `useDemoMode():{isDemo}`.
- **`frontend/src/shell/DemoShell.tsx` (P0)** — a demo shell that renders Sidebar
  (nav `base="/demo"`) + content + persistent **"Demo data"** badge but **omits
  `OfflineBanners`, `QueuedActionsSheet`, logout, and any sync-drain**
  ([useSyncQueueDrain]). Wrap children in
  `<QueryClientProvider client={demoQueryClient}><RouteBaseProvider base="/demo">
  <DemoModeProvider>…`. Demo routes reuse **real** page components.

**Block writes (two layers):**
1. **P0 hard guarantee:** in `client.ts`, if `location.pathname.startsWith('/demo')`,
   **reject every `/api/*` request (incl. GET)** with `DemoDisabledError` and never
   run the 401 redirect. A leaked seeded read therefore fails loudly (error state),
   caught by tests.
2. **UX:** action entry points read `useDemoMode()` → disabled + "Disabled in demo"
   (scan-now/`ScanNowButton`, mark-read/`EmailReader`/`MarkReadStatus`, move-bucket,
   unsubscribe confirm/execute/dismiss/`SenderCard`, account add/disconnect).

**Done when:** every `/demo/*` page shows seeded data with **zero `/api/*`**
(`preview_network` empty); no sync-drain; all mutators disabled; "Demo data" persists.

---

# PHASE 7 — Backend: consent model, endpoints, OpenAPI

**`backend/app/core/consent.py`** (importable by API + workers; mirrors `rate_limit.py`):
`CURRENT_PRIVACY_POLICY_VERSION=1`, `CURRENT_TERMS_VERSION=1`,
`has_current_legal_consent(user)->bool`, `enforce_legal_consent(user)->None` (raises
`HTTPException(451)`).

**Model — `backend/app/db/models.py` (`User`)**: add `privacy_policy_version_accepted`
(int, NOT NULL, server_default "0"), `terms_version_accepted` (same),
`legal_accepted_at` (datetime|None), `legal_accepted_user_agent` (str|None). `0` =
never accepted.

**Migration `0018_add_user_legal_consent.py`** — `make migrate-rev`, hand-edit to
house style (`revision="0018"`, `down_revision="0017"`); `make migrate` up+down.

**Schemas `backend/app/schemas/legal.py`** (mirror `profile.py`):
`LegalConsentStatusOut` (current+accepted privacy/terms versions, `consent_required`,
`accepted_at`); `LegalConsentRequest` (`privacy_policy_version`/`terms_version`,
`ge=1`, `frozen, extra="forbid"`). `Field(description=…)` on all.

**Router `backend/app/api/v1/legal.py`** (mirror `profile.py`): `GET
/api/v1/legal/consent` (status); `POST /api/v1/legal/consent` (422
`consent_version_mismatch` unless versions == current constants; else set columns +
`legal_accepted_at=utcnow()` + UA; return status). Register in `v1/__init__.py`.

**`make docs`** → regenerate `openapi.json` + `schema.d.ts`; commit (CI drift gate).

**Done when:** `test_legal_consent_api.py` green (new→required; accept→ok; mismatch→422; no cookie→401).

---

# PHASE 8 — Frontend: enforced consent gate (`/app/*`)

**Create:** `frontend/src/api/legal.ts` (typed get/accept); `hooks/useConsentGate.ts`
(`useQuery(queryKeys.legalConsent, …,{staleTime:0,gcTime:0})` — always revalidate,
**excluded from offline persistence**; doubles as auth probe: 401→`/login`);
`features/consent/ConsentGate.tsx` (blocking `Dialog`: `CONSENT_SUMMARY` + links +
"I have read and agree" checkbox gating **Accept**; **"Decline & sign out"** →
`logoutAndClearBrowserSession`; `onClose` no-op).

**Modify `AppShell.tsx` (P0 hard branch):** call `useConsentGate()`:
`loading`→shell only (no flash, no Outlet); **`required`→`<ConsentGate/>` and DO NOT
render `<Outlet/>`** (no child route mounts, so no Gmail-derived queries fire — the
only authenticated call before acceptance is `GET /legal/consent`); `error`(non-401)→
retry; `ok`→`<Outlet/>`. Add Privacy·Terms·About footer links.

**P1 — pause offline replay while gated:** `useSyncQueueDrain` must **not** drain
queued mutations when `consent_required` (guard the drain on consent state). Exclude
`legalConsent` key from the `main.tsx` persister `shouldDehydrateQuery`.

**Done when:** fresh user (versions 0) is hard-blocked on `/app` (no dashboard
queries in `preview_network` beyond `/legal/consent`); Accept reveals app; reload no
re-prompt; bumping a backend constant re-prompts; queued mutations don't replay while gated.

---

# PHASE 9 — Backend: enforce consent before processing & on mutations

Using `core/consent.py` helpers:
1. **Manual scan (P1 order)** — `frontend.py` `start_manual_run()`: load `user`,
   `enforce_legal_consent(user)` → 451 `legal_consent_required` **before**
   `enforce_manual_run` (don't burn quota) and before run/enqueue.
2. **Scheduled fanout** — `workers/handlers/fanout.py` user loop (~line 147):
   `if not has_current_legal_consent(user): logger.warning("fanout.skip_no_consent"); continue`.
3. **Ingest (defense-in-depth)** — `workers/handlers/ingest.py` `handle_ingest()`:
   load user; skip + log if not consented (blocks classify/summarize/jobs downstream).
4. **P1 — Gmail-affecting mutations** — gate endpoints that touch Gmail/Gmail-derived
   state with `enforce_legal_consent`: **mark-read** (`emails.py`, `gmail.modify`),
   **unsubscribe execute/confirm/dismiss** (`unsubscribes` router). Disconnect/delete
   account stays allowed (revocation). This closes the offline-replay hole.

**Done when:** manual scan→451 without consent (2xx with); fanout skips un-consented;
mark-read/unsubscribe-execute→451 without consent; consented user unchanged.

---

# PHASE 10 — Tests

**Backend** (`asyncio_mode=auto`): `test_legal_consent_api.py` (status/accept/mismatch/
401/404/malformed); `test_consent_enforcement.py` (helper truth table; manual-scan→451
**before** quota; fanout skip; mark-read/unsubscribe-execute→451); **`sanitize_return_to`
tests** (`//evil`, `https://evil`, `/app`, `/app/settings/accounts`, `/etc`, `""`).
Coverage ≥80%; keep `LLMClient` 100%.

**Frontend:** public pages render logged-out + **assert `api.GET` never called**
(Home/About/Privacy/Terms; Privacy asserts Limited Use); Home CTAs route; Login
checkbox gates OAuth + flag; **demo page renders seeded data with no network +
mutators disabled + non-GET and GET blocked under `/demo`**; ConsentGate (accept
gating, decline→logout, Esc no-bypass, **Outlet not mounted when required**);
`useConsentGate` required→ok; AppShell branch; `BriefedLogo`; **route-base tests
covering BOTH `/app/*` and `/demo/*`** for shared pages; `navItems`/`SettingsLayout`
updated. Commands: `make docs`, `make test`, `ruff`/`mypy --strict`, `npm run
lint`/`format:check`, `make migrate`, `make link-check`.

---

# PHASE 11 — Docs

`README.md` (public home + demo; legal pages; version-bump procedure: the two
backend constants + the two frontend constants + effective date); `docs/adr/
0015-public-homepage-demo-and-enforced-consent.md`; `DESIGN.md` brand-mark +
public-surfaces note. Optional: correct the stale "Gemini 1.5 Flash" line in
[CLAUDE.md](CLAUDE.md) to the catalog truth. `make link-check`.

---

# PHASE 12 — Deploy on Vercel (frontend) + API proxy

**Goal:** Clean public URL; CloudFront becomes the internal API origin (not shared).

### 12a. Vercel project (monorepo!)
- **Root Directory = repo root** (NOT `frontend`) — frontend depends on workspaces
  `@briefed/ui` + `@briefed/contracts`; building from `/frontend` won't resolve them.
- **Build Command** `npm run build` (root script → builds the frontend workspace).
- **Output Directory** `frontend/dist` (Vite). Install: `npm install` at root.

### 12b. `vercel.json` (repo root)
- **Rewrites (order matters):** `/api/(.*)` → `https://<backend-origin>/api/$1`
  (the existing CloudFront/Lambda API URL) **first**; then SPA fallback `/(.*)` →
  `/index.html` (Vercel serves real static files before rewrites, so assets are
  safe). This keeps the browser same-origin → **session cookie + CSRF unchanged, no
  frontend code change** (keeps relative `/api/*`).
- **Headers:** port the security headers/CSP from the CloudFront config
  (`infra/terraform/modules/cloudfront`) into `vercel.json` `headers` (the SPA is no
  longer behind CloudFront). `connect-src 'self'` still holds (proxy = same origin);
  fonts are self-hosted.

### 12c. Backend tweaks for being behind a proxy
- **OAuth redirect URI:** `_compute_redirect_uri(request, settings)` derives from the
  request host — behind the Vercel proxy the backend sees its *own* host, so the
  redirect URI would be wrong. **Fix:** drive it from an explicit configured public
  base URL setting (e.g. `BRIEFED_PUBLIC_BASE_URL`) OR honor `X-Forwarded-Host/Proto`;
  register that exact URI with Google. Prefer the explicit setting.
- **Cookies:** ensure session/CSRF `set_cookie` has **no hardcoded `domain`** (so it
  scopes to the Vercel origin the browser called); keep `secure=True`, `samesite=lax`
  (works for the top-level OAuth redirect). No CORS needed with the proxy. (Only if a
  future cross-origin setup is chosen would CORS + `SameSite=None` be required —
  avoid.)

### 12d. Custom domain (for Google verification)
Add `briefed.email` (or subdomain) in Vercel → Domains; use it for Google Console
values. `briefed.vercel.app` is fine for recruiter/demo sharing but not as a Google
Authorized domain (Assumption 2).

**Done when:** `briefed.vercel.app` serves the homepage; deep-link `/privacy` +
`/app/...` resolve (SPA fallback); `/api/*` proxies and login works end-to-end with
cookies; security headers present.

---

# PHASE 13 — Google OAuth Console + verification

1. Custom domain verified (Search Console) + added to **Authorized domains**.
2. OAuth consent screen: **Homepage** `https://briefed.email/`, **Privacy**
   `…/privacy`, **Terms** `…/terms`; **Redirect URI**
   `https://briefed.email/api/v1/oauth/gmail/callback` (matches 12c).
3. Scopes match the policy's scope list exactly; attach a demo video of the consent flow.
4. **CASA security assessment is REQUIRED** (restricted-scope data is stored/
   transmitted server-side) — budget time/cost. Until done, stay in **Testing**
   (real path for added test users) and keep the Connect-Gmail flag off in prod;
   recruiters use the demo.

---

## Risks / guardrails
- Public/demo pages make **zero `/api/*`** (tests + `preview_network`).
- Consent gate can't deadlock (server-driven; loading shows nothing; non-401 retry;
  decline always works) and **never mounts `<Outlet/>` while required**.
- Offline replay paused while gated + Gmail-mutations server-gated → no consent bypass.
- `appPath()` + centralized query keys prevent `/app`↔`/demo` drift.
- `sanitize_return_to` closes the open redirect.
- Proxy keeps cookies first-party; verify redirect-URI + cookie-domain behind proxy (12c).
- Legal copy matches runtime (OpenRouter + Gemini 2.5 Flash/Claude Haiku 4.5; redaction = best-effort).
- Full verification needs custom domain + CASA; demo avoids that for recruiters.

## Execution order
1 → 2 → 3 → 4 → 6 (demo) → **deploy 12** (ship homepage+demo to recruiters early) →
then 7 → 9 → 8 → 5 (enable Connect-Gmail) → 10 → 11 → 13.
**Hard gate:** do **not** enable the public **Connect Gmail** path until backend
consent endpoints (7), the gate (8), and processing/mutation enforcement (9) are live.
