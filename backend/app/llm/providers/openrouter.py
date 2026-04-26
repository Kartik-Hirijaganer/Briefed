"""OpenRouter provider — routes Gemini Flash + Claude Haiku via one API.

ADR 0009 made OpenRouter the sole direct LLM provider. This adapter
implements the existing :class:`app.llm.providers.base.LLMProvider`
protocol so :class:`app.llm.client.LLMClient` does not change.

Notable request shape (Track A Phase 3):

* ``provider: {data_collection: "deny"}`` — only routes that honour
  no-logging are eligible. ADR 0009 documents the trust-boundary
  trade-off this still leaves on the table.
* ``transforms: []`` — disables OpenRouter's default prompt rewriting
  (e.g. middle-out compression) so Briefed prompts hit the model
  unmodified.
* ``X-Title: Briefed`` header. Deliberately *no* ``HTTP-Referer`` —
  privacy preference per the plan.
* JSON mode (``response_format = {"type": "json_object"}``) is enabled
  on every call where ``spec.schema_ref`` is set — i.e. every call
  Briefed actually makes today.

The adapter parses the per-call ``usage.cost`` field that OpenRouter
returns and surfaces it on :class:`LLMCallResult`. When the field is
missing (rare but possible on certain routes), we fall back to a local
estimate computed from the catalog price table.
"""

from __future__ import annotations

import json
import re
import time
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from app.core.logging import get_logger
from app.llm.catalog import ModelEntry
from app.llm.providers.base import LLMCallResult, LLMProviderError, PromptSpec

if TYPE_CHECKING:  # pragma: no cover
    import httpx


logger = get_logger(__name__)

_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
"""OpenRouter chat-completions endpoint."""

_FENCE_RE = re.compile(r"^```(?:json)?\n?|\n?```$", re.MULTILINE)
"""Strip markdown code fences when a route wraps JSON in them."""


class OpenRouterProvider:
    """OpenRouter chat-completions adapter.

    Attributes:
        name: Provider slug used by :class:`LLMClient` and the
            ``prompt_call_log.provider`` column.
    """

    name = "openrouter"

    def __init__(
        self,
        *,
        api_key: str,
        http_client: httpx.AsyncClient,
        catalog_entry: ModelEntry,
        endpoint: str = _ENDPOINT,
    ) -> None:
        """Wire up credentials, HTTP client, and the active catalog row.

        One :class:`OpenRouterProvider` is built per model in the
        chain; the catalog entry encodes the route id and pricing for
        the local-estimate fallback.

        Args:
            api_key: OpenRouter API key from SSM / ``.env``.
            http_client: Shared :class:`httpx.AsyncClient`. The caller
                owns the lifecycle.
            catalog_entry: :class:`app.llm.catalog.ModelEntry` for the
                model this provider serves.
            endpoint: Override for testing.

        Raises:
            LLMProviderError: When ``api_key`` is empty.
        """
        if not api_key:
            raise LLMProviderError(
                "openrouter requires a non-empty api_key",
                retryable=False,
            )
        self._api_key = api_key
        self._http = http_client
        self._endpoint = endpoint
        self._entry = catalog_entry

    async def complete_json(
        self,
        spec: PromptSpec,
        *,
        rendered_prompt: str,
    ) -> LLMCallResult:
        """Call OpenRouter and return a parsed JSON payload.

        Args:
            spec: Versioned :class:`PromptSpec`. ``spec.model`` is
                ignored in favour of the bound catalog entry — the
                friendly name lives in ``spec.model`` and the entry is
                resolved upstream by the factory.
            rendered_prompt: Fully interpolated prompt text.

        Returns:
            :class:`LLMCallResult` with ``cost_usd`` taken from the
            provider's ``usage.cost`` field when present, otherwise
            estimated from the catalog price table.

        Raises:
            LLMProviderError: ``retryable=True`` for 429 / 5xx /
                transport failures; ``False`` for 4xx, JSON, or schema
                mismatches.
        """
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "X-Title": "Briefed",
            "Content-Type": "application/json",
        }
        body: dict[str, Any] = {
            "model": self._entry["openrouter_id"],
            "max_tokens": min(spec.max_tokens, self._entry["max_output_tokens"]),
            "temperature": spec.temperature,
            "messages": [{"role": "user", "content": rendered_prompt}],
            "provider": {"data_collection": "deny"},
            "transforms": [],
        }
        if spec.schema_ref:
            body["response_format"] = {"type": "json_object"}

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
                f"openrouter transport error: {exc}",
                retryable=True,
            ) from exc

        latency_ms = int((time.monotonic() - start) * 1000)

        if response.status_code == 429 or response.status_code >= 500:
            raise LLMProviderError(
                f"openrouter {response.status_code}: {response.text[:180]}",
                retryable=True,
            )
        if response.status_code >= 400:
            raise LLMProviderError(
                f"openrouter {response.status_code}: {response.text[:180]}",
                retryable=False,
            )

        data: dict[str, Any] = response.json()
        choices = data.get("choices") or []
        if not choices:
            raise LLMProviderError(
                "openrouter returned zero choices",
                retryable=False,
            )

        message = choices[0].get("message") or {}
        raw_text = message.get("content")
        if not isinstance(raw_text, str) or not raw_text:
            raise LLMProviderError(
                "openrouter choice missing message content",
                retryable=False,
            )
        cleaned = _FENCE_RE.sub("", raw_text).strip()
        try:
            payload = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise LLMProviderError(
                f"openrouter returned non-JSON body: {exc}",
                retryable=False,
            ) from exc
        if not isinstance(payload, dict):
            raise LLMProviderError(
                "openrouter payload must be an object",
                retryable=False,
            )

        usage = data.get("usage") or {}
        tokens_in = int(usage.get("prompt_tokens", 0))
        tokens_out = int(usage.get("completion_tokens", 0))
        cache_read = int(usage.get("cache_read_input_tokens", 0) or 0)
        cache_write = int(usage.get("cache_creation_input_tokens", 0) or 0)
        cost_usd = self._extract_cost(usage, tokens_in=tokens_in, tokens_out=tokens_out)

        return LLMCallResult(
            payload=payload,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            tokens_cache_read=cache_read,
            tokens_cache_write=cache_write,
            cost_usd=cost_usd.quantize(Decimal("0.000001")),
            latency_ms=latency_ms,
            provider=self.name,
            model=self._entry["openrouter_id"],
        )

    def _extract_cost(
        self,
        usage: dict[str, Any],
        *,
        tokens_in: int,
        tokens_out: int,
    ) -> Decimal:
        """Return ``usage.cost`` if present, else estimate from the catalog.

        Args:
            usage: ``usage`` block from the OpenRouter response.
            tokens_in: Billed input tokens (used for the fallback
                estimate).
            tokens_out: Billed output tokens.

        Returns:
            Cost as :class:`Decimal`. Defensive parsing — non-numeric
            ``usage.cost`` values fall back to the catalog estimate.
        """
        raw = usage.get("cost")
        if raw is not None:
            try:
                return Decimal(str(raw))
            except (TypeError, ArithmeticError, ValueError):
                logger.warning(
                    "openrouter.usage_cost.malformed",
                    raw=str(raw),
                )
        # Local estimate as a fallback.
        input_rate = Decimal(str(self._entry["cost_per_m_input_usd"]))
        output_rate = Decimal(str(self._entry["cost_per_m_output_usd"]))
        return Decimal(tokens_in) * input_rate / Decimal(1_000_000) + Decimal(
            tokens_out
        ) * output_rate / Decimal(1_000_000)


__all__ = ["OpenRouterProvider"]
