"""Rule-engine over ``rubric_rules`` + ``known_waste_senders`` (plan §14 Phase 2).

Each rule is evaluated in descending ``priority`` order. The first rule
that matches every clause in its ``match`` dict wins, and its ``action``
dict produces a :class:`RuleDecision`. When no rule matches the caller
escalates to the LLM.

``known_waste_senders`` are treated as synthetic *highest-priority*
``ignore`` rules so new seed entries do not require a user-scoped copy.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select

from app.core.logging import get_logger
from app.core.yaml import YamlConfigError, safe_load_yaml_file
from app.db.models import KnownWasteSender, RubricRule

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Mapping
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
        "subject_contains",
        "subject_regex",
        "topic_keyword",
        "has_label",
        "list_unsubscribe_present",
        "header_equals",
    },
)
"""Whitelist of match keys the engine honors. Unknown keys raise."""


_LABEL_PRIORITY: dict[str, int] = {
    "must_read": 60,
    "good_to_read": 50,
    "ignore": 40,
}
"""Tie-breaker used when two rules match the same email; mirrors the
prompt contract."""


def default_rubric_seed_path() -> Path:
    """Return the packaged or repo-relative default rubric seed path.

    Returns:
        Absolute path to ``packages/config/seeds/rubric_rules.yml``.
    """
    raw_task_root = os.environ.get("LAMBDA_TASK_ROOT")
    if raw_task_root:
        lambda_path = Path(raw_task_root) / "packages" / "config" / "seeds" / "rubric_rules.yml"
        if lambda_path.exists():
            return lambda_path
    return (
        Path(__file__).resolve().parents[4] / "packages" / "config" / "seeds" / "rubric_rules.yml"
    )


class RubricSeedRule(BaseModel):
    """One default rubric rule loaded from YAML.

    ``match`` and ``action`` intentionally retain JSON ``Any`` leaves
    because rule-specific validators coerce and validate each supported
    predicate/action key at the engine boundary.

    Attributes:
        name: Human-readable rule name.
        priority: Rule priority; higher wins.
        match: Predicate dict consumed by :class:`RuleEngine`.
        action: Classification action dict consumed by :class:`RuleEngine`.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(..., min_length=1, max_length=120, description="Rule display name.")
    priority: int = Field(..., ge=0, le=100_000, description="Rule priority.")
    match: dict[str, Any] = Field(..., min_length=1, description="Rule match predicate.")
    action: dict[str, Any] = Field(..., description="Rule action payload.")


class RubricSeedConfig(BaseModel):
    """Default rubric seed file loaded from ``packages/config/seeds``.

    Attributes:
        rules: Ordered default rule definitions.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    rules: tuple[RubricSeedRule, ...] = Field(default=(), description="Default rules.")


@dataclass(frozen=True)
class RuleDecision:
    """Verdict produced by the rule engine (and consumed by the pipeline).

    Attributes:
        label: Triage bucket.
        confidence: Calibrated confidence in ``[0, 1]``.
        reasons: Human-readable bullets (persisted encrypted on the row).
        rubric_version: The winning rule's ``version``; ``0`` when the
            decision came from ``known_waste_senders``.
        is_newsletter: Independent newsletter flag.
        rule_id: Winning rule's id; ``None`` for synthetic-seed matches.
        source: Always ``"rule"`` from this module — classification
            pipeline promotes to ``hybrid`` if the LLM is also called.
    """

    label: str
    confidence: float
    reasons: tuple[str, ...]
    rubric_version: int
    rule_id: UUID | None = None
    is_newsletter: bool = False
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
                            label="ignore",
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
                label, is_newsletter = _normalize_action_label(
                    str(action.get("label") or "needs_review"),
                    bool(action.get("is_newsletter", False)),
                )
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
                            is_newsletter=is_newsletter,
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


def _normalize_action_label(
    label: str,
    is_newsletter: bool,
) -> tuple[str, bool]:
    """Normalize legacy pseudo-labels into primary label + flags.

    Older fixtures and seed data may still use ``newsletter`` or
    ``job_candidate`` as labels. New API writes should use primary labels,
    but normalizing here keeps historical rows from producing invalid
    downstream classifications.
    """
    if label == "newsletter":
        return "good_to_read", True
    if label == "job_candidate":
        return "good_to_read", is_newsletter
    if label == "waste":
        return "ignore", is_newsletter
    return label, is_newsletter


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
        "subject_contains": _check_subject_contains,
        "subject_regex": _check_subject_regex,
        "topic_keyword": _check_topic_keyword,
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


def _check_subject_contains(value: object, email: EmailMessage) -> bool:
    needle = str(value).strip().lower()
    if not needle:
        return False
    return needle in (email.subject or "").lower()


def _check_subject_regex(value: object, email: EmailMessage) -> bool:
    try:
        pattern = re.compile(str(value))
    except re.error:
        return False
    return pattern.search(email.subject or "") is not None


def _check_topic_keyword(value: object, email: EmailMessage) -> bool:
    values = value if isinstance(value, list | tuple) else (value,)
    haystack = f"{email.subject or ''}\n{email.snippet or ''}".lower()
    for item in values:
        needle = str(item).strip().lower()
        if needle and needle in haystack:
            return True
    return False


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


def default_rubric_seed(path: Path | None = None) -> tuple[dict[str, object], ...]:
    """Return the rule-set inserted for every freshly-provisioned user.

    Args:
        path: Optional YAML seed path override.

    Returns:
        Tuple of seed rule mappings with ``name``, ``priority``,
        ``match``, and ``action`` keys.

    Raises:
        ValueError: If the seed YAML is missing or malformed.
    """
    seed_path = path if path is not None else default_rubric_seed_path()
    try:
        config = RubricSeedConfig.model_validate(safe_load_yaml_file(seed_path))
    except (YamlConfigError, ValidationError) as exc:
        raise ValueError(f"invalid rubric seed config at {seed_path}") from exc
    return tuple(
        {
            "name": rule.name,
            "priority": rule.priority,
            "match": dict(rule.match),
            "action": dict(rule.action),
        }
        for rule in config.rules
    )


__all__ = [
    "MatchPredicate",
    "RuleDecision",
    "RuleEngine",
    "RuleMatch",
    "default_rubric_seed",
    "default_rubric_seed_path",
    "load_default_rules",
]
