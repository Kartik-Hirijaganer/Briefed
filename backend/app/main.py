"""FastAPI application entrypoint for Briefed.

Exposes the HTTP API and serves the OpenAPI / Swagger specification at
``/docs`` (Swagger UI), ``/redoc`` (ReDoc), and ``/openapi.json`` (raw spec).
"""

from fastapi import FastAPI

from app import __version__

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

    @app.get("/health", tags=["meta"], summary="Liveness probe")
    def health() -> dict[str, str]:
        """Return service liveness status.

        Returns:
            Mapping with ``status`` key set to ``"ok"`` when the service is up.
        """
        return {"status": "ok", "version": __version__}

    return app


app = create_app()
