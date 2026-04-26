# ADR 0009 — OpenRouter as the LLM routing layer

- **Date:** 2026-04-25
- **Status:** Accepted
- **Deciders:** Kartik Hirijaganer
- **Supersedes:** ADR 0002 (Gemini 1.5 Flash primary, Claude Haiku 4.5 fallback)

## Context

ADR 0002 wired Briefed directly to two providers — Google
(Gemini Flash) and Anthropic (Claude Haiku 4.5) — selected because each
publishes a no-training / no-retention tier we trust for personal email
content. The arrangement works but has friction:

- Two SDKs and two billing relationships to operate.
- Adding a new model (Claude Sonnet for an isolated codepath, Llama for a
  cheap unsubscribe-classifier experiment) means a new direct integration.
- Outage drills against either provider hit a single chokepoint.

OpenRouter routes to both providers (and dozens more) behind one API,
one bill, and one set of credentials. It also surfaces a per-call
`usage.cost` field, which simplifies the daily-spend guard the cost
plan needs.

## Decision

- **OpenRouter is the sole direct LLM provider going forward.**
  `OpenRouterProvider` implements the existing
  [`LLMProvider`](../../backend/app/llm/providers/base.py) protocol; the
  rest of the codebase (`LLMClient`, prompt registry, schemas) does not
  change.
- **Catalog is a Python dict** in
  [`backend/app/llm/catalog.py`](../../backend/app/llm/catalog.py),
  not a YAML file. Adding a model is a one-line edit. The plan
  considered a YAML catalog and rejected it as overweight for a
  single-user project.
- **Direct providers were retained behind a flag for 30 days
  post-cutover** to give us a no-code-change rollback path. The legacy
  provider files (`gemini.py`, `anthropic.py`, `anthropic_batch.py`)
  and the `BRIEFED_LLM_PROVIDER_BACKEND` selector were deleted at
  T+30 days; git history is the rollback path beyond that point.
- **Cost guard is a per-day USD cap.** A new setting
  `daily_llm_usd_cap` is enforced inside `LLMClient` from the per-call
  `usage.cost`; trips raise `LLMBudgetExceededError` and open a global
  breaker for the rest of the UTC day. Per-model `daily_call_cap`
  (catalog-driven) is enforced alongside the existing pattern.
- **Secret store stays AWS SSM.** A new parameter
  `/briefed/${env}/openrouter_api_key` is the only addition; existing
  Gemini / Anthropic parameters are retained until deletion at T+30.
- **No library extraction.** `LLMClient` and providers stay under
  `backend/app/llm/`. We will revisit if a second consumer ever needs
  the abstraction.

## Trust-boundary change (the honest paragraph)

ADR 0002 leaned on **two direct contractual relationships** with Google
and Anthropic, each with explicit no-training and no-retention
commitments on their paid tiers. ADR 0009 replaces those with **one
direct relationship with OpenRouter plus their downstream contracts
with the same providers**. We send `provider: { data_collection: "deny" }`
on every request, which controls *OpenRouter's* logging and disables
provider routes that don't honour the same. It does not eliminate the
network hop through OpenRouter itself: requests and responses pass
through their infrastructure before reaching the model provider.

For a **single-user personal project** containing the operator's own
email, this is acceptable and we accept the trade-off knowingly. It
would **not** be acceptable for PHI / PII at scale, multi-tenant
operations, or any deployment where the email author has not consented
to the routing change. A future hosted deployment must revisit ADR 0009
before onboarding a second user.

## Consequences

**Benefits**

- One SDK / one bill / one rotation cycle.
- Adding a model becomes a one-line catalog edit.
- `usage.cost` lets the cost guard be authoritative rather than
  estimated from token counts + a price table.
- Outage surface shrinks operationally — OpenRouter's per-route
  fallbacks already cover transient provider outages on their side.

**Costs**

- Expected 5–10% pricing markup vs. direct provider pricing. Mitigated
  by the daily USD cap.
- Single chokepoint risk: an OpenRouter outage takes the LLM pipeline
  down. The 30-day legacy backend was the rollback path during the
  cutover window; beyond that, git revert + redeploy is the path.
- Trust-boundary regression as documented above.

## Alternatives considered

- **Stay direct (status quo, ADR 0002).** Rejected for the friction
  reasons listed in *Context*; not a defect of 0002, just a re-weighing
  of the trade-offs given the project's actual scale.
- **YAML catalog.** Rejected — extra file format and a Pydantic
  parse / validation step for what is currently two entries.
- **Library extraction of `LLMClient`.** Rejected — there is one
  consumer (this repo). Open a fresh RFC if a second consumer ever
  appears.

## Revisit triggers

- Multi-tenant / hosted deployment of Briefed.
- An OpenRouter outage that exceeds 1 hour in a 30-day window.
- `usage.cost` shape changes break parsing.
- Pricing markup exceeds 15% on a 30-day rolling basis.

## Footer

- Cutover landed: _YYYY-MM-DD_
- Default flag flipped to `openrouter`: _YYYY-MM-DD_
- Legacy provider files deleted: 2026-04-25
