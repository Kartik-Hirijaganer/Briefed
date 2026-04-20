"""Job-extraction service (plan §14 Phase 4).

Public entrypoints:

* :func:`app.services.jobs.extractor.extract_job` — per-email
  LLM extraction + salary corroboration + filter evaluation + persist.
* :func:`app.services.jobs.dispatch.enqueue_unextracted_for_account`
  — worker-edge helper that enqueues :class:`JobExtractMessage`
  payloads for classified ``job_candidate`` rows that still lack a
  :class:`app.db.models.JobMatch`.
* :mod:`app.services.jobs.predicate` — pure-functional JSONB
  predicate engine used by the extractor and by the digest composer
  (Phase 6+) to answer "which rows pass the user's filters right now?".
* :class:`app.services.jobs.repository.JobMatchesRepo` — encrypt-on-
  write persistence boundary for ``job_matches.match_reason``.
"""

from app.services.jobs.dispatch import (
    enqueue_unextracted_for_account,
    parse_job_extract_body,
)
from app.services.jobs.extractor import (
    ExtractInputs,
    ExtractOutcome,
    corroborate_comp,
    extract_job,
)
from app.services.jobs.predicate import (
    JobCandidate,
    PredicateError,
    evaluate,
    evaluate_many,
)
from app.services.jobs.repository import (
    JobMatchesRepo,
    JobMatchWrite,
)

__all__ = [
    "ExtractInputs",
    "ExtractOutcome",
    "JobCandidate",
    "JobMatchWrite",
    "JobMatchesRepo",
    "PredicateError",
    "corroborate_comp",
    "enqueue_unextracted_for_account",
    "evaluate",
    "evaluate_many",
    "extract_job",
    "parse_job_extract_body",
]
