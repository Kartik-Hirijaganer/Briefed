"""AWS Lambda entrypoint for the FastAPI API (plan §19.15).

Wraps the ASGI app with :mod:`mangum` so the same FastAPI surface runs
behind a Lambda Function URL. Module-level initialization (FastAPI app
construction, SSM secret load on first invocation) is intentional — Lambda
SnapStart snapshots the process after init, so every warm restore skips
the cold-path cost.

This module is thin on purpose: logic belongs in ``app.main`` and in
service layers; this file is the boundary between the Lambda runtime and
the FastAPI app.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mangum import Mangum

# Importing ``app.main`` runs its module-level init block, which in turn
# invokes ``get_settings()`` (hydrates SSM secrets) + ``configure_logging``.
# That work lands inside the SnapStart snapshot so warm restores skip it.
from app.main import app

if TYPE_CHECKING:
    from collections.abc import Callable

    LambdaHandler = Callable[[dict[str, Any], Any], dict[str, Any]]


# ``lifespan="off"`` — FastAPI lifespan events don't fit the Lambda model
# (each invocation is effectively a single request); startup work must
# live at module import so SnapStart can capture it.
mangum_handler: LambdaHandler = Mangum(app, lifespan="off")
"""Lambda handler — the Terraform ``image_config.command`` points here."""
