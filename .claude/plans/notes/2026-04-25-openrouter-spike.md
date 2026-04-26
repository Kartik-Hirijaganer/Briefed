# 2026-04-25 — OpenRouter spike (Track A, Phase 0)

This note is the go/no-go gate for Track A. Per the plan, Phases 1–7
**must not land in prod** until every box below is checked and the
go/no-go decision is recorded.

The deterministic implementation work (ADR, catalog, provider, factory,
cost guard, tests) was authored in advance of running the spike so the
diff is reviewable; the cutover (Phase 6) is the gating point.

## Status

- **Spike run by:** _(operator)_
- **Spike date:** _YYYY-MM-DD_
- **Decision:** ☐ go ☐ no-go

## 1. JSON-mode round-trip — Gemini 2.0 Flash via OpenRouter

```sh
curl https://openrouter.ai/api/v1/chat/completions \
  -H "Authorization: Bearer $OPENROUTER_API_KEY" \
  -H "X-Title: Briefed" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "google/gemini-2.0-flash-001",
    "response_format": {"type": "json_object"},
    "provider": {"data_collection": "deny"},
    "transforms": [],
    "messages": [
      {"role": "user", "content": "Reply with JSON {\"ok\": true, \"reason\": \"hi\"}"}
    ]
  }'
```

- ☐ HTTP 200
- ☐ `choices[0].message.content` parses as JSON object
- ☐ `usage.cost` field present (and a number)

Observed `usage.cost`: __________ USD.

## 2. JSON-mode round-trip — Claude Haiku 4.5 via OpenRouter

Same body, swap `model` to `anthropic/claude-haiku-4.5`.

- ☐ HTTP 200
- ☐ JSON object back
- ☐ `usage.cost` present

Observed `usage.cost`: __________ USD.

## 3. `data_collection: deny` accepted on both routes

- ☐ Gemini route returned a result (not an "all deny-supporting providers
      filtered" error)
- ☐ Claude route returned a result

If a route refuses `data_collection: deny`, escalate before cutover —
that is the no-training guarantee Phase 1 ADR 0009 promises.

## 4. Pricing delta vs. direct providers

|                                | Direct ($/M in) | Direct ($/M out) | OR ($/M in) | OR ($/M out) | Δ |
|--------------------------------|-----------------|------------------|-------------|--------------|---|
| Gemini 1.5/2.0 Flash           | 0.075           | 0.300            |             |              |   |
| Claude Haiku 4.5               | 0.80            | 4.00             |             |              |   |

Expected drift: 5–10% (per ADR 0009 risk register).

## 5. End-to-end smoke — `classify_v1` prompt

- ☐ Pull the latest `classify_v1` content from
      `packages/prompts/classify_v1/prompt.md`
- ☐ Render it with the test fixture in
      `packages/prompts/classify_v1/examples/`
- ☐ Send through OR → both routes
- ☐ Response parses against `TriageDecision` schema

## Decision

Record the go/no-go below (delete the not-applicable line):

- **GO** — proceed to cutover. Pricing column above is added to
  ADR 0009; CATALOG entries in `backend/app/llm/catalog.py` updated to
  match observed `usage.cost` if pricing differs from Phase 2 defaults
  by > 1%.
- **NO-GO** — open a follow-up issue describing the failure mode and
  hold the cutover. Phases 1–7 stay merged; the env flag remains
  `legacy` (default does not flip).
