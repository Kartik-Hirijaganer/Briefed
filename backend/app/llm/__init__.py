"""LLM client + provider adapters + Pydantic tool-use schemas.

Phase 2 ships:

* :mod:`app.llm.schemas` — Pydantic value objects for structured outputs
  (``TriageDecision`` today; more as later phases ship).
* :mod:`app.llm.providers` — protocol + ``GeminiProvider`` +
  ``AnthropicDirectProvider`` (gated fallback per plan §19.15).
* :mod:`app.llm.client` — ``LLMClient`` facade: retries + circuit
  breaker + fallback chain + ``prompt_call_log`` metering.

Everything here is deliberately independent of FastAPI + SQLAlchemy so
it can be reused from workers, eval harnesses, and unit tests.
"""
