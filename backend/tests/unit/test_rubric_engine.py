"""Unit tests for the rule engine (plan §14 Phase 2)."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime

import pytest

from app.db.models import KnownWasteSender, RubricRule
from app.domain.providers import EmailAddress, EmailMessage, UnsubscribeInfo
from app.services.classification.rubric import RuleEngine


def _email(
    *,
    subject: str = "hi",
    from_email: str = "sender@example.com",
    labels: tuple[str, ...] = (),
    list_unsub: bool = False,
) -> EmailMessage:
    return EmailMessage(
        account_id=uuid.uuid4(),
        message_id="m1",
        thread_id="t1",
        internal_date=datetime.now(tz=UTC),
        from_addr=EmailAddress(email=from_email),
        subject=subject,
        labels=labels,
        list_unsubscribe=(
            UnsubscribeInfo(http_urls=("https://example.com",)) if list_unsub else None
        ),
        content_hash=hashlib.sha256(b"x").digest(),
    )


def _rule(
    *,
    priority: int,
    match: dict[str, object],
    label: str,
    confidence: float = 0.9,
    version: int = 1,
) -> RubricRule:
    return RubricRule(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        priority=priority,
        match=match,
        action={"label": label, "confidence": confidence, "reasons": ["r"]},
        version=version,
        active=True,
    )


def test_returns_none_on_miss() -> None:
    engine = RuleEngine(user_rules=(), seed_waste=())
    assert engine.evaluate(_email()) is None


def test_higher_priority_wins() -> None:
    lower = _rule(priority=100, match={"from_email": "a@x.com"}, label="ignore")
    higher = _rule(priority=500, match={"from_email": "a@x.com"}, label="must_read")
    engine = RuleEngine(user_rules=(lower, higher), seed_waste=())
    result = engine.evaluate(_email(from_email="a@x.com"))
    assert result is not None
    assert result.label == "must_read"


def test_known_waste_seed_always_wins() -> None:
    seed = KnownWasteSender(
        id=uuid.uuid4(),
        match={"from_email": "spam@x.com"},
        added_by="seed",
        reason="spam",
    )
    user = _rule(priority=10, match={"from_email": "spam@x.com"}, label="must_read")
    engine = RuleEngine(user_rules=(user,), seed_waste=(seed,))
    result = engine.evaluate(_email(from_email="spam@x.com"))
    assert result is not None
    assert result.label == "waste"


def test_from_domain_matches_subdomain() -> None:
    rule = _rule(priority=10, match={"from_domain": "example.com"}, label="newsletter")
    engine = RuleEngine(user_rules=(rule,), seed_waste=())
    assert engine.evaluate(_email(from_email="news@mail.example.com")) is not None


def test_subject_regex_matches() -> None:
    rule = _rule(
        priority=10,
        match={"subject_regex": r"^\[ALERT\]"},
        label="must_read",
    )
    engine = RuleEngine(user_rules=(rule,), seed_waste=())
    assert engine.evaluate(_email(subject="[ALERT] fire"))  # hit
    assert engine.evaluate(_email(subject="nope")) is None


def test_invalid_regex_fails_predicate() -> None:
    rule = _rule(
        priority=10,
        match={"subject_regex": "("},  # unbalanced
        label="must_read",
    )
    engine = RuleEngine(user_rules=(rule,), seed_waste=())
    assert engine.evaluate(_email(subject="anything")) is None


def test_has_label_matches() -> None:
    rule = _rule(priority=10, match={"has_label": "IMPORTANT"}, label="must_read")
    engine = RuleEngine(user_rules=(rule,), seed_waste=())
    assert engine.evaluate(_email(labels=("IMPORTANT",))) is not None
    assert engine.evaluate(_email(labels=("INBOX",))) is None


def test_list_unsubscribe_predicate() -> None:
    rule = _rule(
        priority=10,
        match={"list_unsubscribe_present": True},
        label="newsletter",
    )
    engine = RuleEngine(user_rules=(rule,), seed_waste=())
    assert engine.evaluate(_email(list_unsub=True)) is not None
    assert engine.evaluate(_email(list_unsub=False)) is None


def test_unknown_match_key_raises() -> None:
    rule = _rule(priority=10, match={"something_bogus": 1}, label="must_read")
    engine = RuleEngine(user_rules=(rule,), seed_waste=())
    with pytest.raises(ValueError, match="unknown match keys"):
        engine.evaluate(_email())


def test_inactive_rule_skipped() -> None:
    rule = _rule(priority=10, match={"from_email": "a@x.com"}, label="must_read")
    rule.active = False
    engine = RuleEngine(user_rules=(rule,), seed_waste=())
    assert engine.evaluate(_email(from_email="a@x.com")) is None


def test_empty_match_never_matches() -> None:
    rule = _rule(priority=10, match={}, label="must_read")
    engine = RuleEngine(user_rules=(rule,), seed_waste=())
    # RubricRule validation would normally block this, but the engine
    # must still refuse blanket-match predicates.
    assert engine.evaluate(_email()) is None
