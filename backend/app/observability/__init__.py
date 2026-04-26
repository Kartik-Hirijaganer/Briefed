"""Observability primitives (plan §14 Phase 3 + Phase 8).

CloudWatch EMF metrics + structlog conveniences live here. Phase 3
ships :mod:`app.observability.metrics` with the
summarization-focused counters the dashboards + SNS alarms expect:

* ``summarize.cache_hit`` — 0/1 per call so the dashboard can render
  the rolling ratio.
* ``summarize.cost_usd`` — per-call cost; sums feed the daily budget.
* ``summarize.tokens_in`` / ``summarize.tokens_out`` — raw counters.
* ``summarize.batch_submitted`` / ``summarize.batch_completed`` /
  ``summarize.batch_failed`` — batch job lifecycle.

The emitter prints the EMF payload via structlog in every runtime so
local dev + CI still see the numbers. In Lambda, CloudWatch Logs
picks up the EMF block automatically (no boto call required).
"""

from app.observability.metrics import (
    MetricUnit,
    emit_batch_lifecycle_metric,
    emit_metric,
    emit_summarize_cluster_metric,
    emit_summarize_email_metric,
)

__all__ = [
    "MetricUnit",
    "emit_batch_lifecycle_metric",
    "emit_metric",
    "emit_summarize_cluster_metric",
    "emit_summarize_email_metric",
]
