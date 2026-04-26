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


# --------------------------------------------------------------------------- #
# Reidentify success path — gated behind a temporarily-extended allowlist.    #
# These tests preserve LLMClient at 100% coverage (Track A Phase 7 + plan     #
# §20.1) by exercising the branch the empty production allowlist hides.       #
# --------------------------------------------------------------------------- #


class _NestedSanitizer:
    """Stub sanitizer that produces a non-trivial reversal map."""

    def sanitize(self, text: str) -> RedactionResult:
        return RedactionResult(
            text=text.replace("user@example.com", "<USER_EMAIL_0>"),
            reversal_map={"<USER_EMAIL_0>": "user@example.com"},
            counts_by_kind={"USER_EMAIL": 1},
        )


async def test_reidentify_success_walks_dict_list_tuple_and_scalars(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Happy reidentify path covers every branch of ``_reidentify_node``.

    Provider returns a payload with: a string holding a placeholder, a
    string without one, a list (with placeholder), a tuple (with
    placeholder), and a non-string scalar (int / None / bool). All of
    these are walked by ``_reidentify_node``; the assertions below
    verify each branch.
    """
    from app.llm import client as _client_module

    monkeypatch.setattr(
        _client_module,
        "REIDENTIFY_FLOW_ALLOWLIST",
        frozenset({"unit-test-flow"}),
    )

    nested_payload: dict[str, Any] = {
        "note": "ping <USER_EMAIL_0> please",
        "no_placeholder": "nothing to swap",
        "tags": ["plain", "<USER_EMAIL_0>"],
        "tuple_field": ("a", "<USER_EMAIL_0>"),
        "count": 7,
        "nullable": None,
        "flag": True,
    }

    class _PayloadSchema(BaseModel):
        model_config = ConfigDict(extra="allow", frozen=True)

        note: str

    provider = _CapturingProvider(nested_payload)
    client = LLMClient(primary=provider)

    response = await client.call(
        spec=_spec(),
        rendered_prompt="ping user@example.com",
        schema=_PayloadSchema,
        prompt_version_id=uuid.uuid4(),
        sanitizer=_NestedSanitizer(),
        reidentify=True,
        flow="unit-test-flow",
    )

    # Provider received the redacted prompt.
    assert provider.seen_prompt == "ping <USER_EMAIL_0>"

    # Reidentified values land on the parsed model, not on
    # call_result.payload (which preserves the placeholder form).
    parsed = response.parsed.model_dump()
    assert parsed["note"] == "ping user@example.com please"
    assert parsed["no_placeholder"] == "nothing to swap"
    assert parsed["tags"] == ["plain", "user@example.com"]
    assert parsed["tuple_field"] == ("a", "user@example.com")
    # Non-string scalars walk through untouched.
    assert parsed["count"] == 7
    assert parsed["nullable"] is None
    assert parsed["flag"] is True


async def test_reidentify_with_empty_reversal_map_short_circuits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A sanitizer that produces no replacements still allows reidentify.

    Exercises the early-return branch in ``_reidentify_payload`` when the
    reversal map is empty — the payload is returned unchanged without
    walking the tree.
    """
    from app.llm import client as _client_module

    monkeypatch.setattr(
        _client_module,
        "REIDENTIFY_FLOW_ALLOWLIST",
        frozenset({"unit-test-flow"}),
    )

    class _NoMatchSanitizer:
        def sanitize(self, text: str) -> RedactionResult:
            return RedactionResult(text=text)

    provider = _CapturingProvider({"note": "no replacement happened"})
    client = LLMClient(primary=provider)

    response = await client.call(
        spec=_spec(),
        rendered_prompt="nothing sensitive here",
        schema=_Payload,
        prompt_version_id=uuid.uuid4(),
        sanitizer=_NoMatchSanitizer(),
        reidentify=True,
        flow="unit-test-flow",
    )
    assert response.call_result.payload == {"note": "no replacement happened"}
