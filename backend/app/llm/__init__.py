"""LLM client + provider adapters + Pydantic tool-use schemas.

Modules:

* :mod:`app.llm.schemas` — Pydantic value objects for structured outputs.
* :mod:`app.llm.catalog` — friendly-name → OpenRouter route catalog
  (ADR 0009).
* :mod:`app.llm.providers` — protocol + ``OpenRouterProvider``.
* :mod:`app.llm.client` — ``LLMClient`` facade: retries + circuit
  breaker + fallback chain + ``prompt_call_log`` metering + daily-USD
  cost guard.
* :mod:`app.llm.factory` — single seam that wires the provider chain
  for a given :class:`Settings`.

Everything here is deliberately independent of FastAPI + SQLAlchemy so
it can be reused from workers, eval harnesses, and unit tests.
"""
