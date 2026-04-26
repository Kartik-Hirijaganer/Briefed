"""Insert a ``release_metadata`` row from the deploy workflow.

Plan §8 + §19.7 + §14 Phase 9. Called as the last step of
``deploy-prod.yml`` after ``aws lambda update-alias`` succeeds, so the
DB ledger reflects what is actually serving traffic.

Usage::

    python backend/scripts/write_release_metadata.py \\
        --version v1.0.0 \\
        --git-sha "$GITHUB_SHA" \\
        --notes "first cut"

The script is intentionally idempotent: a unique constraint on
``(version, git_sha)`` rejects duplicate writes, and the script swallows
that error with a non-zero exit only on *unexpected* failures. Re-running
the workflow on the same image is a no-op.

Computes ``alembic_head`` / ``api_schema_version`` /
``prompt_bundle_version`` / ``frontend_build_id`` from the on-disk
artifacts; passes ``--frontend-build-id`` overrides the auto-computed
value when CI is the source of truth (Vite build hash).
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import sys
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from app.db.models import ReleaseMetadata
from app.db.session import get_sessionmaker

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_VERSIONS_DIR = REPO_ROOT / "backend" / "alembic" / "versions"
OPENAPI_PATH = REPO_ROOT / "packages" / "contracts" / "openapi.json"
PROMPTS_DIR = REPO_ROOT / "packages" / "prompts"
FRONTEND_DIST_DIR = REPO_ROOT / "frontend" / "dist"

logger = logging.getLogger("briefed.release")


def _semver(value: str) -> str:
    """Strip a leading ``v`` from a tag-shaped version string."""
    return value.removeprefix("v").strip()


def detect_alembic_head() -> str:
    """Return the highest revision id under ``backend/alembic/versions``.

    Reads each ``00NN_*.py`` file's ``revision: str = "..."`` line so the
    script does not need a live DB connection at the moment of writing.
    The deploy workflow already ran ``alembic upgrade head`` before this
    script fires, so the on-disk head matches the DB head.
    """
    revisions: list[str] = []
    for path in sorted(ALEMBIC_VERSIONS_DIR.glob("[0-9][0-9][0-9][0-9]_*.py")):
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("revision: str = "):
                revisions.append(stripped.split('"')[1])
                break
    if not revisions:
        raise RuntimeError("No Alembic revisions found under backend/alembic/versions")
    return revisions[-1]


def detect_api_schema_version() -> str:
    """Return ``info.version`` from the committed OpenAPI JSON."""
    if not OPENAPI_PATH.is_file():
        raise RuntimeError(f"OpenAPI artifact missing: {OPENAPI_PATH}")
    spec = json.loads(OPENAPI_PATH.read_text(encoding="utf-8"))
    info = spec.get("info") or {}
    version = info.get("version")
    if not isinstance(version, str) or not version:
        raise RuntimeError("OpenAPI info.version is missing or empty")
    return version


def detect_prompt_bundle_version() -> str:
    """Return a stable hash over every versioned prompt + JSON Schema.

    Concatenates SHA-256 digests of every ``packages/prompts/**/v*.md``
    file and every ``packages/prompts/schemas/*.json`` file, then hashes
    the result so a single 16-char hex string identifies the bundle.
    Two deploys of the same prompts share the same id.
    """
    hasher = hashlib.sha256()
    bundle_files = sorted(
        list(PROMPTS_DIR.rglob("v*.md")) + list((PROMPTS_DIR / "schemas").glob("*.json")),
    )
    for path in bundle_files:
        rel = path.relative_to(REPO_ROOT).as_posix()
        hasher.update(rel.encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(path.read_bytes())
    return hasher.hexdigest()[:16]


def detect_frontend_build_id() -> str | None:
    """Return the Vite build hash if a frontend dist is on disk.

    Vite emits hashed asset filenames into ``frontend/dist/assets``;
    ``index.html`` references one of them. Hashing the manifest gives a
    stable per-build id without needing CI to inject a value.
    Returns ``None`` when the dist tree is absent (CI passes an explicit
    ``--frontend-build-id`` instead).
    """
    if not FRONTEND_DIST_DIR.is_dir():
        return None
    hasher = hashlib.sha256()
    for path in sorted(FRONTEND_DIST_DIR.rglob("*")):
        if path.is_file():
            hasher.update(path.relative_to(FRONTEND_DIST_DIR).as_posix().encode("utf-8"))
            hasher.update(b"\0")
            hasher.update(path.read_bytes())
    return hasher.hexdigest()[:16]


async def write_row(
    *,
    version: str,
    git_sha: str,
    alembic_head: str,
    api_schema_version: str,
    prompt_bundle_version: str | None,
    frontend_build_id: str | None,
    notes: str | None,
) -> bool:
    """Insert one ``release_metadata`` row.

    Returns:
        ``True`` if the row was inserted, ``False`` if a duplicate
        ``(version, git_sha)`` already existed (idempotent re-run).
    """
    async with get_sessionmaker()() as session:
        row = ReleaseMetadata(
            version=version,
            git_sha=git_sha,
            alembic_head=alembic_head,
            api_schema_version=api_schema_version,
            db_schema_version=alembic_head,
            frontend_build_id=frontend_build_id,
            prompt_bundle_version=prompt_bundle_version,
            notes=notes,
        )
        session.add(row)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            existing_stmt = sa.select(sa.func.count()).select_from(ReleaseMetadata).where(
                sa.and_(
                    ReleaseMetadata.version == version,
                    ReleaseMetadata.git_sha == git_sha,
                ),
            )
            existing = (await session.execute(existing_stmt)).scalar_one()
            return existing == 0
    return True


def main(argv: list[str] | None = None) -> int:
    """Parse args, compute artifact ids, and write the row."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--version", required=True, help="Tag (with or without leading 'v').")
    parser.add_argument("--git-sha", required=True, help="40-char commit SHA the image was built from.")
    parser.add_argument("--notes", default=None, help="Free-form release-engineer note.")
    parser.add_argument(
        "--frontend-build-id",
        default=None,
        help="Override the auto-detected Vite build hash. CI passes the build artifact hash.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute artifact ids and print them; do not write to the DB.",
    )
    args = parser.parse_args(argv)

    version = _semver(args.version)
    if len(args.git_sha) < 7:
        parser.error("--git-sha must be a real commit SHA")

    alembic_head = detect_alembic_head()
    api_schema_version = detect_api_schema_version()
    prompt_bundle_version = detect_prompt_bundle_version()
    frontend_build_id = args.frontend_build_id or detect_frontend_build_id()

    payload = {
        "version": version,
        "git_sha": args.git_sha,
        "alembic_head": alembic_head,
        "api_schema_version": api_schema_version,
        "db_schema_version": alembic_head,
        "frontend_build_id": frontend_build_id,
        "prompt_bundle_version": prompt_bundle_version,
        "notes": args.notes,
    }
    logger.info("release_metadata payload: %s", json.dumps(payload, sort_keys=True))

    if args.dry_run:
        return 0

    inserted = asyncio.run(
        write_row(
            version=version,
            git_sha=args.git_sha,
            alembic_head=alembic_head,
            api_schema_version=api_schema_version,
            prompt_bundle_version=prompt_bundle_version,
            frontend_build_id=frontend_build_id,
            notes=args.notes,
        ),
    )
    if inserted:
        logger.info("release_metadata row written")
    else:
        logger.info("release_metadata row already present — no-op")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or [arg for arg in os.environ.get("RELEASE_ARGS", "").split() if arg]))
