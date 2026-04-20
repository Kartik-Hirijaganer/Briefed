"""Base types for LLM provider adapters (plan §19.4).

``LLMProvider`` is the narrow seam ``LLMClient`` depends on. Every
adapter (Gemini, Anthropic direct, Bedrock, OpenRouter) implements the
same shape so ``settings.llm.provider`` and ``settings.llm.fallback_chain``
can swap providers as a config change.

The result object :class:`LLMCallResult` contains *parsed* JSON — the
provider adapter owns the JSON parse + Pydantic validation so the rest
of the codebase never touches raw API envelopes.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field


class LLMProviderError(Exception):
    """Raised when an adapter cannot satisfy a call.

    The ``retryable`` flag tells :class:`app.llm.client.LLMClient`
    whether to try this provider again (``True`` for transient transport
    failures, 429s, or 5xx errors) or fall through to the next provider
    in the chain immediately.
    """

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        """Construct the error with a retryability flag.

        Args:
            message: Human-readable description.
            retryable: ``True`` if the client should retry before
                falling through.
        """
        super().__init__(message)
        self.retryable = retryable


class PromptSpec(BaseModel):
    """Versioned prompt + call params bundled into one value object.

    Attributes:
        name: Prompt key (``triage`` / ``summarize_relevant`` / ...).
        version: Integer version.
        content: The raw prompt body from the markdown file.
        model: Model identifier (provider-specific).
        temperature: Sampling temperature.
        max_tokens: Maximum output tokens.
        cache_tier: Provider-specific cache hint (``gemini_context`` /
            ``anthropic_1h`` / ``none``).
        schema_ref: Pydantic schema name that the output must validate
            against. ``LLMClient`` uses this to route the parse.
        extras: Free-form provider-specific knobs.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    version: int
    content: str
    model: str
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    max_tokens: int = Field(default=512, ge=1, le=16_000)
    cache_tier: str = Field(default="none")
    schema_ref: str = Field(default="")
    extras: dict[str, Any] = Field(default_factory=dict)


@dataclass(frozen=True)
class LLMCallResult:
    """Normalized adapter response.

    Attributes:
        payload: Parsed JSON from the model (pre-Pydantic).
        tokens_in: Billed input tokens.
        tokens_out: Billed output tokens.
        tokens_cache_read: Cache-hit token count (0 if unsupported).
        tokens_cache_write: Cache-write token count.
        cost_usd: Provider-reported cost when available; computed
            locally via ``_PRICE_TABLE`` otherwise.
        latency_ms: Wall-clock latency of the call.
        provider: Provider slug (``gemini`` / ``anthropic_direct`` /
            ``bedrock`` / ...).
        model: Concrete model identifier the call actually used.
    """

    payload: dict[str, Any]
    tokens_in: int
    tokens_out: int
    tokens_cache_read: int
    tokens_cache_write: int
    cost_usd: Decimal
    latency_ms: int
    provider: str
    model: str


@runtime_checkable
class LLMProvider(Protocol):
    """Structural protocol every adapter implements.

    Attributes:
        name: Provider slug used in config (``"gemini"`` etc.) and in
            ``prompt_call_log.provider``.
    """

    name: str

    async def complete_json(
        self,
        spec: PromptSpec,
        *,
        rendered_prompt: str,
    ) -> LLMCallResult:
        """Run the model and return a parsed JSON payload.

        Args:
            spec: :class:`PromptSpec` describing the call params.
            rendered_prompt: Fully interpolated prompt text.

        Returns:
            :class:`LLMCallResult` with the parsed payload and cost
            telemetry.

        Raises:
            LLMProviderError: When the provider itself fails — the
                ``retryable`` flag decides retry vs fallback.
        """


__all__ = [
    "LLMCallResult",
    "LLMProvider",
    "LLMProviderError",
    "PromptSpec",
]
