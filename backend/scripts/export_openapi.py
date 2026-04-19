"""Export the FastAPI OpenAPI specification to a JSON file.

Run from the repo root::

    python -m backend.scripts.export_openapi

Writes the spec to ``docs/openapi.json`` with the version pinned to the
package version declared in :mod:`app`.
"""

from __future__ import annotations

import json
from pathlib import Path

from app import __version__
from app.main import app

OUTPUT_PATH = Path(__file__).resolve().parents[2] / "docs" / "openapi.json"


def main() -> None:
    """Serialize the OpenAPI schema and write it to :data:`OUTPUT_PATH`."""
    schema = app.openapi()
    schema["info"]["version"] = __version__
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote OpenAPI spec v{__version__} to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
