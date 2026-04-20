"""Gemini Flash provider adapter (plan §19.15 / §20.1 canonical primary).

Keeps a single ``httpx.AsyncClient`` alive for the Lambda warm window
— the SDK's sync client is not friendly to asyncio, and the REST surface
is small enough to call directly.

The adapter parses the model response into a dict (the downstream Pydantic
schema is applied by :class:`app.llm.client.LLMClient`). Provider-specific
errors map to :class:`app.llm.providers.base.LLMProviderError` with
``retryable=True`` for 429 / 5xx and ``retryable=False`` for schema /
validation failures so the circuit breaker + fallback logic behaves
correctly.
"""

from __future__ import annotations

import json
import time
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from app.core.logging import get_logger
from app.llm.providers.base import LLMCallResult, LLMProviderError, PromptSpec

if TYPE_CHECKING:  # pragma: no cover
    import httpx


logger = get_logger(__name__)

_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models"
"""Gemini REST base URL; model is appended as ``{model}:generateContent``."""

_INPUT_USD_PER_M = Decimal("0.075")
"""Input-token price per million tokens (Gemini 1.5 Flash paid tier)."""

_OUTPUT_USD_PER_M = Decimal("0.300")
"""Output-token price per million tokens (Gemini 1.5 Flash paid tier)."""


class GeminiProvider:
    """REST adapter for Gemini ``generateContent``.

    Attributes:
        name: Provider slug used by the client + logs.
    """

    name = "gemini"

    def __init__(
        self,
        *,
        api_key: str,
        http_client: httpx.AsyncClient,
        endpoint: str = _ENDPOINT,
    ) -> None:
        """Wire up credentials + HTTP client.

        Args:
            api_key: Gemini API key from SSM / ``.env``.
            http_client: Shared :class:`httpx.AsyncClient`. The caller
                owns the lifecycle; we never close it.
            endpoint: Override for testing.

        Raises:
            LLMProviderError: When ``api_key`` is empty.
        """
        if not api_key:
            raise LLMProviderError("gemini requires a non-empty api_key", retryable=False)
        self._api_key = api_key
        self._http = http_client
        self._endpoint = endpoint.rstrip("/")

    async def complete_json(
        self,
        spec: PromptSpec,
        *,
        rendered_prompt: str,
    ) -> LLMCallResult:
        """Call Gemini and return a parsed JSON payload.

        Args:
            spec: Versioned :class:`PromptSpec`.
            rendered_prompt: Fully interpolated prompt text.

        Returns:
            :class:`LLMCallResult`.

        Raises:
            LLMProviderError: ``retryable=True`` for 429/5xx; ``False``
                for 4xx / JSON / schema mismatch.
        """
        url = f"{self._endpoint}/{spec.model}:generateContent?key={self._api_key}"
        body = {
            "contents": [{"role": "user", "parts": [{"text": rendered_prompt}]}],
            "generationConfig": {
                "temperature": spec.temperature,
                "maxOutputTokens": spec.max_tokens,
                "responseMimeType": "application/json",
            },
        }
        start = time.monotonic()
        try:
            response = await self._http.post(url, json=body, timeout=30.0)
        except Exception as exc:
            raise LLMProviderError(f"gemini transport error: {exc}", retryable=True) from exc

        latency_ms = int((time.monotonic() - start) * 1000)

        if response.status_code == 429 or response.status_code >= 500:
            raise LLMProviderError(
                f"gemini {response.status_code}: {response.text[:180]}",
                retryable=True,
            )
        if response.status_code >= 400:
            raise LLMProviderError(
                f"gemini {response.status_code}: {response.text[:180]}",
                retryable=False,
            )

        data: dict[str, Any] = response.json()
        candidates = data.get("candidates") or []
        if not candidates:
            raise LLMProviderError("gemini returned zero candidates", retryable=False)

        parts = candidates[0].get("content", {}).get("parts") or []
        if not parts:
            raise LLMProviderError("gemini candidate missing parts", retryable=False)
        raw_text: str = parts[0].get("text", "")
        try:
            payload = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise LLMProviderError(
                f"gemini returned non-JSON body: {exc}",
                retryable=False,
            ) from exc
        if not isinstance(payload, dict):
            raise LLMProviderError("gemini payload must be an object", retryable=False)

        usage = data.get("usageMetadata") or {}
        tokens_in = int(usage.get("promptTokenCount", 0))
        tokens_out = int(usage.get("candidatesTokenCount", 0))
        cache_read = int(usage.get("cachedContentTokenCount", 0))
        cost = Decimal(tokens_in) * _INPUT_USD_PER_M / Decimal(1_000_000) + Decimal(
            tokens_out
        ) * _OUTPUT_USD_PER_M / Decimal(1_000_000)

        return LLMCallResult(
            payload=payload,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            tokens_cache_read=cache_read,
            tokens_cache_write=0,
            cost_usd=cost.quantize(Decimal("0.000001")),
            latency_ms=latency_ms,
            provider=self.name,
            model=spec.model,
        )


__all__ = ["GeminiProvider"]
