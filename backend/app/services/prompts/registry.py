"""Versioned prompt registry (plan §6, §14 Phase 2).

Every prompt under ``packages/prompts/**/v*.md`` is loaded into memory
at cold-start and indexed by ``(name, version)``. The DB table
``prompt_versions`` is upserted from the same bundle so
``prompt_call_log.prompt_version_id`` FKs resolve cleanly.

Frontmatter contract (required keys):

    ---
    id: triage
    version: 2
    owner: "@user"
    provider: gemini
    model: gemini-flash
    temperature: 0.0
    max_tokens: 400
    output_schema: ../schemas/triage.v2.json
    schema_ref: TriageDecision
    cache_tier: gemini_context
    ---

``model`` is a catalog key from ``packages/config/llm/catalog.yml``.
Missing required keys, unknown model keys, or duplicate ``(id, version)``
pairs raise :class:`PromptBundleError` loudly at boot.

Body contract: the system message, then a line reading exactly
``<!-- user message -->``, then the user-message template. Only the user
template may hold ``{{placeholders}}``, so untrusted input never reaches
the system message. Prompt files are edited in place; :meth:`PromptRegistry.sync_to_db`
refreshes the existing ``(name, version)`` row when a file changes.
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from app.core.logging import get_logger
from app.core.yaml import YamlConfigError, safe_load_yaml_mapping
from app.db.models import PromptVersion
from app.llm.catalog import UnknownModelError
from app.llm.catalog import resolve as resolve_model
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

USER_MESSAGE_MARKER = "<!-- user message -->"
"""Line that splits a prompt body into system message and user template."""

_USER_MESSAGE_SPLIT_RE = re.compile(rf"^{re.escape(USER_MESSAGE_MARKER)}[ \t]*$", re.MULTILINE)
"""Matches the marker only when it stands alone on its own line."""


class PromptBundleError(Exception):
    """Raised when a prompt file is malformed or ambiguous."""


@dataclass(frozen=True)
class RegisteredPrompt:
    """One entry in the registry.

    Attributes:
        spec: Immutable :class:`PromptSpec`.
        content_hash: SHA-256 digest of the whole prompt file, so any edit
            (frontmatter included) refreshes ``prompt_versions``.
        frontmatter: Raw frontmatter dict (useful for diagnostics).
        source_path: Path of the backing markdown file, if any.
        source_text: Full prompt body (system message, marker, user
            template) stored in ``prompt_versions.content``.
    """

    spec: PromptSpec
    content_hash: bytes
    frontmatter: Mapping[str, Any]
    source_path: Path | None = None
    source_text: str = ""


def default_prompt_root() -> Path:
    """Return the packaged or repo-relative ``packages/prompts/`` directory.

    Returns:
        The :class:`pathlib.Path` on disk. Absolute so tests can chdir
        without breaking resolution.
    """
    lambda_task_root = os.environ.get("LAMBDA_TASK_ROOT")
    if lambda_task_root:
        lambda_prompt_root = Path(lambda_task_root) / "packages" / "prompts"
        if lambda_prompt_root.exists():
            return lambda_prompt_root

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

        Called on every worker invocation so ``prompt_call_log`` FKs resolve
        to durable rows. A file edited in place keeps its ``(name, version)``
        row: the row's text, hash, model, and params are refreshed, so
        handlers that resolve the row by ``content_hash`` find it again.

        Args:
            session: Active async session. Caller owns the commit.

        Returns:
            Count of rows inserted or refreshed (unchanged rows are skipped).
        """
        written = 0
        for entry in self._entries.values():
            unchanged = (
                await session.execute(
                    select(PromptVersion.id).where(
                        PromptVersion.content_hash == entry.content_hash,
                    ),
                )
            ).first()
            if unchanged is not None:
                continue
            row = (
                (
                    await session.execute(
                        select(PromptVersion).where(
                            PromptVersion.name == entry.spec.name,
                            PromptVersion.version == entry.spec.version,
                        ),
                    )
                )
                .scalars()
                .first()
            )
            if row is None:
                row = PromptVersion(name=entry.spec.name, version=entry.spec.version)
                session.add(row)
            row.content = entry.source_text or entry.spec.content
            row.content_hash = entry.content_hash
            row.model = entry.spec.model
            row.params = {
                "temperature": entry.spec.temperature,
                "max_tokens": entry.spec.max_tokens,
                "cache_tier": entry.spec.cache_tier,
                "schema_ref": entry.spec.schema_ref,
            }
            written += 1
        await session.flush()
        return written


def _load_file(path: Path) -> RegisteredPrompt:
    """Parse one prompt file into a :class:`RegisteredPrompt`.

    Args:
        path: Path to the markdown file.

    Returns:
        The parsed registry entry.

    Raises:
        PromptBundleError: On malformed YAML frontmatter, missing keys, or a
            body that does not split into system message and user template.
    """
    text = path.read_text(encoding="utf-8")
    match = _FRONTMATTER_RE.match(text)
    if match is None:
        raise PromptBundleError(f"{path} missing YAML frontmatter")

    raw_front, body = match.group(1), match.group(2).strip()
    front = _parse_frontmatter(raw_front, source=str(path))
    system, user_template = _split_body(body, source=str(path))

    missing = [key for key in _REQUIRED_KEYS if key not in front]
    if missing:
        raise PromptBundleError(f"{path} frontmatter missing keys: {missing}")

    model = str(front["model"])
    try:
        resolve_model(model)
    except UnknownModelError as exc:
        raise PromptBundleError(f"{path} frontmatter references unknown model {model!r}") from exc

    content_hash = hashlib.sha256(text.encode("utf-8")).digest()
    spec = PromptSpec(
        name=str(front["id"]),
        version=int(front["version"]),
        system=system,
        content=user_template,
        model=model,
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
        source_text=body,
    )


def _split_body(body: str, *, source: str) -> tuple[str, str]:
    """Split a prompt body into its system message and user template.

    Args:
        body: Prompt text after the frontmatter.
        source: File path used in error messages.

    Returns:
        ``(system, user_template)``, both stripped and non-empty.

    Raises:
        PromptBundleError: If the marker is missing or repeated, either
            side is empty, or the system message holds a placeholder.
    """
    if len(_USER_MESSAGE_SPLIT_RE.findall(body)) != 1:
        raise PromptBundleError(
            f"{source} must contain exactly one {USER_MESSAGE_MARKER!r} line",
        )
    raw_system, raw_user = _USER_MESSAGE_SPLIT_RE.split(body)
    system, user_template = raw_system.strip(), raw_user.strip()
    if not system or not user_template:
        raise PromptBundleError(f"{source} needs text on both sides of {USER_MESSAGE_MARKER!r}")
    if "{{" in system:
        raise PromptBundleError(
            f"{source} system message must not contain {{{{placeholders}}}}; "
            "move input into the user template",
        )
    return system, user_template


def _parse_frontmatter(text: str, *, source: str) -> dict[str, Any]:
    """Parse YAML frontmatter into a mapping.

    Args:
        text: Raw frontmatter block (between the ``---`` markers).
        source: Path for error messages.

    Returns:
        Typed scalar mapping.

    Raises:
        PromptBundleError: On a malformed line.
    """
    try:
        return safe_load_yaml_mapping(text, source=source)
    except YamlConfigError as exc:
        raise PromptBundleError(str(exc)) from exc


__all__ = [
    "PromptBundleError",
    "PromptRegistry",
    "RegisteredPrompt",
    "default_prompt_root",
]
