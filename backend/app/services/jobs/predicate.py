"""JSONB job-filter predicate evaluator (plan §14 Phase 4, §19.2).

Each row in ``job_filters`` carries a JSON predicate. This module
interprets that JSON against a :class:`JobCandidate` value object and
returns ``True`` / ``False``. The predicate shape is deliberately
narrow so the same document can be indexed on Postgres and evaluated
in-process by the worker without shipping Python into the DB.

Supported top-level keys (all optional; implicit AND across keys):

* ``min_comp`` — integer lower bound (inclusive). Row passes when its
  ``comp_max`` is present and ``>= min_comp`` (a row whose range tops
  out below the floor cannot be a match).
* ``max_comp`` — integer upper bound (inclusive). Row passes when its
  ``comp_min`` is present and ``<= max_comp``.
* ``currency`` — required ISO-4217 currency string. Row passes when
  its :attr:`JobCandidate.currency` equals this value (case-insensitive).
  When ``min_comp`` or ``max_comp`` is set, ``currency`` is effectively
  required — without it the row cannot be compared.
* ``remote_required`` — boolean. When ``True`` the row's ``remote`` must
  be ``True`` (``None`` fails). When ``False`` the clause is satisfied by
  ``remote in (False, None)`` — we treat ambiguous rows as candidates.
* ``location_any`` — list of strings. Row passes when any substring
  (case-insensitive) is contained in its :attr:`location`.
* ``location_none`` — list of strings. Row fails when any substring
  appears in its :attr:`location`.
* ``title_keywords_any`` — list of strings. Row passes when any
  substring appears in its :attr:`title` (case-insensitive). Empty /
  missing → no-op.
* ``title_keywords_none`` — list of strings. Row fails when any
  substring appears in its :attr:`title`.
* ``seniority_in`` — list of allowed seniority values. Row fails when
  its :attr:`seniority` is ``None`` or not in the list.
* ``min_confidence`` — float. Row passes when its :attr:`match_score`
  is ``>=`` this value.

Unknown keys raise :class:`PredicateError` — the evaluator refuses to
silently ignore a typo that would otherwise widen the filter.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

_ALLOWED_KEYS: frozenset[str] = frozenset(
    {
        "min_comp",
        "max_comp",
        "currency",
        "remote_required",
        "location_any",
        "location_none",
        "title_keywords_any",
        "title_keywords_none",
        "seniority_in",
        "min_confidence",
    },
)
"""Whitelist of predicate keys. Anything else raises."""


class PredicateError(ValueError):
    """Raised when a job-filter predicate is malformed."""


@dataclass(frozen=True)
class JobCandidate:
    """Plaintext projection the predicate evaluates against.

    All fields mirror :class:`app.db.models.JobMatch` columns except
    for ``match_reason`` which is never evaluated (it is encrypted).

    Attributes:
        title: Role title.
        company: Hiring company.
        location: Free-text location or ``None``.
        remote: Tri-state remote flag.
        comp_min: Lower compensation bound.
        comp_max: Upper compensation bound.
        currency: ISO-4217 code; ``None`` when comp is unset.
        seniority: Normalized tier string.
        match_score: Calibrated confidence.
    """

    title: str
    company: str
    location: str | None
    remote: bool | None
    comp_min: int | None
    comp_max: int | None
    currency: str | None
    seniority: str | None
    match_score: float


def evaluate(predicate: Mapping[str, Any], candidate: JobCandidate) -> bool:
    """Evaluate one predicate document against ``candidate``.

    An empty predicate returns ``True`` (vacuously satisfied). Unknown
    keys raise immediately; the engine refuses to widen a filter by
    dropping a clause it does not understand.

    Args:
        predicate: JSON-shaped predicate document.
        candidate: Row projection to test.

    Returns:
        ``True`` when every clause holds; ``False`` otherwise.

    Raises:
        PredicateError: When a clause references an unknown key or a
            value has the wrong shape.
    """
    _validate_keys(predicate)
    return all(_check_clause(key, value, candidate) for key, value in predicate.items())


def evaluate_many(
    filters: Iterable[Mapping[str, Any]],
    candidate: JobCandidate,
) -> bool:
    """Return ``True`` when ``candidate`` passes every predicate in ``filters``.

    The worker picks the set of active filters for a user and combines
    them with an implicit AND. An empty iterable returns ``True`` so a
    user with no configured filters sees every extracted row.

    Args:
        filters: Iterable of predicate documents.
        candidate: Row projection.

    Returns:
        Combined AND result.
    """
    return all(evaluate(predicate, candidate) for predicate in filters)


def _validate_keys(predicate: Mapping[str, Any]) -> None:
    """Raise when ``predicate`` references keys the engine does not support."""
    unknown = set(predicate) - _ALLOWED_KEYS
    if unknown:
        raise PredicateError(f"unknown predicate keys: {sorted(unknown)}")


def _check_clause(key: str, value: Any, candidate: JobCandidate) -> bool:
    """Dispatch one clause to its handler."""
    if key == "min_comp":
        return _check_min_comp(value, candidate)
    if key == "max_comp":
        return _check_max_comp(value, candidate)
    if key == "currency":
        return _check_currency(value, candidate)
    if key == "remote_required":
        return _check_remote(value, candidate)
    if key == "location_any":
        return _check_location_any(value, candidate)
    if key == "location_none":
        return _check_location_none(value, candidate)
    if key == "title_keywords_any":
        return _check_title_any(value, candidate)
    if key == "title_keywords_none":
        return _check_title_none(value, candidate)
    if key == "seniority_in":
        return _check_seniority_in(value, candidate)
    if key == "min_confidence":
        return _check_min_confidence(value, candidate)
    raise PredicateError(f"unhandled predicate key: {key!r}")


def _as_int(value: Any, *, field: str) -> int:
    """Coerce ``value`` to ``int`` or raise :class:`PredicateError`."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise PredicateError(f"{field} must be an int, got {type(value).__name__}")
    return int(value)


