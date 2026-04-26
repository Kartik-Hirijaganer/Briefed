"""Scan markdown files for broken relative links.

Plan §14 Phase 9 + Verification §10: documentation link-check is a
release gate. Runs over the top-level README, CONTRIBUTING, and every
markdown under ``docs/``. External (``http://`` / ``https://``) links
are skipped — too noisy and offline-unfriendly. Only file-relative and
in-page anchors are validated.

Exit code is ``1`` on the first broken link, with a summary printed
to stdout. The CI ``docs-drift`` job depends on this script via
``make link-check``.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

INCLUDE_PATHS = (
    "README.md",
    "CONTRIBUTING.md",
    "CHANGELOG.md",
    "CLAUDE.md",
)

INCLUDE_DIRS = ("docs",)

LINK_RE = re.compile(r"\[(?P<text>[^\]]*?)\]\((?P<href>[^)\s]+)(?:\s+\"[^\"]*\")?\)")
"""Match standard ``[text](href)`` markdown links, ignoring the optional title."""


def _is_external(href: str) -> bool:
    """Return True if the href is an absolute URL or mailto."""
    return href.startswith(("http://", "https://", "mailto:", "tel:"))


def _strip_anchor(href: str) -> tuple[str, str | None]:
    """Split ``href#anchor`` into ``(href, anchor or None)``."""
    if "#" not in href:
        return href, None
    target, _, anchor = href.partition("#")
    return target, anchor or None


def _resolve(base: Path, href: str) -> Path:
    """Resolve a relative href against the file containing it."""
    if href.startswith("/"):
        return REPO_ROOT / href.lstrip("/")
    return (base.parent / href).resolve()


def _slugify(heading: str) -> str:
    """Approximate GitHub's heading-to-anchor algorithm.

    GitHub's slug strips non-word punctuation but preserves the
    *spacing* around it: ``(token + content CMKs)`` collapses to
    ``token--content-cmks`` because ``+`` is removed from between two
    spaces, and each remaining space converts to a single hyphen
    (no run-collapsing). Match that behavior so anchors survive the
    link-check.
    """
    text = heading.strip().lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = text.replace(" ", "-").strip("-")
    return text


def _collect_anchors(path: Path) -> set[str]:
    """Return the set of GitHub-flavoured anchors a markdown file exposes."""
    anchors: set[str] = set()
    if not path.is_file():
        return anchors
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.lstrip()
        if stripped.startswith("#"):
            heading = stripped.lstrip("#").strip()
            if heading:
                anchors.add(_slugify(heading))
        explicit = re.findall(r"<a\s+(?:[^>]*?\s+)?(?:id|name)=\"([^\"]+)\"", line)
        anchors.update(explicit)
    return anchors


def _iter_targets() -> list[Path]:
    """Yield every markdown file in scope of the link-check."""
    targets: list[Path] = []
    for rel in INCLUDE_PATHS:
        path = REPO_ROOT / rel
        if path.is_file():
            targets.append(path)
    for rel_dir in INCLUDE_DIRS:
        root = REPO_ROOT / rel_dir
        if root.is_dir():
            targets.extend(sorted(root.rglob("*.md")))
    return targets


def _check_link(source: Path, href: str) -> str | None:  # noqa: PLR0911 — distinct early-exit cases
    """Return an error string if a link is broken; ``None`` if OK."""
    if _is_external(href):
        return None
    if href.startswith("#"):
        anchor = href[1:]
        if anchor and anchor not in _collect_anchors(source):
            return f"missing in-page anchor #{anchor}"
        return None
    target, anchor = _strip_anchor(href)
    if target.startswith("mailto:"):
        return None
    resolved = _resolve(source, target)
    if not resolved.exists():
        return f"missing target {target}"
    if anchor and resolved.suffix == ".md" and anchor not in _collect_anchors(resolved):
        return f"missing anchor #{anchor} in {target}"
    return None


def main() -> int:
    """Walk every markdown source and print broken links."""
    failures: list[str] = []
    for source in _iter_targets():
        for match in LINK_RE.finditer(source.read_text(encoding="utf-8")):
            href = match.group("href").strip()
            error = _check_link(source, href)
            if error is not None:
                rel = source.relative_to(REPO_ROOT).as_posix()
                failures.append(f"{rel}: [{match.group('text')}]({href}) — {error}")

    if failures:
        print("Link-check failed:")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    print(f"Link-check passed — {len(_iter_targets())} markdown files clean.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
