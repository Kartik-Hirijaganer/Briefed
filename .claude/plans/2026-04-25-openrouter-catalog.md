# 2026-04-25 — OpenRouter + `llmkit` library + privacy guardrails

Three changes shipped together:

1. **Replace direct Gemini/Anthropic providers** with a single OpenRouter
   provider, driven by a versioned `catalog.yml` (models, sampling
   params, daily caps, primary/fallback chains).
2. **Extract the generic LLM machinery into a standalone Python
   package**: `llmkit`, living at `packages/llmkit/`. Reusable across
   future projects. Briefed becomes a *consumer*, not the owner.
3. **Add a privacy/redaction layer** that scrubs PHI, PII, and
   identity-revealing data before any prompt reaches OpenRouter, and
   sets OpenRouter's no-logging/no-training flags on every call.

Secret backend stays AWS SSM. Supersedes
[ADR 0002](../../docs/adr/0002-gemini-flash-primary-haiku-fallback.md).

---

## CRITICAL — HIPAA gap, decision required before Phase 0

Your account is on `premierhealthgroup.health`. **OpenRouter does not
offer a BAA**, and the providers behind it (Google, Anthropic on
public APIs) do not either. Sending raw PHI through OpenRouter is a
HIPAA violation regardless of how good our redaction is — Safe Harbor
de-identification is hard to guarantee with regex/ML alone.

Three options. **Pick one before Phase 0.**

| Option | Description | Risk |
|---|---|---|
| **(a)** Redact-before-send. Library ships strict redaction + audit logs. Accept residual risk. | What this plan defaults to. | Medium. Even Presidio misses things. Legal review needed. |
| **(b)** No PHI ever. Briefed scopes to non-clinical email only. Domain-allowlist mailboxes. | Tightest. | Lowest. May reduce app utility. |
| **(c)** BAA-covered provider for PHI tenants. Use Anthropic via **AWS Bedrock** (BAA available) for any user flagged as healthcare; OpenRouter for everyone else. | Most flexible. | Doubles provider config + cost. |

My lean: **(a) + (b) layered**. Default to redaction, but also restrict
which mailboxes Briefed connects to so PHI exposure is minimal in the
first place. Move to (c) if you ever onboard a real clinical user.

**Tell me which before I write Phase 0.** Until you pick, the plan
below assumes (a)+(b).

---

## Locked decisions (assuming the path above)

1. **Single direct LLM provider**: OpenRouter. Gemini/Claude reached *through* OpenRouter routing.
2. **Secret store**: AWS SSM Parameter Store. (Akeyless rejected: cold-start cost, chicken-and-egg auth, doubled plumbing.)
3. **Catalog format**: YAML, validated by Pydantic at module import (SnapStart-friendly).
4. **OpenRouter routing**: each LLM call targets *one* specific model. Fallback handled by `llmkit.LLMClient` (per-model breakers + caps), not OpenRouter's `route: fallback`.
5. **No backwards compat**: ADR 0002 fully superseded. `gemini.py`, `anthropic.py`, `anthropic_batch.py` deleted.
6. **Library extraction**: a new package `llmkit` at `packages/llmkit/`, distributed inside this monorepo via editable path-install. Not published to PyPI yet.
7. **Privacy by default**: every prompt is sanitized before send; every OpenRouter call sets no-logging headers; every LLM-call audit log records redaction counts (not values).
8. **Default redaction stack**: Microsoft Presidio (`presidio-analyzer` + `presidio-anonymizer`) as the primary engine, plus a regex fallback for offline/test environments. Presidio is gated behind a `llmkit[presidio]` extra so the core library stays light.

## Open questions resolved before Phase 1

- [ ] HIPAA path: (a)/(b)/(c) — see above.
- [ ] Library name: working title `llmkit`. Push back if you'd prefer `pyllm`, `llm-toolkit`, etc.
- [ ] Reversal-map behaviour: when redaction tokenizes `<EMAIL_1>`, do we *re-identify* the response on the way back (LLM said "email <EMAIL_1> back" → user sees real email), or leave tokens in the output? My pick: **re-identify by default, opt-out per call**. Useful for summarization; harmful for any text that gets stored externally.
- [ ] Logging policy on prompts: never log raw prompt content; log redacted prompt + redaction-stats. OK?
- [ ] Briefed prompt-bundle loader: does it stay in Briefed (knows about `packages/prompts/` layout) or move into `llmkit` as a generic loader? My pick: **stays in Briefed**. The library exposes `PromptSpec`; the loader is project-specific.

