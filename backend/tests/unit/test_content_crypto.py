"""Unit tests for :mod:`app.core.content_crypto` (plan §20.10)."""

from __future__ import annotations

from app.core.content_crypto import content_context


def test_context_binds_table_and_row() -> None:
    ctx = content_context(
        table="classifications",
        row_id="abc-123",
        purpose="classifications_reasons",
    )
    assert ctx.as_kms_dict() == {
        "table": "classifications",
        "row_id": "abc-123",
        "purpose": "classifications_reasons",
    }


def test_context_includes_user_when_supplied() -> None:
    ctx = content_context(
        table="summaries",
        row_id="x",
        purpose="summaries_body",
        user_id="u-1",
    )
    assert ctx.as_kms_dict()["user_id"] == "u-1"


def test_context_mutation_is_isolated() -> None:
    ctx = content_context(
        table="t",
        row_id="r",
        purpose="p",
    )
    first = ctx.as_kms_dict()
    first["table"] = "mutated"
    assert ctx.as_kms_dict()["table"] == "t"
