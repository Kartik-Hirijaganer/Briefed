"""Unit tests for the rule engine (plan §14 Phase 2)."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.db.models import KnownWasteSender, RubricRule
from app.domain.providers import EmailAddress, EmailMessage, UnsubscribeInfo
from app.services.classification.rubric import (
    RuleEngine,
    default_rubric_seed,
    default_rubric_seed_path,
)


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
    assert result.label == "ignore"


def test_from_domain_matches_subdomain() -> None:
    rule = _rule(priority=10, match={"from_domain": "example.com"}, label="newsletter")
    engine = RuleEngine(user_rules=(rule,), seed_waste=())
    result = engine.evaluate(_email(from_email="news@mail.example.com"))
    assert result is not None
    assert result.label == "good_to_read"
    assert result.is_newsletter is True


def test_legacy_waste_label_maps_to_ignore() -> None:
    rule = _rule(priority=10, match={"from_email": "promo@example.com"}, label="waste")
    engine = RuleEngine(user_rules=(rule,), seed_waste=())
    result = engine.evaluate(_email(from_email="promo@example.com"))
    assert result is not None
    assert result.label == "ignore"


def test_subject_contains_matches_case_insensitive_substring() -> None:
    rule = _rule(priority=10, match={"subject_contains": "invoice"}, label="ignore")
    engine = RuleEngine(user_rules=(rule,), seed_waste=())
    assert engine.evaluate(_email(subject="Your Invoice Is Ready")) is not None
    assert engine.evaluate(_email(subject="status update")) is None


def test_topic_keyword_matches_subject_or_snippet() -> None:
    rule = _rule(
        priority=10,
        match={"topic_keyword": ["security alert", "verification code"]},
        label="must_read",
    )
    engine = RuleEngine(user_rules=(rule,), seed_waste=())
    assert engine.evaluate(_email(subject="Security alert for your account")) is not None
    assert engine.evaluate(_email(subject="weekly digest")) is None


def test_default_rubric_seed_loads_yaml() -> None:
    seeds = default_rubric_seed()
    names = {str(seed["name"]) for seed in seeds}

    assert "Gmail important" in names
    assert any(seed["match"] == {"subject_contains": "receipt"} for seed in seeds)


def test_default_rubric_seed_path_prefers_lambda_task_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lambda_seed_path = tmp_path / "packages" / "config" / "seeds" / "rubric_rules.yml"
    lambda_seed_path.parent.mkdir(parents=True)
    lambda_seed_path.write_text("rules: []\n", encoding="utf-8")
    monkeypatch.setenv("LAMBDA_TASK_ROOT", str(tmp_path))

    assert default_rubric_seed_path() == lambda_seed_path


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
