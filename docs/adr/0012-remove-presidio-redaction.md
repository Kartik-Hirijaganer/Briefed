# ADR 0012 - Remove Presidio from prompt redaction

- **Date:** 2026-05-31
- **Status:** Accepted
- **Deciders:** Kartik Hirijaganer
- **Supersedes:** ADR 0010, only where ADR 0010 requires Presidio

## Context

The daily-triage revamp intentionally cuts non-core runtime surface
before reliability and digest work land. Presidio adds a heavy spaCy
runtime, a Lambda-incompatible NumPy pin, cold-start cost, and an extra
failure mode for every LLM prompt.

Briefed still needs lightweight harm reduction before prompt text leaves
the system, but 1.0.0 is a single-user personal app. The right default is
a small deterministic scrubber stack that is cheap, understandable, and
does not pretend to provide complete PII anonymization.

## Decision

Remove Presidio from the application and dependency set. The prompt
redaction chain is now:

1. `IdentityScrubber` for configured user email, display name, user id,
   aliases, and email aliases.
2. `RegexSanitizer` for deterministic patterns: emails, URLs, phones,
   SSNs, ZIP codes, and IP addresses.

The legacy Presidio config flags remain accepted for compatibility, but
the feature defaults to disabled. Calling `build_default_chain` with
Presidio enabled raises immediately because Presidio is removed, not
hidden behind a dormant code path.

`prompt_call_log.redaction_summary` remains unchanged. It continues to
store counts only, never raw redacted values or reversal maps.

## Consequences

**Benefits**

- Removes `presidio-analyzer`, `presidio-anonymizer`, spaCy transitive
  runtime cost, and the `numpy<2.0` Lambda pin.
- Keeps Lambda SnapStart initialization smaller and more predictable.
- Makes prompt redaction behavior auditable from local code rather than
  a model-backed PII recognizer.

**Costs**

- Fuzzy entities such as unknown third-party names and locations are no
  longer NER-redacted unless they match identity aliases or regex shapes.
- ADR 0010's "full chain" quality-eval language is historical; future
  redaction evaluations compare raw text against identity + regex only.

## Alternatives considered

- **Keep Presidio disabled but importable.** Rejected. That keeps the
  dependency and Lambda packaging cost while still not using the feature.
- **Replace Presidio with another NER library.** Rejected. The revamp goal
  is simplification before run finalization, not swapping one heavyweight
  recognizer for another.
- **Remove all redaction.** Rejected. Identity + regex scrubbers are cheap
  and still reduce obvious sensitive tokens before OpenRouter calls.

## Revisit triggers

- Briefed becomes multi-tenant or processes regulated data.
- A measured prompt corpus shows identity + regex misses unacceptable
  recurring PII classes.
- A lightweight, Lambda-friendly NER option becomes available with clear
  precision/latency evidence.
