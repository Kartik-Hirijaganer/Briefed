"""Unsubscribe + inbox-hygiene service (plan §14 Phase 5).

Public entrypoints:

* :func:`parse_list_unsubscribe` — lenient RFC 2369 / RFC 8058 parser
  for raw ``List-Unsubscribe`` headers. Handles mailto, https, and the
  one-click signal.
* :class:`UnsubscribeAction` — structured parser output ready to hand
  to the UI as an action URL.
* :func:`aggregate_sender_stats` — SQL aggregate over
  ``emails`` x ``classifications`` (last 30 days) that produces one
  :class:`SenderStats` per (account, sender_email).
* :func:`score_sender` — maps :class:`SenderStats` to the three
  binary criteria (volume, waste-rate, disengagement) + a
  deterministic base confidence.
* :func:`rank_senders` — end-to-end orchestrator: aggregate → score
  → borderline LLM → upsert. Called from the worker handler.
* :class:`UnsubscribeSuggestionsRepo` — upsert-on-write persistence
  for :class:`app.db.models.UnsubscribeSuggestion`. Preserves a
  user's ``dismissed`` flag across re-runs so recommendations never
  un-dismiss themselves.
* :func:`enqueue_hygiene_run_for_account` — worker-edge helper that
  enqueues an :class:`app.workers.messages.UnsubscribeMessage`.
* :func:`parse_unsubscribe_body` — SQS body validator.
"""

from app.services.unsubscribe.aggregator import (
    SenderStats,
    aggregate_sender_stats,
    rank_senders,
    score_sender,
)
from app.services.unsubscribe.dispatch import (
    enqueue_hygiene_run_for_account,
    parse_unsubscribe_body,
)
from app.services.unsubscribe.parser import (
    UnsubscribeAction,
    parse_list_unsubscribe,
)
from app.services.unsubscribe.repository import (
    UnsubscribeSuggestionsRepo,
    UnsubscribeSuggestionWrite,
)

__all__ = [
    "SenderStats",
    "UnsubscribeAction",
    "UnsubscribeSuggestionWrite",
    "UnsubscribeSuggestionsRepo",
    "aggregate_sender_stats",
    "enqueue_hygiene_run_for_account",
    "parse_list_unsubscribe",
    "parse_unsubscribe_body",
    "rank_senders",
    "score_sender",
]
