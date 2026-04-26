"""Sentry SDK bootstrap (plan §14 Phase 8).

Sentry catches uncaught exceptions in api + worker Lambdas and surfaces
release/user/account context. The SDK is **optional**: if
``settings.sentry_dsn`` is unset (the test + local default) the import
turns into a no-op so unit tests do not need to stub the network.

Module-level invariants:

* ``configure_sentry`` is idempotent across SnapStart restores via the
  module-level ``_CONFIGURED`` guard, mirroring :mod:`app.core.logging`
  and :mod:`app.core.tracing`.
* The SDK is **not** imported until :func:`configure_sentry` runs, so
  cold-start bundles that disable Sentry never pay the import cost.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.core.config import Settings, get_settings

if TYPE_CHECKING:  # pragma: no cover
    pass


_CONFIGURED = False
"""SnapStart-friendly idempotency guard."""


def configure_sentry(settings: Settings | None = None) -> None:
    """Initialize the Sentry SDK when a DSN is configured.

    Args:
        settings: Optional pre-resolved :class:`Settings`. Tests pass a
            stubbed instance to avoid the SSM round-trip.
    """
    global _CONFIGURED  # noqa: PLW0603 — module-level guard, intentional.
    if _CONFIGURED:
        return

    cfg = settings or get_settings()
    dsn = cfg.sentry_dsn
    if not dsn:
        # Mark as configured so repeat calls stay cheap; the absence of a
        # DSN is the operator's explicit "off" signal.
        _CONFIGURED = True
        return

    import sentry_sdk  # type: ignore[import-not-found, unused-ignore]  # noqa: PLC0415 — lazy: Sentry is optional.
    from sentry_sdk.integrations.asyncio import (  # type: ignore[import-not-found, unused-ignore]  # noqa: PLC0415
        AsyncioIntegration,
    )
    from sentry_sdk.integrations.logging import (  # type: ignore[import-not-found, unused-ignore]  # noqa: PLC0415
        LoggingIntegration,
    )

    sentry_sdk.init(
        dsn=dsn,
        environment=cfg.env,
        traces_sample_rate=cfg.sentry_traces_sample_rate,
        send_default_pii=False,
        attach_stacktrace=True,
        integrations=[
            AsyncioIntegration(),
            # ``event_level`` controls when a structlog ``logger.error``
            # creates a Sentry event; INFO messages are still attached as
            # breadcrumbs.
            LoggingIntegration(level=None, event_level=40),  # 40 == ERROR
        ],
        before_send=_scrub,  # type: ignore[arg-type, unused-ignore]
    )
    _CONFIGURED = True


def _scrub(event: dict[str, object], _hint: dict[str, object]) -> dict[str, object] | None:
    """Strip secrets from outbound Sentry events.

    The structlog processor that drops ``Authorization`` / refresh-token
    headers also runs before Sentry sees the message, but Sentry can lift
    request headers + extras from FastAPI integrations directly. This
    second-pass scrub is defense in depth.

    Args:
        event: Sentry event payload.
        _hint: Sentry hint mapping (unused here).

    Returns:
        Mutated event, or ``None`` to drop the event entirely.
    """
    request = event.get("request")
    if isinstance(request, dict):
        headers = request.get("headers")
        if isinstance(headers, dict):
            for key in ("authorization", "cookie", "x-api-key"):
                if key in headers:
                    headers[key] = "[Filtered]"
    return event


__all__ = ["configure_sentry"]
