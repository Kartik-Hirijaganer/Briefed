"""Rule-engine over ``rubric_rules`` + ``known_waste_senders`` (plan §14 Phase 2).

Each rule is evaluated in descending ``priority`` order. The first rule
that matches every clause in its ``match`` dict wins, and its ``action``
dict produces a :class:`RuleDecision`. When no rule matches the caller
escalates to the LLM.

``known_waste_senders`` are treated as synthetic *highest-priority*
rules so new seed entries do not require a user-scoped copy.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from sqlalchemy import select

from app.core.logging import get_logger
from app.db.models import KnownWasteSender, RubricRule

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Iterable, Mapping
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

    from app.domain.providers import EmailMessage


_Handler = Callable[[object, "EmailMessage"], bool]
"""Signature every predicate helper implements."""


logger = get_logger(__name__)


MatchPredicate = dict[str, Any]
"""Shape of ``rubric_rules.match`` and ``known_waste_senders.match``."""


_ALLOWED_MATCH_KEYS = frozenset(
    {
        "from_domain",
        "from_email",
        "subject_regex",
        "has_label",
        "list_unsubscribe_present",
        "header_equals",
    },
)
"""Whitelist of match keys the engine honors. Unknown keys raise."""


_LABEL_PRIORITY: dict[str, int] = {
    "waste": 100,
    "job_candidate": 80,
    "newsletter": 70,
    "must_read": 60,
    "good_to_read": 50,
    "ignore": 40,
    "needs_review": 10,
}
"""Tie-breaker used when two rules match the same email; mirrors the
prompt contract."""


@dataclass(frozen=True)
class RuleDecision:
    """Verdict produced by the rule engine (and consumed by the pipeline).

    Attributes:
        label: Triage bucket.
        confidence: Calibrated confidence in ``[0, 1]``.
        reasons: Human-readable bullets (persisted encrypted on the row).
        rubric_version: The winning rule's ``version``; ``0`` when the
            decision came from ``known_waste_senders``.
        rule_id: Winning rule's id; ``None`` for synthetic-seed matches.
        source: Always ``"rule"`` from this module — classification
            pipeline promotes to ``hybrid`` if the LLM is also called.
    """

    label: str
    confidence: float
    reasons: tuple[str, ...]
    rubric_version: int
    rule_id: UUID | None
    source: Literal["rule"] = "rule"


@dataclass(frozen=True)
class RuleMatch:
    """Internal pre-decision record.

    Attributes:
        decision: The :class:`RuleDecision`.
        priority: Rule priority — higher wins across conflicting matches.
    """

    decision: RuleDecision
    priority: int


class RuleEngine:
    """Pure-functional rule matcher.

    Construct with a frozen snapshot of rules + seed waste senders. The
    ``evaluate(...)`` method is synchronous + side-effect-free so it
    can be reused from the eval harness.
    """

    def __init__(
        self,
        *,
        user_rules: tuple[RubricRule, ...],
        seed_waste: tuple[KnownWasteSender, ...],
    ) -> None:
        """Capture the rule snapshot.

        Args:
            user_rules: Snapshot from ``rubric_rules`` filtered to
                ``active=true`` for the target user.
            seed_waste: Snapshot from ``known_waste_senders`` (global).
        """
        self._user_rules = user_rules
        self._seed_waste = seed_waste

    def evaluate(self, email: EmailMessage) -> RuleDecision | None:
        """Match ``email`` against the configured rules.

        Args:
            email: Parsed :class:`EmailMessage` boundary object.

        Returns:
            A :class:`RuleDecision` when any rule matches; ``None`` when
            the LLM should be consulted.
        """
        candidates: list[RuleMatch] = []

        for seed in self._seed_waste:
            match = seed.match
            if _match_predicate(match, email):
                candidates.append(
                    RuleMatch(
                        decision=RuleDecision(
                            label="waste",
                            confidence=0.98,
                            reasons=(f"seed:{seed.reason or 'known-waste-sender'}",),
                            rubric_version=0,
                            rule_id=None,
                        ),
                        priority=10_000,
                    ),
                )

        for rule in self._user_rules:
            if not rule.active:
                continue
            match = rule.match
            _validate_match_keys(match, source=str(rule.id))
            if _match_predicate(match, email):
                action = rule.action or {}
                label = str(action.get("label") or "needs_review")
                confidence = float(action.get("confidence", 0.9))
                reasons_list = action.get("reasons") or []
                reasons: tuple[str, ...] = tuple(str(r) for r in reasons_list)
                candidates.append(
                    RuleMatch(
                        decision=RuleDecision(
                            label=label,
                            confidence=confidence,
                            reasons=reasons or (f"rule:{rule.id}",),
                            rubric_version=rule.version,
                            rule_id=rule.id,
                        ),
                        priority=rule.priority,
                    ),
                )

        if not candidates:
            return None

        winner = max(
            candidates,
            key=lambda m: (m.priority, _LABEL_PRIORITY.get(m.decision.label, 0)),
        )
        return winner.decision


def _validate_match_keys(match: Mapping[str, Any], *, source: str) -> None:
    """Raise if ``match`` references keys the engine does not support.

    Args:
        match: Raw ``match`` dict from a rule / seed entry.
        source: Identifier for the error message.

    Raises:
        ValueError: On unknown keys.
    """
    unknown = set(match) - _ALLOWED_MATCH_KEYS
    if unknown:
        raise ValueError(f"rubric {source} uses unknown match keys: {sorted(unknown)}")


def _match_predicate(match: Mapping[str, Any], email: EmailMessage) -> bool:
    """Return ``True`` when every clause in ``match`` holds for ``email``.

    Empty predicates are rejected to avoid a blanket "always match"
    footgun.

    Args:
        match: Predicate dict.
        email: Parsed :class:`EmailMessage`.

    Returns:
        Boolean match result.
    """
    if not match:
        return False
    return all(_check_clause(key, value, email) for key, value in match.items())


def _check_clause(key: str, value: object, email: EmailMessage) -> bool:
    """Evaluate one predicate clause.

    Args:
        key: Clause name (must be in :data:`_ALLOWED_MATCH_KEYS`).
        value: Raw right-hand side from the rule.
        email: Parsed :class:`EmailMessage`.

    Returns:
        ``True`` when the clause matches.
    """
    handlers: dict[str, _Handler] = {
        "from_domain": _check_from_domain,
        "from_email": _check_from_email,
        "subject_regex": _check_subject_regex,
        "has_label": _check_has_label,
        "list_unsubscribe_present": _check_list_unsubscribe_present,
        "header_equals": _check_header_equals,
    }
    handler = handlers.get(key)
    if handler is None:
        return False
    return handler(value, email)


def _check_from_domain(value: object, email: EmailMessage) -> bool:
    domain = str(value).lower()
    sender = email.from_addr.email.lower()
    if "@" not in sender:
        return False
    if sender.endswith("@" + domain) or sender.endswith("." + domain):
        return True
    return sender == domain


def _check_from_email(value: object, email: EmailMessage) -> bool:
    return email.from_addr.email.lower() == str(value).lower()


def _check_subject_regex(value: object, email: EmailMessage) -> bool:
    try:
        pattern = re.compile(str(value))
    except re.error:
        return False
    return pattern.search(email.subject or "") is not None


def _check_has_label(value: object, email: EmailMessage) -> bool:
    return str(value) in set(email.labels)


def _check_list_unsubscribe_present(value: object, email: EmailMessage) -> bool:
    return bool(value) == (email.list_unsubscribe is not None)


def _check_header_equals(value: object, email: EmailMessage) -> bool:
    if not isinstance(value, dict):
        return False
    # The boundary model does not carry raw headers; only a subset is
    # inferable from what the parser lifted out (labels, list-unsub).
    for header_name, expected in value.items():
        name = header_name.lower()
        if name == "list-unsubscribe":
            if bool(expected) != (email.list_unsubscribe is not None):
                return False
            continue
        if name == "precedence" and str(expected).lower() == "bulk":
            labels = set(email.labels)
            if "LIST" not in labels and "Precedence:bulk" not in labels:
                return False
            continue
        return False
    return True


async def load_default_rules(
    session: AsyncSession,
    *,
    user_id: UUID,
) -> RuleEngine:
    """Load the active rule + seed snapshot for ``user_id``.

    Args:
        session: Active async session.
        user_id: Target user.

    Returns:
        A populated :class:`RuleEngine`.
    """
    rules = (
        (
            await session.execute(
                select(RubricRule)
                .where(RubricRule.user_id == user_id, RubricRule.active.is_(True))
                .order_by(RubricRule.priority.desc()),
            )
        )
        .scalars()
        .all()
    )
    seeds = (await session.execute(select(KnownWasteSender))).scalars().all()
    return RuleEngine(user_rules=tuple(rules), seed_waste=tuple(seeds))


def default_rubric_seed() -> Iterable[MatchPredicate]:
    """Return the rule-set inserted for every freshly-provisioned user.

    The seed captures "obvious" rules we don't want every user to
    reinvent. Each tuple is ``(priority, match, action)``.
    """
    return (
        # Boss / "direct mention" heuristics go in Phase 3 once we have
        # contact-graph data. Phase 2 seeds only the unambiguous rules.
        {
            "priority": 800,
            "match": {"has_label": "IMPORTANT"},
            "action": {
                "label": "must_read",
                "confidence": 0.9,
                "reasons": ["Gmail marked this as important."],
            },
        },
        {
            "priority": 200,
            "match": {"list_unsubscribe_present": True},
            "action": {
                "label": "newsletter",
                "confidence": 0.75,
                "reasons": ["List-Unsubscribe header present."],
            },
        },
    )


__all__ = [
    "MatchPredicate",
    "RuleDecision",
    "RuleEngine",
    "RuleMatch",
    "default_rubric_seed",
    "load_default_rules",
]
