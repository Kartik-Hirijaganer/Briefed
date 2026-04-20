"""Anthropic direct provider — Claude Haiku 4.5 gated fallback (plan §19.15).

Used only when (a) Gemini returns schema-validation errors twice in a
row, (b) Gemini is rate-limited, or (c) triage confidence < 0.55 on a
``must_read`` candidate. :class:`app.llm.client.LLMClient` enforces the
hard 100-calls/day cap; this adapter just performs the call.

We hit the raw Messages API rather than the SDK so the adapter stays
async and so the deploy artifact does not require the ``anthropic``
Python package at runtime for providers who never enable this fallback.
"""

from __future__ import annotations

import json
import re
import time
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from app.core.logging import get_logger
from app.llm.providers.base import LLMCallResult, LLMProviderError, PromptSpec

if TYPE_CHECKING:  # pragma: no cover
    import httpx


logger = get_logger(__name__)

_ENDPOINT = "https://api.anthropic.com/v1/messages"
"""Anthropic Messages endpoint."""

_ANTHROPIC_VERSION = "2023-06-01"
"""Pinned API version header value."""

_INPUT_USD_PER_M = Decimal("0.80")
"""Input-token price per million tokens (Claude Haiku 4.5)."""

_OUTPUT_USD_PER_M = Decimal("4.00")
"""Output-token price per million tokens (Claude Haiku 4.5)."""

_FENCE_RE = re.compile(r"^```(?:json)?\n?|\n?```$", re.MULTILINE)
"""Strip markdown code fences Claude sometimes wraps JSON in."""


class AnthropicDirectProvider:
    """Direct Anthropic Messages adapter.

    Attributes:
        name: Provider slug used by the client + logs.
    """

    name = "anthropic_direct"

    def __init__(
        self,
        *,
        api_key: str,
        http_client: httpx.AsyncClient,
        endpoint: str = _ENDPOINT,
    ) -> None:
        """Wire up credentials + HTTP client.

        Args:
            api_key: Anthropic API key from SSM / ``.env``.
            http_client: Shared :class:`httpx.AsyncClient`.
            endpoint: Override for testing.

        Raises:
            LLMProviderError: When ``api_key`` is empty.
        """
        if not api_key:
            raise LLMProviderError(
                "anthropic_direct requires a non-empty api_key",
                retryable=False,
            )
        self._api_key = api_key
        self._http = http_client
        self._endpoint = endpoint

    async def complete_json(
        self,
        spec: PromptSpec,
        *,
        rendered_prompt: str,
    ) -> LLMCallResult:
        """Call Claude and return a parsed JSON payload.

        Args:
            spec: Versioned :class:`PromptSpec`.
            rendered_prompt: Fully interpolated prompt text.

        Returns:
            :class:`LLMCallResult`.

        Raises:
            LLMProviderError: Same retryability rules as the Gemini
                adapter.
        """
        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": _ANTHROPIC_VERSION,
            "content-type": "application/json",
        }
        body = {
            "model": spec.model,
            "max_tokens": spec.max_tokens,
            "temperature": spec.temperature,
            "messages": [{"role": "user", "content": rendered_prompt}],
        }
        start = time.monotonic()
        try:
            response = await self._http.post(
                self._endpoint,
                json=body,
                headers=headers,
                timeout=30.0,
            )
        except Exception as exc:
            raise LLMProviderError(
                f"anthropic_direct transport error: {exc}",
                retryable=True,
            ) from exc

        latency_ms = int((time.monotonic() - start) * 1000)

        if response.status_code == 429 or response.status_code >= 500:
            raise LLMProviderError(
                f"anthropic_direct {response.status_code}: {response.text[:180]}",
                retryable=True,
            )
        if response.status_code >= 400:
            raise LLMProviderError(
                f"anthropic_direct {response.status_code}: {response.text[:180]}",
                retryable=False,
            )

        data: dict[str, Any] = response.json()
        content = data.get("content") or []
        text_parts = [part.get("text", "") for part in content if part.get("type") == "text"]
        if not text_parts:
            raise LLMProviderError(
                "anthropic_direct candidate missing text parts",
                retryable=False,
            )
        raw_text = _FENCE_RE.sub("", "\n".join(text_parts)).strip()
        try:
            payload = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise LLMProviderError(
                f"anthropic_direct returned non-JSON body: {exc}",
                retryable=False,
            ) from exc
        if not isinstance(payload, dict):
            raise LLMProviderError(
                "anthropic_direct payload must be an object",
                retryable=False,
            )

        usage = data.get("usage") or {}
        tokens_in = int(usage.get("input_tokens", 0))
        tokens_out = int(usage.get("output_tokens", 0))
        cache_read = int(usage.get("cache_read_input_tokens", 0))
        cache_write = int(usage.get("cache_creation_input_tokens", 0))
        cost = Decimal(tokens_in) * _INPUT_USD_PER_M / Decimal(1_000_000) + Decimal(
            tokens_out
        ) * _OUTPUT_USD_PER_M / Decimal(1_000_000)

        return LLMCallResult(
            payload=payload,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            tokens_cache_read=cache_read,
            tokens_cache_write=cache_write,
            cost_usd=cost.quantize(Decimal("0.000001")),
            latency_ms=latency_ms,
            provider=self.name,
            model=spec.model,
        )


__all__ = ["AnthropicDirectProvider"]
