"""FastAPI application entrypoint for Briefed.

Exposes the HTTP API and serves the OpenAPI / Swagger specification at
``/docs`` (Swagger UI), ``/redoc`` (ReDoc), and ``/openapi.json`` (raw spec).

Module-level side effects
-------------------------
Settings are loaded and logging is configured at import time (not in the
``create_app`` factory) so Lambda SnapStart snapshots a fully-initialized
process. Subsequent warm restores skip both the SSM round-trip and the
``structlog.configure`` call.
"""

from fastapi import FastAPI

from app import __version__
from app.api.v1 import api_router
from app.core.config import get_settings
from app.core.logging import configure as configure_logging
from app.core.security_headers import SecurityHeadersMiddleware
from app.core.sentry import configure_sentry
from app.core.tracing import configure_tracing, instrument_app

# SnapStart-friendly init. ``get_settings`` is memoized via ``lru_cache``;
# the first call triggers SSM hydration in Lambda mode. ``configure_logging``,
# ``configure_tracing`` and ``configure_sentry`` are all idempotent so a
# re-import during testing or a SnapStart restore is a no-op.
_settings = get_settings()
configure_tracing(_settings)
configure_logging(level=_settings.log_level, json_output=_settings.runtime != "local")
configure_sentry(_settings)

API_TITLE = "Briefed API"
API_DESCRIPTION = (
    "Personal AI email agent. Runs a daily pipeline on the user's Gmail inbox, "
    "categorizes and prioritizes messages, and summarizes tech news via the Claude API."
)


def create_app() -> FastAPI:
    """Build and configure the FastAPI application.

    Returns:
        Configured FastAPI instance with version pinned to the package version.
    """
    app = FastAPI(
        title=API_TITLE,
        description=API_DESCRIPTION,
        version=__version__,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    # Phase 8: OWASP-baseline security headers (CSP / HSTS / nosniff / …)
    # land on every response; OTel auto-instrumentation propagates trace
    # IDs into request spans + logs.
    app.add_middleware(SecurityHeadersMiddleware)
    instrument_app(app)

    @app.get("/health", tags=["meta"], summary="Liveness probe")
    def health() -> dict[str, str]:
        """Return service liveness status.

        Returns:
            Mapping with ``status`` key set to ``"ok"`` when the service is up.
        """
        return {"status": "ok", "version": __version__}

    app.include_router(api_router)
    return app


app = create_app()
