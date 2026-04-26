"""Provider adapters for the ``LLMProvider`` protocol (ADR 0009).

OpenRouter is the sole direct LLM provider. The legacy Gemini /
Anthropic adapters were deleted at T+30 days post-cutover per the
plan; their git history is the rollback path if a future regression
needs them.
"""

from app.llm.providers.base import (
    LLMCallResult,
    LLMProvider,
    LLMProviderError,
    PromptSpec,
)
from app.llm.providers.openrouter import OpenRouterProvider

__all__ = [
    "LLMCallResult",
    "LLMProvider",
    "LLMProviderError",
    "OpenRouterProvider",
    "PromptSpec",
]
