# ADR 0010 — LLM prompt redaction

- **Date:** 2026-04-25
- **Status:** Accepted
- **Deciders:** Kartik Hirijaganer

## Context

Briefed forwards email content to LLM providers (Gemini Flash primary;
Claude Haiku 4.5 fallback per ADR 0002). Track A migrates the primary
fallback path through OpenRouter; either way the prompt body crosses
trust boundaries between Briefed and at least one third party.

We want a written, narrow contract for what redaction does and does not
protect against. The bar is "reduce the blast radius of an OR or
downstream-provider compromise / subpoena," not "eliminate identifiable
content." Privacy theatre is worse than no redaction because it lets the
codebase pretend a guarantee exists.

## Threat actors

- **OpenRouter** — intermediary that sees prompts in transit and may
  briefly buffer them on its infrastructure. Track A pins
  `X-OR-No-Train: true` and uses `OR-Site-Url`-anchored opt-outs, but the
  request body is plaintext to OR's edge regardless.
- **OR's downstream providers** — Google (Gemini), Anthropic (Claude),
  any other model OR routes to. Each is bound by its own no-train and
  data-handling terms. Redaction limits what those terms have to cover
  in the worst case.
- **On-path attacker against TLS** — out of scope. Network-layer
  protection is TLS 1.3 + certificate validation; redaction does not try
  to substitute for that.

## What redaction stops

User-identifying tokens (email, name, user-id, account aliases) and
incidental PII (other phones, emails, addresses) in the **prompt body**.
If OR or a downstream provider were ever breached or subpoenaed, the
prompt corpus would not directly tie a request to the user and would
contain fewer raw third-party PII strings.

## What redaction does not stop

- The existence of a request, its timing, its size, the sender's IP.
- Behavioural patterns inferable from prompts even after redaction (the
  user's interests, employer, schedule, family context).
- Anything an LLM hallucinates in the response — see reidentification
  cost below.
- Anything passed in non-prompt channels (logs, traces, error messages)
  — those have separate scrubbing rules.

## Decision

1. **Sanitizer chain wraps every outbound prompt.** Order is identity →
   regex → Presidio. Identity scrubber runs first so user-specific
   strings get a stable placeholder before regex picks up residue and
   Presidio fills in NER-grade PII the regex misses.
2. **Default stack is regex + identity + Presidio.** Presidio is on by
   default. Regex alone misses too much: names in subject lines, phones
   in non-standard formats, emails inside HTML attributes. The user can
   disable Presidio via `redaction_presidio_enabled` if it regresses
   summarisation quality unacceptably.
3. **Reidentification defaults to `False`.** The reversal map only
   knows what *we* scrubbed; the LLM can hallucinate a string matching
   a placeholder pattern and get reidentified to the wrong original.
   Reidentification is gated to an empty allowlist of flows in 1.0.0
   — adding a flow requires an ADR amendment.
4. **Audit log records counts, not values.** A JSONB column
   `prompt_call_log.redaction_summary` stores `{kind: count}`. The
   `reversal_map` never reaches persistence.
5. **Sanitizers live in `backend/app/llm/redaction/`.** Same boundary
   as the rest of LLM code; no premature library extraction.
6. **Quality regression is measured, not assumed.** Phase 6 of the
   Track B plan runs a 5-email eval (newsletter, person-to-person,
   notification, job alert, calendar invite) raw vs regex+identity vs
   full chain. Results are appended below.

## Cost acknowledgements

- Presidio adds ~200ms cold-start (model load) and ~30–80ms per call.
  Module-level engine load + SnapStart amortise the cold-start cost.
- Presidio may degrade summarisation quality on name-heavy emails by
  removing entities the model needs to disambiguate the sender.
- Reidentification on the response is dangerous and is off by default;
  the response carries placeholders unless explicitly reidentified.

## Code-review checklist

When touching any code that handles a `RedactionResult`:

- **Never log `reversal_map`.** Log only `counts_by_kind`.
- **Never persist `reversal_map`.** It exists only for the lifetime of
  one in-memory call.
- **`reidentify=True` requires an entry in the flow allowlist** in
  `backend/app/llm/client.py`. Adding a flow requires an ADR amendment
  to this document.

## Phase 6 — Quality eval

| Email kind        | Raw TTFT | Raw total | Regex+Id TTFT | Regex+Id total | Full TTFT | Full total | Quality (raw) | Quality (regex+id) | Quality (full) |
|-------------------|----------|-----------|---------------|----------------|-----------|------------|---------------|--------------------|----------------|
| Newsletter        | _TBD_    | _TBD_     | _TBD_         | _TBD_          | _TBD_     | _TBD_      | _TBD_         | _TBD_              | _TBD_          |
| Person-to-person  | _TBD_    | _TBD_     | _TBD_         | _TBD_          | _TBD_     | _TBD_      | _TBD_         | _TBD_              | _TBD_          |
| Notification      | _TBD_    | _TBD_     | _TBD_         | _TBD_          | _TBD_     | _TBD_      | _TBD_         | _TBD_              | _TBD_          |
| Job alert         | _TBD_    | _TBD_     | _TBD_         | _TBD_          | _TBD_     | _TBD_      | _TBD_         | _TBD_              | _TBD_          |
| Calendar invite   | _TBD_    | _TBD_     | _TBD_         | _TBD_          | _TBD_     | _TBD_      | _TBD_         | _TBD_              | _TBD_          |

Eval harness lives at `backend/scripts/redaction_quality_eval.py`. If
the full chain regresses quality meaningfully, set
`redaction_presidio_enabled = False` and revisit.

## Alternatives considered

- **No redaction; rely on provider terms alone.** Rejected — provider
  no-train terms protect future training, not breach / subpoena posture.
- **Regex only.** Rejected — misses names in subjects, phones in
  non-standard formats, emails in HTML attributes. Phase 6 eval pins
  the trade-off rather than assuming.
- **Per-tenant redaction policies.** Out of scope — Briefed is single-
  user in 1.0.0.
- **DLP-grade detection (entity linking, document classification).** Out
  of scope — heavyweight, latency hostile, dependency hostile, and the
  blast-radius reduction over Presidio is small.

## Revisit triggers

- Multi-tenant deployment lands.
- A reidentification flow becomes load-bearing for product UX.
- Presidio quality regression becomes severe enough that we want a
  trained NER alternative.
