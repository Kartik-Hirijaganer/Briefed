"""Anthropic Message Batches adapter (plan §14 Phase 3, §6 Batch API).

Implements :class:`app.services.summarization.batch.BatchProvider` for
Anthropic's ``/v1/messages/batches`` endpoint. We target the direct
Anthropic API (plan §20.1 canonical fallback); if an operator swaps in
Bedrock, a separate adapter ships alongside.

The adapter never invokes the sync ``/v1/messages`` path — that lives in
:mod:`app.llm.providers.anthropic`. Failures surface as
:class:`app.llm.providers.base.LLMProviderError` with retryability flags
so the driver treats transport blips as transient and hard schema
issues as terminal.
"""

from __future__ import annotations

import json
import re
import time
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from app.core.logging import get_logger
from app.llm.providers.base import LLMProviderError
from app.services.summarization.batch import (
    BatchRequest,
    BatchResult,
    BatchSubmission,
    build_call_result,
)

if TYPE_CHECKING:  # pragma: no cover
    import httpx


logger = get_logger(__name__)

_ENDPOINT = "https://api.anthropic.com/v1/messages/batches"
"""Anthropic Message Batches endpoint."""

_ANTHROPIC_VERSION = "2023-06-01"
"""Pinned API version."""

_BATCH_HEADERS_BETA = {"anthropic-beta": "message-batches-2024-09-24"}
"""Required beta header for batches endpoint."""

_INPUT_USD_PER_M = Decimal("0.40")
"""Input-token price per million tokens with Batch 50% discount."""

_OUTPUT_USD_PER_M = Decimal("2.00")
"""Output-token price per million tokens with Batch 50% discount."""

_FENCE_RE = re.compile(r"^```(?:json)?\n?|\n?```$", re.MULTILINE)
"""Strip markdown code fences the model sometimes wraps JSON in."""

_TERMINAL_STATES = {"ended", "canceled", "completed", "failed"}
"""Provider status strings that map to our terminal states."""


class AnthropicBatchProvider:
    """Anthropic Message Batches adapter."""

    name = "anthropic_direct_batch"

    def __init__(
        self,
        *,
        api_key: str,
        http_client: httpx.AsyncClient,
        endpoint: str = _ENDPOINT,
    ) -> None:
        """Wire up credentials + HTTP client.

        Args:
            api_key: Anthropic API key.
            http_client: Shared :class:`httpx.AsyncClient`.
            endpoint: Override for testing.

        Raises:
            LLMProviderError: When ``api_key`` is empty.
        """
        if not api_key:
            raise LLMProviderError(
                "anthropic_direct_batch requires a non-empty api_key",
                retryable=False,
            )
        self._api_key = api_key
        self._http = http_client
        self._endpoint = endpoint

    async def submit(self, requests: tuple[BatchRequest, ...]) -> BatchSubmission:
        """Create a batch on the Anthropic side + return its id."""
        payload = {
            "requests": [
                {
                    "custom_id": req.request_id,
                    "params": {
                        "model": req.spec.model,
                        "max_tokens": req.spec.max_tokens,
                        "temperature": req.spec.temperature,
                        "messages": [
                            {"role": "user", "content": req.rendered_prompt},
                        ],
                    },
                }
                for req in requests
            ],
        }
        data = await self._post(self._endpoint, payload)
        batch_id = str(data.get("id", ""))
        status = _normalize_status(str(data.get("processing_status", "in_progress")))
        if not batch_id:
            raise LLMProviderError(
                "anthropic batch response missing id",
                retryable=False,
            )
        return BatchSubmission(
            batch_id=batch_id,
            status=status,
            submitted_at=time.monotonic(),
            request_count=len(requests),
        )

    async def poll(self, batch_id: str) -> BatchSubmission:
        """Return the current status for ``batch_id``."""
        data = await self._get(f"{self._endpoint}/{batch_id}")
        status = _normalize_status(str(data.get("processing_status", "in_progress")))
        return BatchSubmission(
            batch_id=batch_id,
            status=status,
            submitted_at=time.monotonic(),
            request_count=int(data.get("request_counts", {}).get("total", 0)),
        )

    async def fetch_results(self, batch_id: str) -> tuple[BatchResult, ...]:
        """Download the per-request results once the batch is terminal."""
        data = await self._get(f"{self._endpoint}/{batch_id}/results")
        raw = data.get("results") if isinstance(data, dict) else data
        if not isinstance(raw, list):
            raise LLMProviderError(
                "anthropic batch results payload was not a list",
                retryable=False,
            )
        parsed: list[BatchResult] = []
        for entry in raw:
            parsed.append(_parse_entry(entry))
        return tuple(parsed)

    async def cancel(self, batch_id: str) -> None:
        """Cancel an in-flight batch (best-effort)."""
        await self._post(f"{self._endpoint}/{batch_id}/cancel", {})

    async def _post(self, url: str, body: dict[str, Any]) -> dict[str, Any]:
        """POST helper that maps transport + API errors to provider errors."""
        try:
            response = await self._http.post(
                url,
                json=body,
                headers=self._headers(),
                timeout=60.0,
            )
        except Exception as exc:
            raise LLMProviderError(
                f"anthropic_direct_batch transport error: {exc}",
                retryable=True,
            ) from exc
        return _parse_response(response)

    async def _get(self, url: str) -> dict[str, Any]:
        """GET helper that maps transport + API errors to provider errors."""
        try:
            response = await self._http.get(url, headers=self._headers(), timeout=60.0)
        except Exception as exc:
            raise LLMProviderError(
                f"anthropic_direct_batch transport error: {exc}",
                retryable=True,
            ) from exc
        return _parse_response(response)

    def _headers(self) -> dict[str, str]:
        """Build the request headers + beta opt-in."""
        return {
            "x-api-key": self._api_key,
            "anthropic-version": _ANTHROPIC_VERSION,
            "content-type": "application/json",
            **_BATCH_HEADERS_BETA,
        }


