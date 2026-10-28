"""Integration tests for :meth:`PromptRegistry.sync_to_db` with in-place edits."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import PromptVersion
from app.services.prompts.registry import USER_MESSAGE_MARKER, PromptRegistry


def _write(root: Path, *, max_tokens: int, rules: str) -> None:
    path = root / "triage" / "v2.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\nid: triage\nversion: 2\nmodel: gemini-flash\n"
        f"temperature: 0.0\nmax_tokens: {max_tokens}\n---\n"
        f"{rules}\n{USER_MESSAGE_MARKER}\n<subject>{{{{subject}}}}</subject>\n",
        encoding="utf-8",
    )


async def _rows(session: AsyncSession) -> list[PromptVersion]:
    return list((await session.execute(select(PromptVersion))).scalars().all())


async def test_sync_inserts_then_skips_unchanged(test_session: AsyncSession, tmp_path) -> None:
    _write(tmp_path, max_tokens=400, rules="rules v-a")
    registry = PromptRegistry.load(tmp_path)

    assert await registry.sync_to_db(test_session) == 1
    assert await registry.sync_to_db(test_session) == 0

    (row,) = await _rows(test_session)
    entry = registry.get("triage", version=2)
    assert row.content_hash == entry.content_hash
    assert row.content == entry.source_text
    assert USER_MESSAGE_MARKER in row.content
    assert row.params["max_tokens"] == 400


async def test_sync_refreshes_row_for_file_edited_in_place(
    test_session: AsyncSession,
    tmp_path,
) -> None:
    _write(tmp_path, max_tokens=400, rules="rules v-a")
    await PromptRegistry.load(tmp_path).sync_to_db(test_session)
    (original,) = await _rows(test_session)
    original_id = original.id

    _write(tmp_path, max_tokens=1500, rules="rules v-b")
    edited = PromptRegistry.load(tmp_path)
    assert await edited.sync_to_db(test_session) == 1

    count = (
        await test_session.execute(select(func.count()).select_from(PromptVersion))
    ).scalar_one()
    assert count == 1
    (row,) = await _rows(test_session)
    assert row.id == original_id
    assert row.content_hash == edited.get("triage", version=2).content_hash
    assert row.content.startswith("rules v-b")
    assert row.params["max_tokens"] == 1500
