"""Summarization pipeline (plan §14 Phase 3).

Public entrypoints:

* :func:`app.services.summarization.relevant.summarize_email` — per-email
  summary for ``must_read`` / ``good_to_read`` / ``newsletter`` rows.
* :func:`app.services.summarization.tech_news.cluster_and_summarize` —
  newsletter clustering + group summary.
* :func:`app.services.summarization.dispatch.enqueue_unsummarized_for_run`
  — worker-edge helper that enqueues ``SummarizeMessage`` payloads for
  classified rows that still lack a :class:`app.db.models.Summary`.
"""

from app.services.summarization.batch import (
    BatchDriver,
    BatchProvider,
    BatchRequest,
    BatchResult,
    BatchSubmission,
    BatchTimeoutError,
    InMemoryBatchProvider,
    SyntheticBatchProvider,
    build_call_result,
)
from app.services.summarization.cluster_router import (
    ClusterRoute,
    ClusterRouter,
    load_default_router,
)
from app.services.summarization.dispatch import (
    enqueue_unsummarized_for_run,
    parse_summarize_body,
)
from app.services.summarization.relevant import (
    SummarizeInputs,
    SummarizeOutcome,
    summarize_email,
)
from app.services.summarization.repository import (
    SummariesRepo,
    SummaryEmailWrite,
    SummaryTechNewsWrite,
)
from app.services.summarization.tech_news import (
    TechNewsInputs,
    TechNewsOutcome,
    cluster_and_summarize,
)

__all__ = [
    "BatchDriver",
    "BatchProvider",
    "BatchRequest",
    "BatchResult",
    "BatchSubmission",
    "BatchTimeoutError",
    "ClusterRoute",
    "ClusterRouter",
    "InMemoryBatchProvider",
    "SummariesRepo",
    "SummarizeInputs",
    "SummarizeOutcome",
    "SummaryEmailWrite",
    "SummaryTechNewsWrite",
    "SyntheticBatchProvider",
    "TechNewsInputs",
    "TechNewsOutcome",
    "build_call_result",
    "cluster_and_summarize",
    "enqueue_unsummarized_for_run",
    "load_default_router",
    "parse_summarize_body",
    "summarize_email",
]
