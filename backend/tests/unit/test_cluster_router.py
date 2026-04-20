"""Unit tests for the newsletter cluster router (plan §14 Phase 3).

Covers the "cluster router deterministic for known List-IDs" exit
criterion, plus the fallback heuristic + precedence between user-added
and seed rules.
"""

from __future__ import annotations

import uuid

from app.db.models import KnownNewsletter
from app.services.summarization.cluster_router import ClusterRouter


def _rule(
    *,
    match: dict[str, object],
    cluster_key: str,
    topic_hint: str = "",
    maintainer: str = "seed",
) -> KnownNewsletter:
    return KnownNewsletter(
        id=uuid.uuid4(),
        match=match,
        cluster_key=cluster_key,
        topic_hint=topic_hint,
        maintainer=maintainer,
    )


def test_known_list_id_routes_deterministically() -> None:
    router = ClusterRouter(
        rules=(
            _rule(
                match={"list_id_equals": "llm-research.list-id.example"},
                cluster_key="llm-research",
                topic_hint="LLM research.",
            ),
        ),
    )

    first = router.route(
        from_addr="digest@example.com",
        subject="Weekly AI",
        list_id="<llm-research.list-id.example>",
    )
    second = router.route(
        from_addr="digest@example.com",
        subject="Different subject",
        list_id="LLM-Research.List-ID.Example",
    )
    assert first.cluster_key == "llm-research"
    assert first.topic_hint == "LLM research."
    assert first.cluster_key == second.cluster_key


def test_user_rule_wins_over_seed_rule() -> None:
    seed = _rule(
        match={"from_domain": "news.example"},
        cluster_key="seed-bucket",
        maintainer="seed",
    )
    user = _rule(
        match={"from_domain": "news.example"},
        cluster_key="user-bucket",
        maintainer="user:abc",
    )
    # load_default_router puts user rules first; simulate that order.
    router = ClusterRouter(rules=(user, seed))
    route = router.route(
        from_addr="weekly@news.example",
        subject="anything",
        list_id=None,
    )
    assert route.cluster_key == "user-bucket"


def test_subject_regex_participates_in_and_semantics() -> None:
    router = ClusterRouter(
        rules=(
            _rule(
                match={
                    "from_domain": "substack.com",
                    "subject_regex": r"(?i)weekly (ai|ml)",
                },
                cluster_key="ai-weekly",
            ),
        ),
    )
    match = router.route(
        from_addr="writer@substack.com",
        subject="Weekly ML — April",
        list_id=None,
    )
    miss = router.route(
        from_addr="writer@substack.com",
        subject="Random subject",
        list_id=None,
    )
    assert match.cluster_key == "ai-weekly"
    assert miss.cluster_key != "ai-weekly"


def test_fallback_slug_stable_across_runs() -> None:
    router = ClusterRouter(rules=())
    first = router.route(
        from_addr="Weekly@BigTech.Co.UK",
        subject="x",
        list_id=None,
    )
    second = router.route(
        from_addr="weekly@BIGTECH.co.uk",
        subject="y",
        list_id=None,
    )
    assert first.cluster_key == "bigtech"
    assert first.cluster_key == second.cluster_key


def test_fallback_returns_unsorted_for_malformed_sender() -> None:
    router = ClusterRouter(rules=())
    route = router.route(from_addr="", subject="x", list_id=None)
    assert route.cluster_key == "unsorted"
