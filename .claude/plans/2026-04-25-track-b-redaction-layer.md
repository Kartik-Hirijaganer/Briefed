# 2026-04-25 — Track B: PII redaction layer

Wrap every outbound LLM prompt in a sanitizer chain. Designed against
an explicit threat model, not as privacy theater.

**Independent of Track A** — the sanitizer chain wraps any
`LLMProvider`, OR-based or otherwise. Has a soft dependency on Track C
(user profile fields drive the identity scrubber); until C lands, the
identity scrubber reads from settings/env.

---

## Locked decisions

1. **Threat model is written down before code.** ADR 0010 (one page)
   states *who* the redaction protects against and *what* it does and
   does not stop.
2. **Default stack is regex + identity + Presidio.** Presidio is **on
   by default**, not an optional extra. Regex alone misses too much
   (names in subjects, phones in non-standard formats, emails inside
   HTML attributes). User can disable Presidio via a setting if it
   regresses summarization quality unacceptably.
3. **Reidentification defaults to `False`.** The reversal map only
   knows what *we* scrubbed; the LLM can hallucinate a string matching
   a placeholder pattern. Reidentify only on flows where the response
   is ephemeral and not persisted.
4. **Audit log records counts, not values.** A JSONB column
   `prompt_call_logs.redaction_summary` stores `{kind: count}`.
5. **Sanitizers live in `backend/app/llm/redaction/`.** Same boundary
   as the rest of LLM code; no library extraction.
6. **Quality regression is measured, not assumed.** A small eval set
   (5 representative emails) compares summarization quality with and
   without redaction; documented in the ADR.

## Out of scope (here)

- Library extraction.
- DLP-grade detection (entity linking, document classification).
- Per-tenant policies (single user).

---

## Phase 0 — Threat model + ADR 0010

One page; lands first; gates the rest.

- [ ] New file [docs/adr/0010-llm-prompt-redaction.md](../../docs/adr/0010-llm-prompt-redaction.md).
- [ ] Sections:
  - **Threat actors**: OpenRouter (intermediary that sees prompts in
    transit + may briefly buffer them); OR's downstream providers
    (Google, Anthropic) under their own no-train terms; an
    on-path-attacker against TLS (out of scope, network-layer).
  - **What redaction stops**: user-identifying tokens (email, name,
    user-id, account aliases) and incidental PII (other phones,
    emails, addresses) in the *prompt body*. Reduces blast radius if
    OR or a downstream provider were ever breached or subpoenaed.
  - **What redaction does not stop**: the existence of a request, its
    timing, its size, the sender's IP. Behavioral patterns inferable
    from prompts even after redaction. Anything an LLM hallucinates.
  - **Cost acknowledgments**: Presidio adds ~200ms cold-start +
    ~30-80ms per call; may degrade summarization quality on
    name-heavy emails; reidentification on response is dangerous and
    is off by default.
- [ ] Phase 6 quality eval will be appended to the ADR.

**Exit**: ADR 0010 staged; threat actors named; cost acknowledged.

---

## Phase 1 — Sanitizer protocol + regex sanitizer

- [ ] New module [backend/app/llm/redaction/](../../backend/app/llm/redaction/).
- [ ] Files:
  ```
  redaction/
    __init__.py        # public re-exports
    types.py           # Sanitizer protocol, RedactionResult
    chain.py           # SanitizerChain (composition)
    regex_sanitizer.py # zero-deps regex implementation
    identity.py        # IdentityScrubber
    presidio.py        # PresidioSanitizer (real dep, not optional)
  ```
- [ ] `Sanitizer` protocol:

  ```python
  class Sanitizer(Protocol):
      def sanitize(self, text: str) -> RedactionResult: ...

  @dataclass(frozen=True)
  class RedactionResult:
      text: str
      reversal_map: dict[str, str]   # placeholder -> original
      counts_by_kind: dict[str, int]
  ```

- [ ] `RegexSanitizer` covers: emails, phones (E.164 + US-formatted),
  US SSN, US ZIP, IPv4/v6, URLs. Each match is replaced with
  `<KIND_N>` and recorded in `reversal_map` + `counts_by_kind`.
- [ ] Tests: golden inputs for each kind; idempotency
  (`sanitize(sanitize(x).text) == sanitize(x)`); empty input.

---

## Phase 2 — Identity scrubber

- [ ] `IdentityScrubber` accepts a dict of `{placeholder: list[str]}`
  at construction:

  ```python
  IdentityScrubber({
      "<USER_EMAIL>": ["kartik@example.com", "alias@example.com"],
      "<USER_NAME>":  ["Kartik Hirijaganer", "Kartik H"],
      "<USER_ID>":    ["uuid-..."],
  })
  ```

- [ ] Replacements are case-insensitive, longest-match-first to avoid
  partial matches eating substrings.
- [ ] Tests: longest-match-first semantics, case folding, overlap with
  regex sanitizer (identity runs first; regex picks up residue).

---

## Phase 3 — Presidio sanitizer

