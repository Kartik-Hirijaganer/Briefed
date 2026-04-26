# 2026-04-25 — Track A: OpenRouter migration

Replace direct Gemini/Anthropic providers with OpenRouter behind the
existing `LLMClient`. **No library extraction. No YAML catalog. No
redaction layer in this track** — those are Tracks B and C.

Scope is sized for a single-user personal project. Right-sized
abstractions only; rollback path preserved for 30 days.

Future ADR 0009 documents the trust-boundary change.

---

## Locked decisions

1. **OpenRouter is the sole direct provider going forward.** Gemini and
   Claude reached *through* OpenRouter routing.
2. **Catalog is a Python dict in `backend/app/llm/catalog.py`.** Not
   YAML. Not Pydantic-validated at import. A typed module with
   constants. Adding a model is a one-line edit.
3. **No library extraction.** `LLMClient` and providers stay in
   `backend/app/llm/`. Re-evaluate if a second consumer ever exists.
4. **Direct providers stay flag-gated for 30 days post-cutover.** A
   single env var (`BRIEFED_LLM_PROVIDER_BACKEND=openrouter|legacy`)
   selects the backend. Default flips to `openrouter` once green for a
   week. Delete legacy code at T+30 days.
5. **Cost guard is per-day USD cap, not just per-model call cap.** A
   single setting `daily_llm_usd_cap` enforced inside `LLMClient`; trips
   open the breaker for the rest of the UTC day.
6. **Trust-boundary regression is acknowledged in ADR 0009.** Going
   from two direct DPAs (Google, Anthropic) to one intermediary
   (OpenRouter) plus their downstream relationships is a real change.
   ADR states it explicitly; doesn't handwave with `data_collection: deny`.
7. **Secret store stays AWS SSM.** One new param
   `/briefed/<env>/openrouter_api_key`; old params retained until
   deletion at T+30 days.

## Out of scope (here)

- Library extraction → never (open new RFC if a second consumer appears).
- YAML catalog → never for one user.
- Redaction / sanitizers → Track B.
- Profile / schedule / design tokens → Track C.

---

## Phase 0 — Spike (30 minutes, gates the rest)

If anything in this phase fails, the plan does not proceed.

- [ ] Curl `openrouter.ai/api/v1/chat/completions` with
  `model: google/gemini-2.0-flash` and `response_format: { type: "json_object" }`.
  Verify JSON-mode response is well-formed.
- [ ] Same with `model: anthropic/claude-haiku-4.5`.
- [ ] Verify request body containing
  `provider: { data_collection: "deny" }` is accepted (and routes are
  still available with that flag set — some providers refuse).
- [ ] Verify the `usage.cost` field shape on the response. Note token
  pricing for both routes; compare to current direct pricing.
- [ ] One real prompt from Briefed (`classify_v1`) round-tripped end to
  end on each route — JSON parses against the existing schema.

**Exit**: a one-page spike note saved at
[.claude/plans/notes/2026-04-25-openrouter-spike.md](notes/) — go/no-go
plus the cost delta.

---

## Phase 1 — ADR 0009

- [ ] New file [docs/adr/0009-openrouter-as-llm-routing-layer.md](../../docs/adr/0009-openrouter-as-llm-routing-layer.md).
- [ ] Decisions captured: OpenRouter as sole direct provider, catalog
  as Python dict, no library extraction, 30-day rollback window.
- [ ] **Trust boundary section** (one paragraph, plain language): we
  previously had explicit no-training/no-retention terms with Google and
  Anthropic; we now have one such relationship with OpenRouter and rely
  on their downstream contracts with the same providers. `data_collection:
  deny` controls OR's logging, not the network hop itself. This is
  acceptable for a single-user personal project; it would not be for
  PHI/PII at scale.
- [ ] Mark ADR 0002 status `Superseded by 0009`.
- [ ] Update [docs/adr/README.md](../../docs/adr/README.md) index.

---

## Phase 2 — Catalog module

- [ ] New file [backend/app/llm/catalog.py](../../backend/app/llm/catalog.py)
  exposes a single typed dict + helper:

  ```python
  from typing import TypedDict

  class ModelEntry(TypedDict):
      openrouter_id: str
      cost_per_m_input_usd: float
      cost_per_m_output_usd: float
      daily_call_cap: int | None
      max_output_tokens: int

  CATALOG: dict[str, ModelEntry] = {
      "gemini-flash": {...},
      "claude-haiku": {...},
  }

  PRIMARY: str = "gemini-flash"
  FALLBACKS: list[str] = ["claude-haiku"]

  def resolve(name: str) -> ModelEntry: ...
  ```

- [ ] Adding a future model = add one entry to `CATALOG`. Adding a
  prompt = unchanged from today (lives under
  [packages/prompts/](../../packages/prompts/)).
- [ ] Unit tests for `resolve()` (unknown name raises, known name
  returns).

---

## Phase 3 — OpenRouter provider