---

## Library boundary — what lives where

### `packages/llmkit/` (generic, reusable)

| Module | Contents |
|---|---|
| `llmkit/__init__.py` | Public API re-exports |
| `llmkit/client.py` | `LLMClient`, `CircuitBreaker`, `RateCap`, `LLMClientConfig`, `ClientResponse` |
| `llmkit/providers/base.py` | `LLMProvider` protocol, `LLMCallResult`, `LLMProviderError` |
| `llmkit/providers/openrouter.py` | `OpenRouterProvider` (the only concrete provider in v1) |
| `llmkit/catalog.py` | `Catalog`, `ModelEntry`, `ChainEntry`, `PromptEntry`, `load_catalog()` |
| `llmkit/prompt.py` | `PromptSpec`, `render_prompt()`, `PromptCallRecord` |
| `llmkit/redaction/__init__.py` | `Sanitizer` protocol, `SanitizerChain`, `RedactionResult`, `Reidentifier` |
| `llmkit/redaction/regex_sanitizer.py` | `RegexSanitizer` — defaults: emails, phones, SSN, CC, IPs, URLs |
| `llmkit/redaction/presidio_sanitizer.py` | `PresidioSanitizer` — gated by `[presidio]` extra |
| `llmkit/redaction/identity.py` | `IdentityScrubber` — removes operator-supplied user identifiers from prompts |
| `llmkit/factory.py` | `build_client_from_catalog(prompt_name, *, catalog, api_key, http_client, sanitizer, log_call)` |
| `llmkit/errors.py` | `LLMClientError`, `LLMProviderError`, `CircuitOpenError`, `RedactionError` |

**Hard rules for the library**:
- No imports from `app.*`. Library can't know it's running inside Briefed.
- No `structlog` dependency — use `logging` (stdlib) with a null handler; consumers wire their own.
- No DB, no SSM, no AWS SDK. Caller passes in the API key and optional async log callback.
- No clock helper imports — use `datetime.datetime.now(UTC)` or accept a `clock: Callable[[], datetime]` for tests.
- All public types `ConfigDict(frozen=True, extra="forbid")`.
- Type-clean under `mypy --strict`.
- Has its own pyproject + tests + README, can be cloned/copied as-is to a new repo.

### `backend/app/llm/` (Briefed-specific glue)