- [ ] `PresidioSanitizer` wraps `presidio_analyzer.AnalyzerEngine` +
  `presidio_anonymizer.AnonymizerEngine`.
- [ ] Engine is module-level (loaded once at cold-start; SnapStart
  bakes it into the snapshot).
- [ ] Recognizers enabled: `PERSON`, `LOCATION`, `DATE_TIME`,
  `PHONE_NUMBER`, `EMAIL_ADDRESS`, `IBAN_CODE`, `CREDIT_CARD`.
- [ ] `presidio-analyzer` + `presidio-anonymizer` added as **regular
  dependencies** in [pyproject.toml](../../pyproject.toml). No `extra`.
- [ ] Setting `redaction_presidio_enabled: bool = True` in
  [backend/app/core/config.py](../../backend/app/core/config.py) — flip
  to disable if quality regresses.
- [ ] Tests stub the Presidio engine; one opt-in live test guarded by
  `PRESIDIO_LIVE=1` covering a real model load.

---

## Phase 4 — Sanitizer chain + LLMClient integration

- [ ] `SanitizerChain([identity, regex, presidio])` runs sanitizers in
  sequence; merges `reversal_map` (later wins on collision) and sums
  `counts_by_kind`.
- [ ] [backend/app/llm/client.py](../../backend/app/llm/client.py)
  `LLMClient.call(...)` gains:
  - `sanitizer: Sanitizer | None = None`
  - `reidentify: bool = False` (note the default)
- [ ] Behavior:
  1. If `sanitizer` is set, sanitize *before* sending to provider.
  2. Provider sees only redacted text.
  3. If `reidentify=True`, post-process the response by replacing
     placeholders with originals from `reversal_map`. Otherwise leave
     placeholders intact in the response.
  4. `PromptCallRecord.redaction_counts` populated regardless.
- [ ] Construction in [backend/app/lambda_worker.py](../../backend/app/lambda_worker.py)
  builds the chain from settings (Track A's catalog wiring) and passes
  it as a kwarg.
- [ ] Hardcoded list of flows that may set `reidentify=True`
  (currently: none — every flow persists or renders the response).
  Adding a flow to that list requires an ADR amendment.

---

## Phase 5 — Audit log column

- [ ] Alembic revision adds
  `prompt_call_logs.redaction_summary JSONB NULL`. Always written when
  a sanitizer was applied; null otherwise.
- [ ] [backend/app/db/models.py](../../backend/app/db/models.py)
  updated.
- [ ] Worker logger writes `{kind: count}` only — never `reversal_map`.
- [ ] Code-review checklist in
  [docs/adr/0010-llm-prompt-redaction.md](../../docs/adr/0010-llm-prompt-redaction.md):
  "If you log a `RedactionResult`, log only `counts_by_kind`."

---

## Phase 6 — Quality eval

Run before defaulting Presidio on for everyone.

- [ ] Pick 5 representative emails from the user's own inbox covering
  the common shapes: newsletter, person-to-person, notification, job
  alert, calendar invite.
- [ ] For each, run `summarize_relevant_v1` three ways:
  1. raw
  2. regex + identity only
  3. full chain (regex + identity + Presidio)
- [ ] Capture: time-to-first-token, total latency, response length,
  qualitative quality (1-5 score, written by user).
- [ ] Append a table to ADR 0010. If full chain regresses quality
  meaningfully, set `redaction_presidio_enabled = False` and revisit.

---

## Phase 7 — Coupling with Track C (when it lands)

While Track C is in flight, the IdentityScrubber reads from settings:
`BRIEFED_USER_EMAIL`, `BRIEFED_USER_NAME`, `BRIEFED_USER_ALIASES`.

When Track C ships the user profile fields, swap the construction site
to read from the profile row instead. Setting-based fallback can stay
for tests.

This is a one-line change at the Briefed factory site; tracked here as
a checklist item, not a separate phase.

---

## Risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Reidentification leaks hallucinated content | Med | Med | Default `reidentify=False`; explicit ADR-gated flow allowlist |
| RegexSanitizer misses something obvious | Med | Low | Identity scrubber catches user-specific data deterministically; Presidio NER catches the rest |
| Presidio degrades summarization quality | Med | Med | Phase 6 eval; toggle to disable; ADR documents the trade-off |
| Presidio cold-start regresses Lambda init | Low–Med | Low | Module-level engine load; SnapStart snapshots it |
| Audit log accidentally captures reversal_map | Low | High | Code-review rule + a unit test that asserts the log row has only `counts_by_kind` |

## Estimated effort

| Phase | Effort |
|---|---|
| 0 — Threat model + ADR 0010 | ½ day |
| 1 — Sanitizer protocol + regex | ½ day |
| 2 — Identity scrubber | ¼ day |
| 3 — Presidio sanitizer | ½ day |
| 4 — Chain + LLMClient integration | ½ day |
| 5 — Audit log column | ¼ day |
| 6 — Quality eval | ½ day (mostly waiting + reading) |

**Total: ~2.5 days.**
