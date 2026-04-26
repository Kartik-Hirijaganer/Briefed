# ADR 0002 — Gemini 1.5 Flash primary, Claude Haiku 4.5 gated fallback

- **Date:** 2026-04-19
- **Status:** Superseded by ADR 0009 (2026-04-25)
- **Deciders:** Kartik Hirijaganer

## Context

Briefed's cost envelope (plan §19.15, §20.8) targets **~$5/month of LLM
spend at 18k emails/month**. Four providers are on the table:

| Provider             | Classification cost | Strength            | Weakness              |
|----------------------|--------------------:|---------------------|-----------------------|
| Gemini 1.5 Flash (paid) | ~$1/mo            | Cheapest at scale   | Less mature caching   |
| Claude Haiku 4.5     | ~$2–3/mo            | Best JSON reliability | 2–3× Gemini price   |
| Claude Sonnet 4.6    | ~$10/mo             | Highest quality     | Blows the budget      |
| OpenRouter           | variable            | Portability         | No no-training tier   |

The paid Gemini tier includes Google's "no training on your content"
commitment, which we require for email-content privacy.

## Decision

- **Primary**: `GeminiProvider` using Gemini 1.5 Flash (paid, no-training tier)
  for all classification + summarization + job extraction calls.
- **Fallback**: `AnthropicDirectProvider` using Claude Haiku 4.5. Invoked only
  when (a) Gemini returns a schema-validation error twice in a row,
  (b) Gemini is rate-limited, or (c) classification confidence < 0.55 AND
  the email matched a `must_read` candidate rule.
- **Hard cap**: 100 Haiku calls/day project-wide — circuit breaker open once
  reached, surfaces a `needs_review` badge for the rest of the window.
- **No Sonnet or Opus** in the default profile. Quality floors live in the
  prompt eval suite; regressions page us, not auto-escalate to a pricier model.

## Consequences

**Benefits**
- Steady-state LLM cost ~$5/month with a capped fallback bill.
- Two providers under test in CI means neither monoculture failure mode
  (Gemini outage, Anthropic outage) takes the whole pipeline down.
- `LLMProvider` protocol (§19.4) already allows adding `BedrockProvider` or
  `OpenRouterProvider` without code changes; they ship as adapters but are
  not in the default `fallback_chain`.

**Costs**
- Gemini prompt caching is less mature than Anthropic's 1-hour tier.
  Cost math in §19.15 explicitly does not assume cache savings — any hit
  is upside.
- Gemini quality on summarization is good, not Sonnet-grade. Acceptable for
  personal triage; the `needs_review` UI state (§19.8) covers edge cases.

## Alternatives considered

- **Anthropic direct primary + OpenRouter fallback.** Rejected — higher steady
  cost (~$8–10/mo) and OpenRouter does not offer no-training guarantees.
- **Bedrock primary.** Rejected — ~+20% per-token cost for the same Claude
  family + no prompt caching parity. Kept as an adapter for operators who
  want AWS-native billing + CloudTrail.

## Revisit triggers

- Gemini Flash quality regresses below the eval-suite thresholds (plan §6).
- Claude Haiku pricing drops below Flash (unlikely but possible).
- A hosted multi-tenant deployment makes the no-training tier inadequate on
  policy grounds — revisit with CMK-wrapped on-disk storage + Bedrock.
