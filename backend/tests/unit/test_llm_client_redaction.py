"""Tests for the Track B redaction integration on :class:`LLMClient`."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict

from app.llm.client import (
    REIDENTIFY_FLOW_ALLOWLIST,
    LLMClient,
    LLMClientError,
    PromptCallRecord,
)
from app.llm.providers.base import LLMCallResult, PromptSpec
from app.llm.redaction.types import RedactionResult, Sanitizer


class _Payload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    note: str


def _spec() -> PromptSpec:
    return PromptSpec(
        name="triage",
        version=1,
        content="hi {{who}}",
        model="fake-model",
        temperature=0.0,
        max_tokens=100,
        schema_ref="TriageDecision",
    )


def _result(payload: dict[str, Any]) -> LLMCallResult:
    return LLMCallResult(
        payload=payload,
        tokens_in=10,
        tokens_out=5,
        tokens_cache_read=0,
        tokens_cache_write=0,
        cost_usd=Decimal("0.000100"),
        latency_ms=42,
        provider="fake",
        model="fake-model",
    )


class _CapturingProvider:
    name = "fake"

    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload
        self.seen_prompt: str | None = None

    async def complete_json(
        self,
        spec: PromptSpec,
        *,
        rendered_prompt: str,
    ) -> LLMCallResult:
        self.seen_prompt = rendered_prompt
        return _result(self._payload)


class _RecordingSanitizer:
    """Replaces ``user@example.com`` with ``<USER_EMAIL_0>``."""

    def sanitize(self, text: str) -> RedactionResult:
        if "user@example.com" not in text:
            return RedactionResult(text=text)
        return RedactionResult(
            text=text.replace("user@example.com", "<USER_EMAIL_0>"),
            reversal_map={"<USER_EMAIL_0>": "user@example.com"},
            counts_by_kind={"USER_EMAIL": 1},
        )


async def test_call_level_sanitizer_redacts_prompt() -> None:
    provider = _CapturingProvider({"note": "ok"})
    client = LLMClient(primary=provider)
    sanitizer: Sanitizer = _RecordingSanitizer()
    response = await client.call(
        spec=_spec(),
        rendered_prompt="ping user@example.com",
        schema=_Payload,
        prompt_version_id=uuid.uuid4(),
        sanitizer=sanitizer,
    )
    assert provider.seen_prompt == "ping <USER_EMAIL_0>"
    assert response.redaction is not None
    assert response.record.redaction_counts == {"USER_EMAIL": 1}


async def test_constructor_default_sanitizer_applied() -> None:
    provider = _CapturingProvider({"note": "ok"})
    client = LLMClient(primary=provider, sanitizer=_RecordingSanitizer())
    response = await client.call(
        spec=_spec(),
        rendered_prompt="ping user@example.com",
        schema=_Payload,
        prompt_version_id=uuid.uuid4(),
    )
    assert provider.seen_prompt == "ping <USER_EMAIL_0>"
    assert response.record.redaction_counts == {"USER_EMAIL": 1}


async def test_call_level_sanitizer_overrides_constructor_default() -> None:
    provider = _CapturingProvider({"note": "ok"})

    class _NoopSanitizer:
        def sanitize(self, text: str) -> RedactionResult:
            return RedactionResult(text=text)

    client = LLMClient(primary=provider, sanitizer=_RecordingSanitizer())
    response = await client.call(
        spec=_spec(),
        rendered_prompt="ping user@example.com",
        schema=_Payload,
        prompt_version_id=uuid.uuid4(),
        sanitizer=_NoopSanitizer(),
    )
    assert provider.seen_prompt == "ping user@example.com"
    assert response.record.redaction_counts == {}


async def test_record_log_includes_counts() -> None:
    provider = _CapturingProvider({"note": "ok"})
    client = LLMClient(primary=provider)
    logs: list[PromptCallRecord] = []

    async def log(record: PromptCallRecord) -> None:
        logs.append(record)

    await client.call(
        spec=_spec(),
        rendered_prompt="ping user@example.com",
        schema=_Payload,
        prompt_version_id=uuid.uuid4(),
        log_call=log,
        sanitizer=_RecordingSanitizer(),
    )
    assert logs[0].redaction_counts == {"USER_EMAIL": 1}


async def test_no_sanitizer_yields_none_counts() -> None:
    provider = _CapturingProvider({"note": "ok"})
    client = LLMClient(primary=provider)
    response = await client.call(
        spec=_spec(),
        rendered_prompt="ping user@example.com",
        schema=_Payload,
        prompt_version_id=uuid.uuid4(),
    )
    assert response.record.redaction_counts is None
    assert response.redaction is None


async def test_reidentify_requires_allowlisted_flow() -> None:
    provider = _CapturingProvider({"note": "ok"})
    client = LLMClient(primary=provider)
    with pytest.raises(LLMClientError):
        await client.call(
            spec=_spec(),
            rendered_prompt="ping user@example.com",
            schema=_Payload,
            prompt_version_id=uuid.uuid4(),
            sanitizer=_RecordingSanitizer(),
            reidentify=True,
            flow="not-on-list",
        )


async def test_reidentify_requires_sanitizer() -> None:
    provider = _CapturingProvider({"note": "ok"})
    client = LLMClient(primary=provider)
    with pytest.raises(LLMClientError):
        await client.call(
            spec=_spec(),
            rendered_prompt="ping user@example.com",
            schema=_Payload,
            prompt_version_id=uuid.uuid4(),
            reidentify=True,
        )


def test_reidentify_allowlist_empty_in_v1() -> None:
    # ADR 0010 §Decision: empty allowlist in 1.0.0; adding a flow
    # requires an ADR amendment. This test exists to fail loudly if
    # someone adds a flow without amending the ADR.
    assert frozenset() == REIDENTIFY_FLOW_ALLOWLIST


def test_prompt_call_record_does_not_carry_reversal_map() -> None:
    # Risk-register entry: audit log accidentally captures reversal_map.
    # The PromptCallRecord shape is the only thing that reaches
    # _persist_call_log → PromptCallLog → DB. Asserting the field set
    # makes the boundary explicit.
    fields = set(PromptCallRecord.__dataclass_fields__)
    assert "reversal_map" not in fields
    assert "redaction_counts" in fields
