"""Helpers for Aegis-compatible API error envelopes."""

from __future__ import annotations

from uuid import uuid4

from fastapi.responses import JSONResponse
from starlette.requests import Request

from app.schemas.emails import ErrorEnvelope


def request_id_for(request: Request) -> str:
    """Return a request id from headers or create one.

    Args:
        request: Incoming HTTP request.

    Returns:
        Stable correlation id for the error response.
    """
    request_id = request.headers.get("x-request-id")
    if request_id:
        return request_id
    return uuid4().hex


def api_error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    request: Request,
    details: dict[str, object] | None = None,
) -> JSONResponse:
    """Build an Aegis-compatible JSON error response.

    Args:
        status_code: HTTP status code.
        code: Stable machine-readable error code.
        message: User-safe error summary.
        request: Incoming HTTP request, used for error correlation.
        details: Optional structured diagnostic context.

    Returns:
        JSON response with ``code``, ``message``, ``details``, and
        ``requestId`` fields.
    """
    envelope = ErrorEnvelope(
        code=code,
        message=message,
        details=details or {},
        request_id=request_id_for(request),
    )
    return JSONResponse(
        status_code=status_code,
        content=envelope.model_dump(by_alias=True),
    )


__all__ = ["api_error_response", "request_id_for"]
