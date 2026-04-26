"""Briefed backend package.

Version is sourced from ``packages/contracts/version.json`` — the single
source of truth across backend OpenAPI ``info.version``, the React PWA
``APP_VERSION`` constant, and any release-metadata ledger row. Bump the
version in one place by editing ``version.json``.
"""

from __future__ import annotations

import json
from pathlib import Path

_VERSION_FILE = Path(__file__).resolve().parents[2] / "packages" / "contracts" / "version.json"


def _load_version() -> str:
    """Return the canonical app version from ``version.json``.

    Falls back to ``"0.0.0"`` if the file is missing or malformed so an
    accidental delete cannot wedge process startup.

    Returns:
        Semver string read from the contracts package.
    """
    try:
        with _VERSION_FILE.open(encoding="utf-8") as handle:
            payload = json.load(handle)
        version = payload.get("version")
    except (OSError, json.JSONDecodeError):
        return "0.0.0"
    return version if isinstance(version, str) and version else "0.0.0"


__version__: str = _load_version()
