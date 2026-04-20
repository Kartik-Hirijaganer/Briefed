"""Classification service — rules + LLM + persistence (plan §14 Phase 2).

Public API:

* :mod:`app.services.classification.rubric` — pure-functional rule
  engine over ``rubric_rules`` + ``known_waste_senders``.
* :mod:`app.services.classification.pipeline` — orchestration that
  first runs the rules, consults the LLM on misses, and writes a
  ``classifications`` row with cost telemetry.
* :mod:`app.services.classification.repository` — envelope-encrypted
  ``ClassificationsRepo`` (plan §20.10).
"""

from app.services.classification.pipeline import (
    ClassifyInputs,
    ClassifyOutcome,
    classify_one,
)
from app.services.classification.rubric import (
    MatchPredicate,
    RuleDecision,
    RuleEngine,
    RuleMatch,
    load_default_rules,
)

__all__ = [
    "ClassifyInputs",
    "ClassifyOutcome",
    "MatchPredicate",
    "RuleDecision",
    "RuleEngine",
    "RuleMatch",
    "classify_one",
    "load_default_rules",
]
