"""OpenTelemetry bootstrap for Briefed (plan §5, §7, §14 Phase 8).

Phase 8 wires structlog + OTel end-to-end so every log line carries the
active span's ``trace_id`` and ``span_id``. CloudWatch + Sentry can then
join the JSON log stream against traces without per-callsite plumbing.

Design choices:

* ``configure_tracing`` is **idempotent** — Lambda SnapStart restores the
  module image, so every cold-start invokes this twice. The module-level
  ``_CONFIGURED`` guard mirrors :mod:`app.core.logging`.
* No vendor SDK is hard-coded. The exporter is selected from
  ``settings.otel_exporter``: ``none`` (default for tests + local) drops
  spans on the floor; ``otlp`` ships them to whatever ADOT collector the
  Lambda has been wired to via ``OTEL_EXPORTER_OTLP_ENDPOINT``. CloudWatch
  Container Insights ingestion happens at the collector edge — the app
  never imports ``opentelemetry-exporter-cloudwatch`` directly so the
  cold-start bundle stays small.
* :func:`instrument_app` wraps a FastAPI app with the OTel ASGI
  middleware. Worker handlers do not auto-instrument — they create
  spans manually around per-record dispatch via :func:`worker_span`.
* :func:`bind_trace_context_to_logs` adds a structlog processor that
  injects the active ``trace_id`` / ``span_id`` into every JSON log
  entry. Calls to :func:`app.core.logging.configure` register it once.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from opentelemetry import trace
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
)

from app.core.config import Settings, get_settings

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Iterator

    from fastapi import FastAPI
    from opentelemetry.sdk.trace.export import SpanExporter
    from opentelemetry.trace import Span, Tracer
    from structlog.typing import EventDict, WrappedLogger

_CONFIGURED = False
"""Module-level guard so :func:`configure_tracing` is SnapStart-safe."""

_TRACER_NAME = "briefed"
"""Stable tracer name; do not change without coordinating dashboards."""


def configure_tracing(settings: Settings | None = None) -> None:
    """Initialize the global OTel ``TracerProvider``.

    Args:
        settings: Optional pre-resolved :class:`Settings`. When ``None``
            the cached :func:`get_settings` value is used. Tests pass a
            stubbed instance to avoid the SSM round-trip.
    """
    global _CONFIGURED  # noqa: PLW0603 — module-level guard, intentional.
    if _CONFIGURED:
        return

    cfg = settings or get_settings()
    resource = Resource.create(
        {
            SERVICE_NAME: f"briefed-{cfg.runtime}",
            "deployment.environment": cfg.env,
        },
    )
    provider = TracerProvider(resource=resource)
    exporter = _build_exporter(cfg)
    if exporter is not None:
        # Batch processor in prod / dev; console exporter (debug) gets a
        # SimpleSpanProcessor so spans flush before tests assert on them.
        processor: Any
        if isinstance(exporter, ConsoleSpanExporter):
            processor = SimpleSpanProcessor(exporter)
        else:
            processor = BatchSpanProcessor(exporter)
        provider.add_span_processor(processor)
    trace.set_tracer_provider(provider)
    _CONFIGURED = True


def _build_exporter(settings: Settings) -> SpanExporter | None:
    """Return the configured exporter, or ``None`` for the no-op path.

    Args:
        settings: Resolved settings.

    Returns:
        A concrete exporter, or ``None`` when ``settings.otel_exporter``
        equals ``"none"`` (tests + local default).
    """
    name = (settings.otel_exporter or "none").lower()
    if name == "none":
        return None
    if name == "console":
        return ConsoleSpanExporter()
    if name == "otlp":
        # Imported lazily so the OTLP gRPC dependency is optional in tests
        # and only landed in the Lambda image where the ADOT collector lives.
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (  # type: ignore[import-not-found, unused-ignore]  # noqa: PLC0415
            OTLPSpanExporter,
        )

        exporter: SpanExporter = OTLPSpanExporter()
        return exporter
    raise ValueError(f"unknown otel_exporter: {settings.otel_exporter!r}")


def get_tracer() -> Tracer:
    """Return the project tracer.

    Returns:
        The shared OTel tracer for the ``"briefed"`` namespace.
    """
    return trace.get_tracer(_TRACER_NAME)


def instrument_app(app: FastAPI) -> None:
    """Wire the OTel FastAPI middleware onto the given app.

    Args:
        app: The FastAPI instance returned by ``create_app``.
    """
    # Imported lazily because the FastAPI instrumentation pulls the full
    # ASGI stack into the cold-start bundle when imported at module level.
    from opentelemetry.instrumentation.fastapi import (  # noqa: PLC0415
        FastAPIInstrumentor,
    )

    FastAPIInstrumentor.instrument_app(app)


@contextmanager
def worker_span(name: str, **attributes: Any) -> Iterator[Span]:  # noqa: ANN401
    """Create a span around a worker handler invocation.

    ``**attributes`` is intentionally ``Any``: OTel span attributes accept
    str/int/float/bool/sequences thereof, mirroring its public surface.

    Args:
        name: Span name (typically ``"worker.<stage>"``).
        **attributes: Optional span attributes (account_id, run_id, …).

    Yields:
        The active span for inline annotation.
    """
    tracer = get_tracer()
    with tracer.start_as_current_span(name) as span:
        for key, value in attributes.items():
            if value is not None:
                span.set_attribute(key, value)
        yield span


def trace_context_processor(
    _logger: WrappedLogger,
    _name: str,
    event_dict: EventDict,
) -> EventDict:
    """Structlog processor that injects ``trace_id`` / ``span_id``.

    Registered by :func:`app.core.logging.configure` after this module is
    imported. The processor reads the *currently active* span (set by the
    FastAPI middleware or :func:`worker_span`) and decorates the event
    dict with hex-formatted IDs that match the OTel wire format.

    Args:
        _logger: Bound logger (unused; required by structlog signature).
        _name: Method name (unused).
        event_dict: Mutable event dict to enrich.

    Returns:
        The same ``event_dict``, with ``trace_id`` and ``span_id`` keys
        added when an active span exists.
    """
    span = trace.get_current_span()
    span_ctx = span.get_span_context() if span else None
    if span_ctx is None or not span_ctx.is_valid:
        return event_dict
    event_dict.setdefault("trace_id", f"{span_ctx.trace_id:032x}")
    event_dict.setdefault("span_id", f"{span_ctx.span_id:016x}")
    return event_dict


__all__ = [
    "configure_tracing",
    "get_tracer",
    "instrument_app",
    "trace_context_processor",
    "worker_span",
]
