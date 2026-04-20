"""CloudWatch EMF metric emitter (plan §14 Phase 3 + Phase 8).

Uses the `Embedded Metric Format <https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch_Embedded_Metric_Format_Specification.html>`_
so CloudWatch Logs extracts metrics automatically. That keeps the
Lambda hot path free of boto3 PutMetricData calls and costs nothing
beyond the existing log-group ingestion.

For Phase 3 we emit:

* ``Summarize/Email`` — one payload per per-email summary.
* ``Summarize/Cluster`` — one payload per tech-news cluster summary.
* ``Summarize/Batch`` — one payload per Batch API lifecycle transition
  (``submitted`` / ``completed`` / ``failed``).

Every payload carries the ``Environment`` + ``Runtime`` dimensions so
the dashboard can slice dev vs prod and api vs worker.

The emitter is sync + dependency-free. Tests assert the JSON shape.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from app.core.config import get_settings
from app.core.logging import get_logger

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Mapping


logger = get_logger(__name__)

_NAMESPACE = "Briefed"
"""CloudWatch namespace for every Briefed metric."""


class MetricUnit(StrEnum):
    """CloudWatch unit enum mirror."""

    COUNT = "Count"
    MILLISECONDS = "Milliseconds"
    BYTES = "Bytes"
    SECONDS = "Seconds"
    NONE = "None"


@dataclass(frozen=True)
class _MetricEntry:
    """One metric inside an EMF payload."""

    name: str
    unit: MetricUnit


def emit_metric(
    *,
    metric_set: str,
    values: Mapping[str, tuple[float, MetricUnit]],
    properties: Mapping[str, Any] | None = None,
) -> None:
    """Emit one EMF log line to stdout via structlog.

    Args:
        metric_set: Logical metric group (``Summarize/Email`` etc.).
            Becomes the EMF ``_aws.CloudWatchMetrics[].Namespace`` tail.
        values: Mapping of ``metric_name → (value, unit)``.
        properties: Extra properties (dimensions + diagnostics) to
            emit alongside the metrics.
    """
    settings = get_settings()
    base_props: dict[str, Any] = {
        "Environment": settings.env,
        "Runtime": settings.runtime,
    }
    if properties:
        base_props.update(properties)

    metric_definitions = [
        {"Name": name, "Unit": unit.value} for name, (_value, unit) in values.items()
    ]
    emf: dict[str, Any] = {
        "_aws": {
            "Timestamp": 0,  # CloudWatch fills this on ingest when absent.
            "CloudWatchMetrics": [
                {
                    "Namespace": f"{_NAMESPACE}/{metric_set}",
                    "Dimensions": [["Environment", "Runtime"]],
                    "Metrics": metric_definitions,
                },
            ],
        },
        **base_props,
        **{name: _coerce(value) for name, (value, _unit) in values.items()},
    }
    logger.info("metric", emf=emf)


def emit_summarize_email_metric(
    *,
    ok: bool,
    confidence: float,
    cache_hit: bool,
    tokens_in: int,
    tokens_out: int,
    cost_usd: Decimal,
    fallback_used: bool,
    batch: bool,
) -> None:
    """Emit ``Summarize/Email`` metrics for one per-email summary."""
    emit_metric(
        metric_set="Summarize/Email",
        values={
            "OK": (1.0 if ok else 0.0, MetricUnit.COUNT),
            "CacheHit": (1.0 if cache_hit else 0.0, MetricUnit.COUNT),
            "FallbackUsed": (1.0 if fallback_used else 0.0, MetricUnit.COUNT),
            "TokensIn": (float(tokens_in), MetricUnit.COUNT),
            "TokensOut": (float(tokens_out), MetricUnit.COUNT),
            "CostUsd": (float(cost_usd), MetricUnit.NONE),
            "Confidence": (float(confidence), MetricUnit.NONE),
        },
        properties={
            "Mode": "batch" if batch else "sync",
        },
    )


def emit_summarize_cluster_metric(
    *,
    clusters_created: int,
    clusters_summarized: int,
    clusters_failed: int,
    tokens_in: int,
    tokens_out: int,
    cost_usd: Decimal,
    cache_hits: int,
) -> None:
    """Emit ``Summarize/Cluster`` metrics for one clustering run."""
    emit_metric(
        metric_set="Summarize/Cluster",
        values={
            "ClustersCreated": (float(clusters_created), MetricUnit.COUNT),
            "ClustersSummarized": (float(clusters_summarized), MetricUnit.COUNT),
            "ClustersFailed": (float(clusters_failed), MetricUnit.COUNT),
            "CacheHits": (float(cache_hits), MetricUnit.COUNT),
            "TokensIn": (float(tokens_in), MetricUnit.COUNT),
            "TokensOut": (float(tokens_out), MetricUnit.COUNT),
            "CostUsd": (float(cost_usd), MetricUnit.NONE),
        },
    )


def emit_batch_lifecycle_metric(
    *,
    phase: str,
    requests: int,
    succeeded: int,
    failed: int,
    provider: str,
) -> None:
    """Emit ``Summarize/Batch`` metrics for one batch lifecycle event.

    Args:
        phase: ``submitted`` / ``completed`` / ``failed``.
        requests: Count of individual requests in the batch.
        succeeded: Count of successful responses (``0`` on submit).
        failed: Count of failed responses (``0`` on submit).
        provider: Provider slug (``gemini`` / ``anthropic_direct``).
    """
    emit_metric(
        metric_set="Summarize/Batch",
        values={
            "Requests": (float(requests), MetricUnit.COUNT),
            "Succeeded": (float(succeeded), MetricUnit.COUNT),
            "Failed": (float(failed), MetricUnit.COUNT),
        },
        properties={"Phase": phase, "Provider": provider},
    )


def _coerce(value: float) -> float:
    """Normalize metric values to floats JSON can serialize."""
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


# Silence unused-import lint when json isn't referenced by callsites.
_ = json


__all__ = [
    "MetricUnit",
    "emit_batch_lifecycle_metric",
    "emit_metric",
    "emit_summarize_cluster_metric",
    "emit_summarize_email_metric",
]