- [ ] New file [backend/app/llm/providers/openrouter.py](../../backend/app/llm/providers/openrouter.py)
  implementing the existing `LLMProvider` protocol from
  [backend/app/llm/providers/base.py](../../backend/app/llm/providers/base.py).
- [ ] Body sets `provider: {data_collection: "deny"}` and `transforms: []`.
- [ ] Header `X-Title: Briefed`. **No** `HTTP-Referer` (privacy).
- [ ] JSON mode enabled per call when prompt schema is provided.
- [ ] `usage.cost` parsed and surfaced on `LLMCallResult`.
- [ ] Tests use `respx` to stub OpenRouter; cover success, JSON-mode,
  retryable 5xx, non-retryable 4xx, and `cost` parsing.
- [ ] One opt-in live smoke test guarded by `OPENROUTER_LIVE=1`.

---

## Phase 4 — Wire `LLMClient` to OpenRouter

- [ ] [backend/app/core/config.py](../../backend/app/core/config.py)
  gains `openrouter_api_key`, `llm_provider_backend: Literal["openrouter", "legacy"] = "openrouter"`,
  and `daily_llm_usd_cap: float | None = None` (None disables).
- [ ] `_SSM_FIELD_MAP` adds the new key; `_REQUIRED_SECRETS` adds it
  conditionally on `llm_provider_backend == "openrouter"`.
- [ ] `LLMClient` factory branches on `llm_provider_backend`:
  - `openrouter` → builds `OpenRouterProvider` for each model in the
    catalog chain.
  - `legacy` → constructs the existing direct providers (unchanged).
- [ ] Fallback chain order is `[CATALOG primary, *CATALOG fallbacks]` —
  same chain semantics as today (per-model breaker + cap), just
  different transport.

---

## Phase 5 — Cost guard

- [ ] In `LLMClient`, accumulate UTC-day spend from the `usage.cost`
  field per call.
- [ ] If `daily_llm_usd_cap` is set and reached, subsequent calls raise
  `LLMBudgetExceededError` (new error class) and trip a global breaker
  until UTC midnight.
- [ ] Per-model `daily_call_cap` from the catalog is enforced
  alongside (existing pattern).
- [ ] Unit tests across day-boundary, cap reset, multi-model accrual.

---

## Phase 6 — Cutover

- [ ] No code changes here; only the env flag flips and a SSM write.
- [ ] Default `llm_provider_backend` flips from `legacy` to
  `openrouter` once Phase 5 has been green for a week.
- [ ] Update [.env.example](../../.env.example) — add
  `BRIEFED_OPENROUTER_API_KEY`, mark Gemini/Anthropic keys as
  *retained for legacy fallback only*.
- [ ] Update [docs/operations/secrets-rotation.md](../../docs/operations/secrets-rotation.md).

---

## Phase 7 — Tests + monitoring

- [ ] Existing 100% coverage on `LLMClient` preserved (no module move
  to disturb it).
- [ ] Integration tests parametrized by backend (`openrouter`,
  `legacy`) — both pass for the duration of the rollback window.
- [ ] CloudWatch alarm on `LLMBudgetExceededError` rate (any non-zero
  rate pages).
- [ ] CloudWatch alarm on per-model breaker open events (renamed from
  `Gemini` / `Anthropic` to `OpenRouter:gemini-flash` etc.).

---

## Phase 8 — Delete legacy (T+30 days)

Separate PR, scheduled, not landed with the cutover.

- [ ] Delete `backend/app/llm/providers/gemini.py`,
  `anthropic.py`, `anthropic_batch.py`.
- [ ] Remove `legacy` branch from the factory.
- [ ] Remove `gemini_api_key`, `anthropic_api_key` from settings + SSM
  + Terraform.
- [ ] Update tests + ADR 0009 footer ("legacy removed YYYY-MM-DD").

---

## Risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| OpenRouter outage = total LLM outage | Low–Med | High | 30-day legacy backend reachable via env flag |
| JSON-mode flaky on Gemini-via-OR | Med | Med | Phase 0 spike gates the plan; per-model fallback |
| Cost regression (5–10% via OR) | Cert. | Low | Documented in ADR 0009; daily $ cap as backstop |
| `usage.cost` shape changes | Low | Low | Defensive parsing; test coverage |
| Trust-boundary perception | n/a | n/a | Explicit in ADR; user has accepted the trade-off |

## Estimated effort

| Phase | Effort |
|---|---|
| 0 — Spike | 30 min |
| 1 — ADR | 1 hr |
| 2 — Catalog | 1 hr |
| 3 — Provider | ½ day |
| 4 — Wire LLMClient | ½ day |
| 5 — Cost guard | ½ day |
| 6 — Cutover | ½ hr |
| 7 — Tests + monitoring | ½ day |
| 8 — Delete legacy (T+30) | ½ day |

**Total to cutover: ~3 days. Deletion: ½ day at T+30.**
