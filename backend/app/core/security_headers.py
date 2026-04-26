"""Security-headers middleware (plan §11, §14 Phase 8, §19.14).

Adds the OWASP-baseline header set to every response so direct hits on
the Lambda Function URL (during debugging or behind a misconfigured
CDN) are still hardened. CloudFront is the production default; this
middleware is the belt-and-braces tier when CloudFront is bypassed.

CSP rules (kept tight per Phase 8 exit criteria):

* ``default-src 'self'`` — block any cross-origin resource by default.
* ``script-src 'self' 'sha256-...'`` — Vite emits hashed bundles. The
  one inline script is the FOUC theme resolver in
  ``frontend/index.html`` (Track C — Phase I.5); its body is pinned
  via SHA-256 hash so altering it without bumping the hash blocks
  the script.
* ``style-src 'self' 'unsafe-inline'`` — Tailwind injects inline style
  blocks for the variable layer; we cannot drop ``'unsafe-inline'``
  without a runtime hash list. Acceptable because we forbid runtime
  HTML injection at the rendering layer (``react-markdown`` allowlist).
* ``img-src 'self' data: blob:`` — favicon + manifest icons + offline
  cache previews.
* ``connect-src 'self'`` — XHR/fetch only to our origin (api + same
  origin via CloudFront).
* ``frame-ancestors 'none'`` — clickjack defense; pairs with
  ``X-Frame-Options: DENY``.
* ``form-action 'self'``, ``base-uri 'self'`` — defense-in-depth.

Tests in ``backend/tests/integration/test_security_headers.py`` assert
the header set is present on a representative endpoint.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.middleware.base import BaseHTTPMiddleware

if TYPE_CHECKING:  # pragma: no cover
    from starlette.requests import Request
    from starlette.responses import Response
    from starlette.types import ASGIApp


# Single CSP definition kept here so frontend ``index.html`` and this
# middleware cannot drift. Dev / Storybook builds widen ``connect-src``
# via the ``BRIEFED_CSP_RELAX`` toggle wired into Settings later if
# needed; production stays this strict.
_FOUC_SCRIPT_HASH = "'sha256-fR2NYStsW2BshKwCzIT9vedLP8WxYCyrqpkonquA9ss='"
"""SHA-256 of the inline FOUC theme resolver in ``frontend/index.html``.

Pinned via CSP hash so the inline script runs without ``'unsafe-inline'``.
Edits to the script body must recompute this hash + the matching meta
CSP token; both are kept in lockstep.
"""


_CSP = "; ".join(
    [
        "default-src 'self'",
        f"script-src 'self' {_FOUC_SCRIPT_HASH}",
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data: blob:",
        "font-src 'self' data:",
        "connect-src 'self'",
        "frame-ancestors 'none'",
        "form-action 'self'",
        "base-uri 'self'",
        "object-src 'none'",
        "manifest-src 'self'",
        "worker-src 'self'",
        "upgrade-insecure-requests",
    ],
)


_PERMISSIONS_POLICY = ", ".join(
    [
        "geolocation=()",
        "microphone=()",
        "camera=()",
        "payment=()",
        "usb=()",
        "interest-cohort=()",
    ],
)


# Default header set applied to every response unless the caller already
# set the same key (allows targeted overrides per route).
DEFAULT_HEADERS: dict[str, str] = {
    "Content-Security-Policy": _CSP,
    # 1 year HSTS + preload — only meaningful when served over HTTPS.
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains; preload",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": _PERMISSIONS_POLICY,
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Stamp the OWASP baseline headers on every response."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        extra: dict[str, str] | None = None,
    ) -> None:
        """Initialize the middleware.

        Args:
            app: Wrapped ASGI app.
            extra: Optional header overrides merged on top of
                :data:`DEFAULT_HEADERS`.
        """
        super().__init__(app)
        self._headers: dict[str, str] = {**DEFAULT_HEADERS, **(extra or {})}

    async def dispatch(
        self,
        request: Request,
        call_next: object,
    ) -> Response:
        """Forward the request and decorate the response.

        Args:
            request: Incoming request.
            call_next: Downstream handler (typed loosely because the
                Starlette stub uses ``RequestResponseEndpoint``).

        Returns:
            The response with security headers added.
        """
        response: Response = await call_next(request)  # type: ignore[operator]
        for key, value in self._headers.items():
            response.headers.setdefault(key, value)
        return response


__all__ = ["DEFAULT_HEADERS", "SecurityHeadersMiddleware"]
