"""Versioned prompt registry (plan §6, §14 Phase 2).

Every prompt under ``packages/prompts/**/v*.md`` is loaded into memory
at cold-start and indexed by ``(name, version)``. The DB table
``prompt_versions`` is upserted from the same bundle so
``prompt_call_log.prompt_version_id`` FKs resolve cleanly.

Frontmatter contract (required keys):

    ---
    id: triage
    version: 1
    owner: "@user"
    provider: gemini
    model: gemini-1.5-flash
    temperature: 0.0
    max_tokens: 400
    output_schema: ../schemas/triage.v1.json
    schema_ref: TriageDecision
    cache_tier: gemini_context
    ---

Missing required keys or duplicate ``(id, version)`` pairs raise
:class:`PromptBundleError` loudly at boot.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from app.core.logging import get_logger
from app.db.models import PromptVersion
from app.llm.providers.base import PromptSpec

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Mapping

    from sqlalchemy.ext.asyncio import AsyncSession


logger = get_logger(__name__)

_REQUIRED_KEYS: tuple[str, ...] = (
    "id",
    "version",
    "model",
    "temperature",
    "max_tokens",
)
"""Frontmatter keys every prompt file must declare."""

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n(.*)\Z", re.DOTALL)
"""Matches a YAML frontmatter block followed by the prompt body."""


class PromptBundleError(Exception):
    """Raised when a prompt file is malformed or ambiguous."""


@dataclass(frozen=True)
class RegisteredPrompt:
    """One entry in the registry.

    Attributes:
        spec: Immutable :class:`PromptSpec`.
        content_hash: SHA-256 digest of ``spec.content``. Propagates to
            ``prompt_versions.content_hash``.
        frontmatter: Raw frontmatter dict (useful for diagnostics).
        source_path: Path of the backing markdown file, if any.
    """

    spec: PromptSpec
    content_hash: bytes
    frontmatter: Mapping[str, Any]
    source_path: Path | None = None


def default_prompt_root() -> Path:
    """Return the repo-relative ``packages/prompts/`` directory.

    Returns:
        The :class:`pathlib.Path` on disk. Absolute so tests can chdir
        without breaking resolution.
    """
    # backend/app/services/prompts/registry.py → repo root is five up.
    return Path(__file__).resolve().parents[4] / "packages" / "prompts"


class PromptRegistry:
    """In-memory registry keyed by ``(name, version)``.

    Construct via :meth:`load` so tests can point at a fixture tree.
    ``get()`` + ``latest()`` are the two hot-path accessors.
    """

    def __init__(self, entries: dict[tuple[str, int], RegisteredPrompt]) -> None:
        """Store a pre-built index.

        Args:
            entries: Mapping from ``(name, version)`` to the loaded
                :class:`RegisteredPrompt`.
        """
        self._entries = dict(entries)

    @classmethod
    def load(
        cls,
        root: Path | None = None,
        *,
        include_globs: tuple[str, ...] = ("*/v*.md",),
    ) -> PromptRegistry:
        """Walk ``root`` and build a registry.

        Args:
            root: Base directory; defaults to :func:`default_prompt_root`.
            include_globs: Glob patterns to include relative to ``root``.

        Returns:
            A populated :class:`PromptRegistry`.

        Raises:
            PromptBundleError: When a prompt file cannot be parsed or
                when a ``(name, version)`` pair appears twice.
        """
        base = root if root is not None else default_prompt_root()
        if not base.exists():
            raise PromptBundleError(f"prompt root does not exist: {base}")

        paths: list[Path] = []
        for pattern in include_globs:
            paths.extend(sorted(base.glob(pattern)))

        entries: dict[tuple[str, int], RegisteredPrompt] = {}
        for path in paths:
            entry = _load_file(path)
            key = (entry.spec.name, entry.spec.version)
            if key in entries:
                raise PromptBundleError(
                    f"duplicate prompt {key!r} at {path} vs {entries[key].source_path}"
                )
            entries[key] = entry
            logger.info(
                "prompts.loaded",
                name=entry.spec.name,
                version=entry.spec.version,
                path=str(path),
                hash=entry.content_hash.hex(),
            )
        if not entries:
            raise PromptBundleError(f"no prompts found under {base}")
        return cls(entries)

    def get(self, name: str, *, version: int) -> RegisteredPrompt:
        """Return the registered prompt for ``(name, version)``.

        Args:
            name: Prompt key.
            version: Integer version.

        Returns:
            The :class:`RegisteredPrompt`.

        Raises:
            KeyError: When the entry is not registered.
        """
        try:
            return self._entries[(name, version)]
        except KeyError as exc:
            raise KeyError(f"prompt {name} v{version} not registered") from exc

    def latest(self, name: str) -> RegisteredPrompt:
        """Return the highest-versioned entry for ``name``.

        Args:
            name: Prompt key.

        Returns:
            The :class:`RegisteredPrompt` with the largest ``version``.

        Raises:
            KeyError: When no versions exist.
        """
        matches = [entry for (key, entry) in self._entries.items() if key[0] == name]
        if not matches:
            raise KeyError(f"prompt {name} has no registered versions")
        return max(matches, key=lambda entry: entry.spec.version)

    def all(self) -> tuple[RegisteredPrompt, ...]:
        """Return every registered prompt as an immutable tuple."""
        return tuple(self._entries.values())

    async def sync_to_db(self, session: AsyncSession) -> int:
        """Upsert every registered prompt into ``prompt_versions``.

        Called once per Lambda cold start (and explicitly by the test
        harness) so ``prompt_call_log`` FKs resolve to durable rows.

        Args:
            session: Active async session. Caller owns the commit.

        Returns:
            Count of rows inserted (existing rows are left alone).
        """
        inserted = 0
        for entry in self._entries.values():
            existing = (
                (
                    await session.execute(
                        select(PromptVersion).where(
                            PromptVersion.content_hash == entry.content_hash,
                        ),
                    )
                )
                .scalars()
                .first()
            )
            if existing is not None:
                continue
            session.add(
                PromptVersion(
                    name=entry.spec.name,
                    version=entry.spec.version,
                    content=entry.spec.content,
                    content_hash=entry.content_hash,
                    model=entry.spec.model,
                    params={
                        "temperature": entry.spec.temperature,
                        "max_tokens": entry.spec.max_tokens,
                        "cache_tier": entry.spec.cache_tier,
                        "schema_ref": entry.spec.schema_ref,
                    },
                ),
            )
            inserted += 1
        await session.flush()
        return inserted


def _load_file(path: Path) -> RegisteredPrompt:
    """Parse one prompt file into a :class:`RegisteredPrompt`.

    Args:
        path: Path to the markdown file.

    Returns:
        The parsed registry entry.

    Raises:
        PromptBundleError: On malformed YAML frontmatter or missing keys.
    """
    text = path.read_text(encoding="utf-8")
    match = _FRONTMATTER_RE.match(text)
    if match is None:
        raise PromptBundleError(f"{path} missing YAML frontmatter")

    raw_front, body = match.group(1), match.group(2).strip()
    front = _parse_frontmatter(raw_front, source=str(path))

    missing = [key for key in _REQUIRED_KEYS if key not in front]
    if missing:
        raise PromptBundleError(f"{path} frontmatter missing keys: {missing}")

    content_hash = hashlib.sha256(body.encode("utf-8")).digest()
    spec = PromptSpec(
        name=str(front["id"]),
        version=int(front["version"]),
        content=body,
        model=str(front["model"]),
        temperature=float(front.get("temperature", 0.0)),
        max_tokens=int(front.get("max_tokens", 512)),
        cache_tier=str(front.get("cache_tier", "none")),
        schema_ref=str(front.get("schema_ref", "")),
        extras={
            k: v
            for k, v in front.items()
            if k
            not in {
                "id",
                "version",
                "model",
                "temperature",
                "max_tokens",
                "cache_tier",
                "schema_ref",
            }
        },
    )
    return RegisteredPrompt(
        spec=spec,
        content_hash=content_hash,
        frontmatter=front,
        source_path=path,
    )


_SCALAR_STR_RE = re.compile(r"^\"(.*)\"$|^'(.*)'$")
"""Match a quoted scalar value; captures the inner string."""

_INT_RE = re.compile(r"^-?\d+$")
"""Match a signed integer literal."""

_FLOAT_RE = re.compile(r"^-?\d+\.\d+$")
"""Match a signed float literal."""


def _parse_frontmatter(text: str, *, source: str) -> dict[str, Any]:
    """Minimal YAML-flavored frontmatter parser (no external dep).

    Supports the subset we need: ``key: value`` per line with optional
    quoting, integers, and floats. Complex YAML (nested maps, anchors,
    block scalars) is out of scope — the prompt bundle never needs it.

    Args:
        text: Raw frontmatter block (between the ``---`` markers).
        source: Path for error messages.

    Returns:
        Typed scalar mapping.

    Raises:
        PromptBundleError: On a malformed line.
    """
    out: dict[str, Any] = {}
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        if ":" not in line:
            raise PromptBundleError(f"{source}: malformed frontmatter line {raw!r}")
        key, _, value = line.partition(":")
        out[key.strip()] = _coerce(value.strip())
    return out


_BOOL_SCALARS: dict[str, bool] = {"true": True, "false": False}
"""Boolean literals the frontmatter parser recognizes."""


def _coerce(value: str) -> str | int | float | bool:
    """Coerce a frontmatter scalar into a typed Python value.

    Args:
        value: Raw right-hand side.

    Returns:
        Parsed scalar (str / int / float / bool).
    """
    if not value:
        return ""
    match = _SCALAR_STR_RE.match(value)
    if match is not None:
        return match.group(1) or match.group(2) or ""
    boolean = _BOOL_SCALARS.get(value.lower())
    if boolean is not None:
        return boolean
    if _INT_RE.match(value):
        return int(value)
    if _FLOAT_RE.match(value):
        return float(value)
    return value


__all__ = [
    "PromptBundleError",
    "PromptRegistry",
    "RegisteredPrompt",
    "default_prompt_root",
]
