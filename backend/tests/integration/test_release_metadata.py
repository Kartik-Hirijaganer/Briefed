"""Integration tests for the Phase 9 ``release_metadata`` ledger.

The model is append-only — a rollback emits a *new* row with the
previous version's SHA. The unique constraint on ``(version, git_sha)``
prevents accidental double-writes when the deploy workflow retries.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ReleaseMetadata


async def test_release_metadata_round_trip(test_session: AsyncSession) -> None:
    """A release_metadata row inserts and reads back with all columns."""
    row = ReleaseMetadata(
        version="1.0.0",
        git_sha="0" * 40,
        alembic_head="0007",
        api_schema_version="1.0.0",
        db_schema_version="0007",
        frontend_build_id="abc1234567890def",
        prompt_bundle_version="prompt-bundle-001",
        notes="first cut",
    )
    test_session.add(row)
    await test_session.commit()

    fetched = (
        await test_session.execute(
            sa.select(ReleaseMetadata).where(ReleaseMetadata.version == "1.0.0"),
        )
    ).scalar_one()

    assert fetched.git_sha == "0" * 40
    assert fetched.alembic_head == "0007"
    assert fetched.db_schema_version == "0007"
    assert fetched.api_schema_version == "1.0.0"
    assert fetched.frontend_build_id == "abc1234567890def"
    assert fetched.prompt_bundle_version == "prompt-bundle-001"
    assert fetched.notes == "first cut"
    assert fetched.deployed_at is not None


async def test_release_metadata_unique_version_sha(test_session: AsyncSession) -> None:
    """Inserting the same (version, git_sha) twice raises IntegrityError."""
    base_kwargs = {
        "version": "1.0.0",
        "git_sha": "1" * 40,
        "alembic_head": "0007",
        "api_schema_version": "1.0.0",
        "db_schema_version": "0007",
    }
    test_session.add(ReleaseMetadata(**base_kwargs))
    await test_session.commit()

    test_session.add(ReleaseMetadata(**base_kwargs))
    raised = False
    try:
        await test_session.commit()
    except sa.exc.IntegrityError:
        raised = True
        await test_session.rollback()
    assert raised, "expected IntegrityError on duplicate (version, git_sha)"


async def test_release_metadata_rollback_emits_new_row(test_session: AsyncSession) -> None:
    """A rollback writes a fresh row pointing at the previous SHA."""
    test_session.add(
        ReleaseMetadata(
            version="1.1.0",
            git_sha="a" * 40,
            alembic_head="0008",
            api_schema_version="1.1.0",
            db_schema_version="0008",
            notes="cut",
        ),
    )
    await test_session.commit()

    test_session.add(
        ReleaseMetadata(
            version="1.0.0",
            git_sha="b" * 40,
            alembic_head="0007",
            api_schema_version="1.0.0",
            db_schema_version="0007",
            notes="rollback to 1.0.0 after 1.1.0 regression",
        ),
    )
    await test_session.commit()

    rows = (
        (
            await test_session.execute(
                sa.select(ReleaseMetadata).order_by(ReleaseMetadata.deployed_at.asc()),
            )
        )
        .scalars()
        .all()
    )

    assert [row.version for row in rows] == ["1.1.0", "1.0.0"]
    assert rows[-1].notes is not None and "rollback" in rows[-1].notes
