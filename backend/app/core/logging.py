"""Structured logging setup using ``structlog`` (plan §5, §7).

Phase 0 ships the baseline: JSON output on stdout, level driven by
``settings.log_level``, ``context vars`` bound per request/worker
invocation. Later phases bolt on OpenTelemetry trace-id correlation
via ``opentelemetry.propagate`` and per-module log samplers.

The module is idempotent: calling :func:`configure` twice does not
double-wrap the processor chain (``structlog.configure`` itself is
idempotent in this regard).
"""

from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:  # pragma: no cover
    from structlog.typing import Processor


_CONFIGURED = False
"""Module-level guard so ``configure`` is idempotent across SnapStart restores."""


def configure(*, level: str = "info", json_output: bool = True) -> None:
    """Initialize structlog + stdlib logging.

    Call exactly once per process; module-level startup code in
    :mod:`app.lambda_api` and :mod:`app.main` invokes it before any
    other module logs. Calling again is a no-op.

    Args:
        level: Minimum log level name (``"debug"``, ``"info"``,
            ``"warning"``, ``"error"``, ``"critical"``). Case-insensitive.
        json_output: When ``True`` (default — appropriate for Lambda /
            CloudWatch), emit JSON per line. Set ``False`` for
            human-readable console output during local development.
    """
    global _CONFIGURED  # noqa: PLW0603 — intentional module-level guard
    if _CONFIGURED:
        return

    level_const = getattr(logging, level.upper(), logging.INFO)

    # Root stdlib logger — structlog routes through this so third-party
    # libs that use the stdlib logger (boto3, SQLAlchemy, etc.) still land
    # in the same JSON stream.
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=level_const,
        force=True,
    )

    processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    processors.append(
        structlog.processors.JSONRenderer()
        if json_output
        else structlog.dev.ConsoleRenderer(colors=False)
    )

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(level_const),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    _CONFIGURED = True


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a bound structlog logger.

    Args:
        name: Optional logger name; defaults to the caller's module.

    Returns:
        Bound structlog logger suitable for ``logger.info("event", foo=bar)``.
    """
    logger: structlog.stdlib.BoundLogger = (
        structlog.get_logger(name) if name else structlog.get_logger()
    )
    return logger