def _as_float(value: Any, *, field: str) -> float:
    """Coerce ``value`` to ``float`` or raise :class:`PredicateError`."""
    if isinstance(value, bool):
        raise PredicateError(f"{field} must be a number, got bool")
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, Decimal):
        return float(value)
    raise PredicateError(f"{field} must be a number, got {type(value).__name__}")


def _as_str_list(value: Any, *, field: str) -> list[str]:
    """Coerce ``value`` to a ``list[str]`` or raise."""
    if not isinstance(value, list):
        raise PredicateError(f"{field} must be a list of strings")
    out: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise PredicateError(f"{field} entries must be strings")
        stripped = item.strip()
        if stripped:
            out.append(stripped)
    return out


def _check_min_comp(value: Any, candidate: JobCandidate) -> bool:
    """Row passes when ``candidate.comp_max`` is ``>=`` the floor."""
    floor = _as_int(value, field="min_comp")
    if candidate.comp_max is None:
        return False
    return candidate.comp_max >= floor


def _check_max_comp(value: Any, candidate: JobCandidate) -> bool:
    """Row passes when ``candidate.comp_min`` is ``<=`` the ceiling."""
    ceiling = _as_int(value, field="max_comp")
    if candidate.comp_min is None:
        return False
    return candidate.comp_min <= ceiling


def _check_currency(value: Any, candidate: JobCandidate) -> bool:
    """Row passes when the currency matches (case-insensitive)."""
    if not isinstance(value, str):
        raise PredicateError("currency must be a string")
    expected = value.strip().upper()
    if not expected:
        raise PredicateError("currency must be non-empty")
    return candidate.currency is not None and candidate.currency.upper() == expected


def _check_remote(value: Any, candidate: JobCandidate) -> bool:
    """Enforce the tri-state remote rule described in the module docstring."""
    if not isinstance(value, bool):
        raise PredicateError("remote_required must be a bool")
    if value:
        return candidate.remote is True
    return candidate.remote in (False, None)


def _check_location_any(value: Any, candidate: JobCandidate) -> bool:
    """Row passes when any ``location_any`` substring is in the location."""
    needles = _as_str_list(value, field="location_any")
    if not needles:
        return True
    if not candidate.location:
        return False
    haystack = candidate.location.lower()
    return any(needle.lower() in haystack for needle in needles)


def _check_location_none(value: Any, candidate: JobCandidate) -> bool:
    """Row fails when any ``location_none`` substring is in the location."""
    needles = _as_str_list(value, field="location_none")
    if not needles:
        return True
    if not candidate.location:
        return True
    haystack = candidate.location.lower()
    return all(needle.lower() not in haystack for needle in needles)


def _check_title_any(value: Any, candidate: JobCandidate) -> bool:
    """Row passes when any keyword appears in the title."""
    needles = _as_str_list(value, field="title_keywords_any")
    if not needles:
        return True
    haystack = candidate.title.lower()
    return any(needle.lower() in haystack for needle in needles)


def _check_title_none(value: Any, candidate: JobCandidate) -> bool:
    """Row fails when any keyword appears in the title."""
    needles = _as_str_list(value, field="title_keywords_none")
    if not needles:
        return True
    haystack = candidate.title.lower()
    return all(needle.lower() not in haystack for needle in needles)


def _check_seniority_in(value: Any, candidate: JobCandidate) -> bool:
    """Row passes when the candidate's seniority is in the allow-list."""
    tiers = _as_str_list(value, field="seniority_in")
    if not tiers:
        raise PredicateError("seniority_in must be a non-empty list")
    if candidate.seniority is None:
        return False
    return candidate.seniority.lower() in {t.lower() for t in tiers}


def _check_min_confidence(value: Any, candidate: JobCandidate) -> bool:
    """Row passes when ``match_score`` meets the floor."""
    floor = _as_float(value, field="min_confidence")
    if not 0.0 <= floor <= 1.0:
        raise PredicateError("min_confidence must be in [0, 1]")
    return candidate.match_score >= floor


__all__ = [
    "JobCandidate",
    "PredicateError",
    "evaluate",
    "evaluate_many",
]
