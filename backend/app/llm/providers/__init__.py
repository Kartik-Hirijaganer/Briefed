"""Provider adapters for the ``LLMProvider`` protocol (plan §19.4).

Phase 2 ships:

* :class:`app.llm.providers.base.LLMProvider` — the structural protocol.
* :class:`app.llm.providers.gemini.GeminiProvider` — primary per §20.1.
* :class:`app.llm.providers.anthropic.AnthropicDirectProvider` — gated
  fallback (Claude Haiku 4.5, hard cap 100 calls/day).

Both concrete providers use async HTTP and avoid importing the SDKs at
module import time so Lambda SnapStart does not snapshot heavy
dependencies needed only on the hot path.
"""

from app.llm.providers.anthropic import AnthropicDirectProvider
from app.llm.providers.base import (
    LLMCallResult,
    LLMProvider,
    LLMProviderError,
    PromptSpec,
)
from app.llm.providers.gemini import GeminiProvider

__all__ = [
    "AnthropicDirectProvider",
    "GeminiProvider",
    "LLMCallResult",
    "LLMProvider",
    "LLMProviderError",
    "PromptSpec",
]