def _parse_response(response: Any) -> dict[str, Any]:
    """Validate the HTTP response + decode JSON."""
    status_code = int(getattr(response, "status_code", 500))
    if status_code == 429 or status_code >= 500:
        raise LLMProviderError(
            f"anthropic_direct_batch {status_code}",
            retryable=True,
        )
    if status_code >= 400:
        raise LLMProviderError(
            f"anthropic_direct_batch {status_code}",
            retryable=False,
        )
    data: Any = response.json()
    if isinstance(data, dict):
        return data
    if isinstance(data, list):
        return {"results": data}
    raise LLMProviderError(
        "anthropic_direct_batch returned a non-object body",
        retryable=False,
    )


def _normalize_status(raw: str) -> str:
    """Map provider-reported processing_status to driver-terminal strings."""
    lowered = raw.strip().lower()
    if lowered in {"ended", "completed"}:
        return "completed"
    if lowered in {"canceled", "cancelling"}:
        return "canceled"
    if lowered in {"errored", "failed"}:
        return "failed"
    return "running"


def _parse_entry(entry: Any) -> BatchResult:
    """Parse one per-request result from the Anthropic batch output."""
    if not isinstance(entry, dict):
        return BatchResult(
            request_id="",
            ok=False,
            call_result=None,
            error="non-object batch entry",
        )
    request_id = str(entry.get("custom_id", ""))
    result = entry.get("result")
    if not isinstance(result, dict):
        return BatchResult(
            request_id=request_id,
            ok=False,
            call_result=None,
            error="missing result object",
        )
    result_type = str(result.get("type", ""))
    if result_type == "succeeded":
        message = result.get("message")
        if not isinstance(message, dict):
            return BatchResult(
                request_id=request_id,
                ok=False,
                call_result=None,
                error="missing message body",
            )
        content = message.get("content") or []
        text_parts = [part.get("text", "") for part in content if part.get("type") == "text"]
        if not text_parts:
            return BatchResult(
                request_id=request_id,
                ok=False,
                call_result=None,
                error="missing text parts",
            )
        raw_text = _FENCE_RE.sub("", "\n".join(text_parts)).strip()
        try:
            payload = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            return BatchResult(
                request_id=request_id,
                ok=False,
                call_result=None,
                error=f"non-JSON body: {exc}",
            )
        if not isinstance(payload, dict):
            return BatchResult(
                request_id=request_id,
                ok=False,
                call_result=None,
                error="payload must be an object",
            )
        usage = message.get("usage") or {}
        tokens_in = int(usage.get("input_tokens", 0))
        tokens_out = int(usage.get("output_tokens", 0))
        cache_read = int(usage.get("cache_read_input_tokens", 0))
        cache_write = int(usage.get("cache_creation_input_tokens", 0))
        model = str(message.get("model", ""))
        cost = Decimal(tokens_in) * _INPUT_USD_PER_M / Decimal(1_000_000) + Decimal(
            tokens_out
        ) * _OUTPUT_USD_PER_M / Decimal(1_000_000)
        from app.llm.providers.base import PromptSpec  # noqa: PLC0415

        spec = PromptSpec(
            name="<batch>",
            version=0,
            content="",
            model=model or "claude-haiku-4-5",
        )
        return BatchResult(
            request_id=request_id,
            ok=True,
            call_result=build_call_result(
                payload=payload,
                spec=spec,
                provider="anthropic_direct_batch",
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                tokens_cache_read=cache_read,
                tokens_cache_write=cache_write,
                cost_usd=cost.quantize(Decimal("0.000001")),
                latency_ms=0,
            ),
        )
    return BatchResult(
        request_id=request_id,
        ok=False,
        call_result=None,
        error=f"batch result type: {result_type}",
    )


__all__ = ["AnthropicBatchProvider"]
