"""Export the FastAPI OpenAPI specification to a JSON file.

Run from the repo root::

    python backend/scripts/export_openapi.py

Writes the spec to ``packages/contracts/openapi.json`` with the version pinned
to the package version declared in :mod:`app`. ``make docs`` wraps this script
so the OpenAPI JSON + frontend TypeScript client regenerate together.
"""

from __future__ import annotations

import json
from pathlib import Path

from app import __version__
from app.main import app

REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_PATH = REPO_ROOT / "packages" / "contracts" / "openapi.json"


def main() -> None:
    """Serialize the OpenAPI schema and write it to :data:`OUTPUT_PATH`."""
    schema = app.openapi()
    schema["info"]["version"] = __version__
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote OpenAPI spec v{__version__} to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