| Module | Contents |
|---|---|
| `app/llm/__init__.py` | Thin re-exports from `llmkit` for ergonomic imports |
| `app/llm/factory.py` | `build_briefed_llm_client(prompt_name, settings, session)` — wires SSM-loaded key, DB-backed `log_call` writing `PromptCallLog`, and the chosen sanitizer profile |
| `app/llm/prompt_logger.py` | The async callback that persists `PromptCallRecord` → `PromptCallLog` SQLAlchemy row |
| `app/llm/sanitizer_profile.py` | Returns the configured `Sanitizer` for Briefed (Presidio + identity scrubber wired with the user's email/name from `Settings`) |

The library does the heavy lifting; Briefed is a 4-file adapter.

---

## catalog.yml — schema

```yaml
version: 1

defaults:
  temperature: 0.2
  top_p: 1.0
  max_output_tokens: 2048
  timeout_seconds: 30
  json_mode: true

privacy:
  default_policy: strict       # strict | standard | off
  reidentify_responses: true   # restore <EMAIL_1> etc. in returned text
  no_logging_at_provider: true # set OpenRouter no-logging flags

models:
  gemini-flash:
    openrouter_id: google/gemini-flash-1.5
    cost_per_m_input_usd: 0.075
    cost_per_m_output_usd: 0.30
    daily_call_cap: null
    overrides:
      max_output_tokens: 4096

  claude-haiku:
    openrouter_id: anthropic/claude-haiku-4.5
    cost_per_m_input_usd: 1.00
    cost_per_m_output_usd: 5.00
    daily_call_cap: 100         # plan §19.15 hard cap preserved
    overrides: {}

chains:
  default:
    primary: gemini-flash
    fallbacks: [claude-haiku]

prompts:
  classify_v1:
    chain: default
    overrides:
      temperature: 0.0
    privacy_policy: strict      # override default
  summarize_relevant_v1:
    chain: default
    overrides:
      temperature: 0.4
  job_extract_v1:
    chain: default
  unsubscribe_borderline:
    chain: default
```

**Resolution order** for any sampling parameter:
`prompts.<name>.overrides` → `models.<name>.overrides` → `defaults`.

**Validation rules** (Pydantic):
- Every `prompts.*.chain` references an existing chain.
- Every `chains.*.primary` and fallbacks reference existing models.
- `version == 1`.
- Numeric ranges checked.
- All entries frozen + `extra="forbid"`.

---

## Privacy + redaction design

### Sanitizer interface (in `llmkit`)

```python
class Sanitizer(Protocol):
    def sanitize(self, text: str) -> RedactionResult: ...

@dataclass(frozen=True)
class RedactionResult:
    text: str                          # the redacted prompt
    reversal_map: dict[str, str]       # token → original (kept in memory only)
    counts_by_kind: dict[str, int]     # {"EMAIL": 2, "PHONE": 1} — safe to log
```

`SanitizerChain` composes multiple sanitizers; later ones see the
already-redacted output. The chain returns a merged reversal map.

### Built-in sanitizers

| Sanitizer | Detects | Notes |
|---|---|---|
| `RegexSanitizer` | emails, phones (NANP + intl), SSN, US ZIP, IPs, URLs, MRN-shaped IDs (`MRN-\d{6,}`) | Always-on default. Zero deps. |
| `PresidioSanitizer` | Names, addresses, dates, NRP, US driving license, IBAN, credit card, medical license, …  full Presidio list | Optional extra. Catches what regex misses (esp. names). |
| `IdentityScrubber` | Operator-supplied tokens — caller passes user's email + display name + account ID at construction; sanitizer replaces those exact strings with `<USER_EMAIL>` / `<USER_NAME>` / `<USER_ID>` | Lets Briefed strip *its own user's* identity from prompts. |

### Re-identification (round-trip)

`Reidentifier` accepts the LLM response and the reversal map; replaces
tokens back. Toggleable per call (`reidentify=False` for content that
will be stored externally, e.g. analytics).

### LLMClient integration

`LLMClient.call(...)` gains:
- `sanitizer: Sanitizer | None = None`
- `reidentify: bool = True`

Flow:
1. `rendered_prompt` → `sanitizer.sanitize()` → redacted prompt + reversal map.
2. Provider sees only the redacted prompt.
3. Response payload comes back; if `reidentify=True`, walk the parsed Pydantic object's string fields and re-identify.
4. `PromptCallRecord` gets `redaction_counts` field added (just the `counts_by_kind` dict). Reversal map is discarded after step 3.

### OpenRouter privacy headers

Set on every request:
- `X-Title: Briefed` (generic, no per-user info)
- No `HTTP-Referer` (defaults to nothing rather than leaking)
- Body field `provider: { data_collection: "deny" }` — restricts to providers that don't log/train on inputs.
- Body field `transforms: ["middle-out"]` only if explicitly enabled per-call (it edits prompt content; off by default for traceability).

### Audit log

`PromptCallLog` schema gains a JSON column `redaction_summary` storing
`{kind: count}` only. **Never the values.** A nightly query can spot
unusual redaction-count spikes for an integrity check.

### Hard fail-safes

- If `privacy_policy=strict` and the sanitizer detects ≥ 1 `MRN`, `SSN`, or `MEDICAL_LICENSE` entity AND no Reidentifier was wired, raise `RedactionError` and abort the call.
- Library refuses to send if `api_key` is empty (already true).
- Library refuses to send if `sanitizer is None and policy != "off"` (defence in depth — caller has to opt out).

---

## Phase 0 — Discovery + 2 ADRs

**Goal**: lock the design in writing.

### 0.1 — Investigate current LLM settings shape
- Read [backend/app/core/config.py](../../backend/app/core/config.py) — capture exact shape of any `LLMSettings` / `llm.fallback_chain` field.
- Re-read the four `LLMClient(...)` sites in [backend/app/lambda_worker.py:248-498](../../backend/app/lambda_worker.py).
- Re-read [backend/app/llm/providers/__init__.py](../../backend/app/llm/providers/__init__.py).

### 0.2 — Confirm OpenRouter capabilities
- Curl test: JSON-mode (`response_format: {type: "json_object"}`) against `google/gemini-flash-1.5` and `anthropic/claude-haiku-4.5`.
- Curl test: `provider.data_collection: "deny"` actually filters the route list.
- Confirm `usage.cost` field shape.

### 0.3 — ADR 0009 (supersedes 0002)
- New file: [docs/adr/0009-openrouter-via-catalog-and-llmkit.md](../../docs/adr/0009-openrouter-via-catalog-and-llmkit.md).
- Decision: OpenRouter as sole direct provider, driven by `llmkit` library + `catalog.yml`.
- Consequences: 5–10% cost markup, single point of failure (mitigated by chain-level fallback within OR), much simpler ops.
- Mark ADR 0002 status `Superseded by 0009`.
- Update [docs/adr/README.md](../../docs/adr/README.md).

### 0.4 — ADR 0010 (privacy stance)
- New file: [docs/adr/0010-llm-privacy-redaction.md](../../docs/adr/0010-llm-privacy-redaction.md).
- Decision: redact-before-send (Presidio + regex + identity scrubber); HIPAA path chosen above; legal review checkpoint before any clinical use.
- Consequences: every LLM call adds ~10-50ms for redaction; some accuracy loss when names matter; no PHI in any external log.

**Exit**: both ADRs committed; HIPAA path explicit.

---

## Phase 1 — Scaffold `llmkit`

**Goal**: empty-but-installable package skeleton, wired into Briefed's dev install.

### 1.1 — Package layout
```
packages/llmkit/
  pyproject.toml
  README.md
  src/llmkit/
    __init__.py
    client.py            # placeholders
    catalog.py
    prompt.py
    errors.py
    factory.py
    providers/
      __init__.py
      base.py
      openrouter.py
    redaction/
      __init__.py
      regex_sanitizer.py
      presidio_sanitizer.py
      identity.py
  tests/
    conftest.py
```

### 1.2 — pyproject
- Build backend: `hatchling` (lightweight, no extra dev tooling).
- `name = "llmkit"`, `version = "0.1.0"`, `requires-python = ">=3.11"`.
- Core deps: `pydantic>=2.5`, `httpx>=0.27`, `pyyaml>=6`.
- Optional extras:
  - `presidio = ["presidio-analyzer>=2.2", "presidio-anonymizer>=2.2", "spacy>=3.7"]`
  - `dev = ["pytest", "pytest-asyncio", "respx", "ruff", "mypy"]`
- `[tool.ruff]` and `[tool.mypy]` mirror Briefed's strict settings.

### 1.3 — Editable install in Briefed
- Add to root [pyproject.toml](../../pyproject.toml) (or `backend/pyproject.toml` — confirm in 0.1):
  - `llmkit @ {root:uri}/packages/llmkit` for path install, OR
  - `[tool.uv.sources] llmkit = { workspace = true }` if uv workspaces, OR
  - dev install via `pip install -e packages/llmkit[presidio]` from the Makefile.
- Update [Makefile](../../Makefile) `bootstrap` target to run the editable install.

### 1.4 — Tests directory ready
- `pytest packages/llmkit/tests -q` runs (zero tests, 0 errors).
- CI: extend [.github/workflows/ci.yml](../../.github/workflows/ci.yml) to include `packages/llmkit` in the test + lint matrix.

**Exit**: `from llmkit import client` succeeds inside Briefed; no behaviour change anywhere.

---

## Phase 2 — Move generic primitives into `llmkit`

**Goal**: lift `LLMClient`, `Catalog`, prompt rendering, errors, breaker, rate cap, provider protocol into the library. Preserve the existing `LLMClient` API exactly so Briefed still imports it (now via re-export).

### 2.1 — Move + adapt
- `backend/app/llm/client.py` → `packages/llmkit/src/llmkit/client.py`. Strip the `from app.core.clock import utcnow` and `from app.core.logging import get_logger` imports — replace with stdlib equivalents (`datetime.now(UTC)`, `logging.getLogger`).
- `backend/app/llm/providers/base.py` → `packages/llmkit/src/llmkit/providers/base.py`. No changes.
- Catalog modules (Phase 1 placeholders) → real implementations.
- `render_prompt` + `PromptSpec` → `packages/llmkit/src/llmkit/prompt.py`.
- Add `packages/llmkit/src/llmkit/errors.py` consolidating exception classes.

### 2.2 — Briefed shim
- Replace `backend/app/llm/client.py` with a 5-line file that just re-exports from `llmkit` so existing imports `from app.llm.client import LLMClient` keep working. (Phase 7 deletes this shim.)
- Same for `backend/app/llm/providers/base.py`.

### 2.3 — Tests
- Move `backend/tests/unit/test_llm_client.py` → `packages/llmkit/tests/test_client.py`. Adjust imports.
- Verify the **100%-coverage pin on LLMClient** is preserved — it's still 100%, just in a new location. Update CLAUDE.md §8 accordingly.
- Add catalog tests (Phase 1.4 in old plan, now lives here): valid load, invalid version, missing chain ref, missing model ref, override resolution, frozen instances.

### 2.4 — Lint + type
- `ruff check packages/llmkit` clean.
- `mypy --strict packages/llmkit/src` clean.
- Briefed's `mypy --strict backend/app` still clean (because the shim re-exports).

**Exit**: library has client + catalog + protocol; Briefed unchanged behaviourally.

---

## Phase 3 — OpenRouter provider in `llmkit`

**Goal**: ship `OpenRouterProvider` in the library, fully tested.

### 3.1 — Implementation
- `packages/llmkit/src/llmkit/providers/openrouter.py`.
- Constructor: `(api_key, http_client, endpoint="https://openrouter.ai/api/v1/chat/completions", app_title="llmkit")`.
- `complete_json(spec, *, rendered_prompt) -> LLMCallResult`:
  - Body: `model = spec.model`, OpenAI-style messages, `temperature`, `max_tokens`, `top_p`, `response_format` when `spec.json_mode`, `provider: {data_collection: "deny"}`, `usage: {include: true}`.
  - Headers: `Authorization: Bearer …`, `X-Title: …`. **No** `HTTP-Referer`.
  - Error mapping: 429/5xx → retryable; 4xx auth/validation → non-retryable; JSON parse fail → non-retryable.
  - Cost: prefer `data.usage.cost`; fall back to caller-supplied rates × tokens (the catalog rates).
  - Tokens: `prompt_tokens`, `completion_tokens`, `prompt_tokens_details.cached_tokens` when present.

### 3.2 — Tests
- `packages/llmkit/tests/test_openrouter_provider.py` with `respx`:
  - happy path
  - 429 retryable / 500 retryable / 401 non-retryable
  - JSON-mode header sent
  - `provider.data_collection: deny` body field present
  - cost from `usage.cost`
  - cost fallback to rates
  - empty api_key raises at construction
- Coverage: 100% on this file.

**Exit**: library can talk to OpenRouter end-to-end (manual test with a real key).

---

## Phase 4 — Redaction layer in `llmkit`

**Goal**: `Sanitizer`, `RegexSanitizer`, `PresidioSanitizer`, `IdentityScrubber`, `SanitizerChain`, `Reidentifier`, integrated into `LLMClient.call`.

### 4.1 — Core types + protocol
- `packages/llmkit/src/llmkit/redaction/__init__.py`: `Sanitizer` protocol, `RedactionResult`, `RedactionError`, `Reidentifier`.

### 4.2 — RegexSanitizer
- Patterns: email (RFC 5322 simplified), NANP phone, intl phone, SSN, US ZIP, IPv4, IPv6, common URLs, MRN (`MRN-\d{6,}` configurable). All compiled at module load.
- Each match becomes `<KIND_N>` token with stable counter per `sanitize()` call.
- Reversal map populated on the fly.

### 4.3 — PresidioSanitizer
- Lazy-import Presidio inside the class so the optional dep can be missing without breaking core imports.
- Uses Presidio's `AnalyzerEngine` + `AnonymizerEngine`. Anonymizer config replaces detected entities with `<KIND_N>` tokens.
- Recognizers: default English set + custom `MRN` pattern recognizer.

### 4.4 — IdentityScrubber
- Constructor: `IdentityScrubber(user_identifiers: dict[str, str])` — e.g. `{"USER_EMAIL": "khirijaganer@…", "USER_NAME": "Kartik Hirijaganer"}`.
- Plain string replacement (case-insensitive) — runs *before* Presidio so the user's literal email is replaced with `<USER_EMAIL>` rather than a generic `<EMAIL_1>`.

### 4.5 — SanitizerChain + Reidentifier
- `SanitizerChain([IdentityScrubber, PresidioSanitizer, RegexSanitizer])` — typical Briefed config.
- `Reidentifier.reidentify(text, reversal_map) -> str`: longest-token-first replacement to avoid `<EMAIL_10>` partially matching `<EMAIL_1>`.

### 4.6 — LLMClient integration
- `LLMClient.call(...)` gains `sanitizer: Sanitizer | None = None`, `reidentify: bool = True`.
- After provider returns, walk `parsed: BaseModel` recursively; for every `str` field, run `Reidentifier`.
- `PromptCallRecord` gains `redaction_counts: dict[str, int] | None`.
- New error: `RedactionError`. Raised at `LLMClient.call` boundary if a "must-not-leak" entity (configurable) survives sanitization (covers regex misses).

### 4.7 — Tests
- `tests/test_regex_sanitizer.py`: every kind detected; tokens stable per call; reversal_map round-trips.
- `tests/test_presidio_sanitizer.py`: skip if Presidio not installed; otherwise verify name + address detection.
- `tests/test_identity_scrubber.py`: case-insensitive, idempotent, leaves non-matches untouched.
- `tests/test_chain_and_reidentify.py`: full round-trip through a chain.
- `tests/test_llm_client_with_sanitizer.py`: provider sees only redacted prompt; response is reidentified; redaction_counts populated; strict-policy abort path.

**Exit**: full redaction stack shipped + tested in the library.

---

## Phase 5 — Wire Briefed to consume `llmkit`

**Goal**: every production LLM call goes through OpenRouter via `llmkit`, with Briefed's user identity scrubbed.

### 5.1 — Settings changes
- [backend/app/core/config.py](../../backend/app/core/config.py):
  - Remove `gemini_api_key`, `anthropic_api_key`.
  - Add `openrouter_api_key: str | None = None`.
  - Update `_SSM_FIELD_MAP` and `_REQUIRED_SECRETS` accordingly.
  - Add `llm_catalog_path: Path = Path("packages/config/llm/catalog.yml")` (note: the *catalog file* lives in Briefed config, not the library — the library defines the schema, the project defines the values).

### 5.2 — Briefed factory
- `backend/app/llm/factory.py`:
  - `build_briefed_llm_client(prompt_name, *, settings, session, http_client, user) -> LLMClient`.
  - Reads catalog via `llmkit.load_catalog(settings.llm_catalog_path)`.
  - Builds `OpenRouterProvider` for primary + each fallback in the chain.
  - Builds `IdentityScrubber({"USER_EMAIL": user.email, "USER_NAME": user.display_name})`.
  - Composes `SanitizerChain([identity, presidio, regex])`.
  - Wraps Briefed's DB writer (`prompt_logger.py`) into the `log_call` callback that writes a `PromptCallLog` row including `redaction_summary`.

### 5.3 — Briefed prompt logger
- `backend/app/llm/prompt_logger.py`:
  - Async function `log_to_db(record: PromptCallRecord, *, session) -> None`.
  - Writes one row to `prompt_call_logs`. New column `redaction_summary` (Phase 8 migration).

### 5.4 — Refactor `lambda_worker.py` construction sites
- All four call sites at [backend/app/lambda_worker.py:274,372,433,498](../../backend/app/lambda_worker.py): replace inline `GeminiProvider(...)` with `build_briefed_llm_client(prompt_name, ...)`.
- Drop deferred `from app.llm.providers import GeminiProvider` imports (lines 248, 348, 414, 473).

### 5.5 — Update integration tests
- The fakes in [test_classification_pipeline.py](../../backend/tests/integration/test_classification_pipeline.py), [test_summarize_tech_news_pipeline.py](../../backend/tests/integration/test_summarize_tech_news_pipeline.py), [test_unsubscribe_dispatch.py](../../backend/tests/integration/test_unsubscribe_dispatch.py): rename provider slug from `"gemini"` to `"openrouter"` where asserted; verify sanitizer is invoked.

**Exit**: all live paths route through OpenRouter via `llmkit`; sanitizer wired; full pytest suite green.

---

## Phase 6 — Briefed-specific PHI guardrails

**Goal**: defence-in-depth specific to a healthcare-domain account.

### 6.1 — DB migration
- Alembic revision: add `redaction_summary JSONB` column to `prompt_call_logs`. Run upgrade + downgrade locally.

### 6.2 — Mailbox allowlist (option (b) layer)
- New `Settings.mailbox_domain_allowlist: list[str] = []` (empty = allow all; explicit list = strict mode).
- `MailboxProvider.connect()` rejects connections whose primary address domain isn't in the allowlist when set.
- Config path documented in [docs/operations/secrets-rotation.md](../../docs/operations/secrets-rotation.md) (rename to runbook section).

### 6.3 — Outbound prompt audit
- Nightly Lambda (or cron in dev) scans last-24h `prompt_call_logs` for `redaction_summary` containing high-risk kinds (MRN, SSN, MEDICAL_LICENSE) above threshold. Emits a CloudWatch alarm.
- Implemented in `backend/app/workers/handlers/redaction_audit.py`.

### 6.4 — Pre-flight content check (extra-strict path)
- Optional `Settings.llm_strict_phi_block: bool = False`. When true, after sanitization Briefed runs Presidio *again* on the redacted prompt — if any PHI-class entity is detected (i.e. the first pass missed one), the LLM call is aborted with `RedactionError` and the email is flagged for human review.

### 6.5 — Tests
- `backend/tests/unit/test_redaction_audit.py`: alarm fires on threshold breach.
- `backend/tests/unit/test_mailbox_allowlist.py`: rejects out-of-allowlist domains.
- `backend/tests/integration/test_phi_guardrail.py`: end-to-end — email containing fake MRN flows through pipeline, MRN is `<MRN_1>` in the OpenRouter request, response is reidentified, `redaction_summary` recorded.

**Exit**: Briefed-side guardrails running; alarm wired.

---

## Phase 7 — Delete legacy code

### 7.1 — Delete provider modules
- `rm backend/app/llm/providers/gemini.py`
- `rm backend/app/llm/providers/anthropic.py`
- `rm backend/app/llm/providers/anthropic_batch.py`
- Update [backend/app/llm/providers/__init__.py](../../backend/app/llm/providers/__init__.py) to drop legacy exports; keep the `OpenRouterProvider` re-export for ergonomics.
- Delete the Phase 2 shims: `backend/app/llm/client.py` (re-export), `backend/app/llm/providers/base.py` (re-export). Replace remaining imports with `from llmkit import …`.

### 7.2 — Delete legacy tests
- `grep -lrn "GeminiProvider\|AnthropicProvider" backend/tests/` → remove or rewrite.

### 7.3 — Verify
- `make coverage` ≥ 80% (LLMClient now in llmkit but still 100%).
- `make test` clean.
- `git grep -i 'gemini\|anthropic'` returns only ADR/doc references (no live code).

**Exit**: Briefed code is clean of direct-SDK references.

---

## Phase 8 — Infra + secrets

### 8.1 — Terraform
- [infra/terraform/modules/ssm/main.tf](../../infra/terraform/modules/ssm/main.tf): drop the two old `aws_ssm_parameter` resources; add `openrouter_api_key`.
- [infra/terraform/envs/dev/main.tf](../../infra/terraform/envs/dev/main.tf): drop variable inputs for old keys, add OpenRouter.
- [infra/terraform/modules/alarms/](../../infra/terraform/modules/alarms/): rename Gemini/Anthropic-specific alarms to `openrouter` + add the new `phi_redaction_anomaly` alarm from 6.3.

### 8.2 — Manual secret ops
- `aws ssm put-parameter --name /briefed/dev/openrouter_api_key --value "sk-or-..." --type SecureString --key-id alias/briefed-secrets`
- `aws ssm delete-parameter --name /briefed/dev/gemini_api_key`
- `aws ssm delete-parameter --name /briefed/dev/anthropic_api_key`

### 8.3 — Local dev .env
- [.env.example](../../.env.example): drop `GEMINI_API_KEY` and `ANTHROPIC_API_KEY`; add `OPENROUTER_API_KEY=`.

### 8.4 — Rotation runbook
- Update [docs/operations/secrets-rotation.md](../../docs/operations/secrets-rotation.md): replace Gemini/Anthropic rotation with OpenRouter; note the no-logging flag must be re-verified after key rotation.

**Exit**: `terraform plan` clean; `make run` works locally with a real key.

---

## Phase 9 — Docs + final testing

### 9.1 — README
- [README.md](../../README.md): stack section update, env var update, mention `packages/llmkit/` and `packages/config/llm/catalog.yml`. Per CLAUDE.md §5 this is required.

### 9.2 — `packages/llmkit/README.md`
- Quickstart for using the library outside Briefed:
  ```python
  import asyncio, httpx
  from llmkit import build_client_from_catalog, load_catalog, PromptSpec
  from llmkit.redaction import RegexSanitizer

  async def main() -> None:
      catalog = load_catalog("./catalog.yml")
      async with httpx.AsyncClient() as http:
          client = build_client_from_catalog(
              prompt_name="classify_v1",
              catalog=catalog,
              api_key="sk-or-…",
              http_client=http,
              sanitizer=RegexSanitizer(),
          )
          spec = PromptSpec(name="classify_v1", version="1", model="google/gemini-flash-1.5", content="…")
          resp = await client.call(spec=spec, rendered_prompt="…", schema=MySchema, prompt_version_id=…)
          print(resp.parsed)

  asyncio.run(main())
  ```
- API reference: brief docstring listing of public symbols.
- Privacy section: how the redaction layer works, how to add custom recognizers, what gets logged.

### 9.3 — Threat model + ops docs
- [docs/security/threat-model.md](../../docs/security/threat-model.md): OpenRouter trust boundary; redaction layer as primary control; HIPAA disclaimer.
- [docs/operations/runbook.md](../../docs/operations/runbook.md): single-provider failure mode; redaction audit alarm response.
- [docs/operations/alarms.md](../../docs/operations/alarms.md): rename + add the new alarm.

### 9.4 — CLAUDE.md update
- Update §1 build-rules' note about LLM client coverage pin → point to `packages/llmkit`.
- Update §9 architecture section to describe the `llmkit` boundary.

### 9.5 — Final smoke test
- `make bootstrap && make test` clean.
- `make coverage` ≥ 80%, pinned modules at 100%.
- `make docs` regenerates OpenAPI cleanly.
- Manual end-to-end: trigger a fanout with a real OpenRouter key, observe one classify + one summarize call go through, verify `prompt_call_logs.redaction_summary` is populated and contains no raw PII.

**Exit**: branch ready for PR review.

---

## Risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| **HIPAA exposure** through PHI in unredacted prompts | Med | Severe | Layered redaction (regex + Presidio + identity); strict-policy abort; mailbox allowlist; legal review checkpoint before clinical use; ADR 0010 documents residual risk |
| Presidio misses a PHI class (false negative) | Med | Severe | Custom recognizers for MRN-shaped IDs; alarm on outliers; `llm_strict_phi_block` second-pass option |
| OpenRouter outage = total LLM outage | Low–Med | High | OR's internal redundancy across providers; chain has primary + fallback; daily run can re-attempt next cycle |
| OR JSON-mode unreliable on some routes | Med | Med | Phase 0.2 verifies; per-model fallback in catalog; prompt-based JSON contract as last resort |
| Library API instability while still in early dev | High | Low (in-monorepo) | Path-installed editable; semver doesn't matter while it's a workspace package; freeze API at v1.0 only when extracted to a separate repo |
| Gemini-via-OR is more expensive than direct | Cert. (5–10%) | Low | Documented in ADR 0009 |
| Catalog drift: prompt added without entry | Med | Med | `Catalog.resolve(prompt_name)` raises; integration test checks every Briefed prompt has an entry |
| 100%-coverage regression on LLMClient during move | Low | Med | Lift-and-shift, not rewrite; tests move alongside; CI matrix covers `packages/llmkit` |
| Re-identification leaks tokens to external storage | Med | Med | `reidentify=False` mode; default off for any flow whose response is persisted unencrypted; integration test asserts |
| Identity scrubber misses a variant (e.g. `kartik.h@…` instead of `khirijaganer@…`) | Low | Med | IdentityScrubber accepts a list of variants; Presidio's name detection is the safety net |
| Library used in another project picks up Briefed-specific assumptions | Low | Low | Hard rules in §"Library boundary" — no `app.*` imports; reviewed in Phase 9 |

## Out of scope

- Publishing `llmkit` to PyPI. Premature.
- Streaming responses.
- Prompt caching (separate plan).
- BAA path (option (c) above) — only if you decide to go that way.
- Akeyless integration. Decided against.
- Migrating existing prompt YAML to add new `model` fields per-prompt — the catalog injects model resolution at runtime.

## Estimated effort

| Phase | Effort |
|---|---|
| 0 — Discovery + 2 ADRs | 1 day |
| 1 — Scaffold llmkit | 0.5 day |
| 2 — Move primitives | 1 day |
| 3 — OpenRouter provider | 1 day |
| 4 — Redaction layer | 2 days (Presidio is fiddly) |
| 5 — Wire Briefed | 1.5 days |
| 6 — PHI guardrails | 1 day |
| 7 — Delete legacy | 0.5 day |
| 8 — Infra + secrets | 0.5 day |
| 9 — Docs + final | 1 day |

**Total: ~10 days.** Recommend one PR per phase; phases 1–4 are
purely additive (no behaviour change in Briefed), so they can land
independently and let the library stabilize before the cutover in
Phase 5.
