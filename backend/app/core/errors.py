"""Domain-level exceptions (plan §9).

Every raisable error outside :mod:`app.integrations` derives from
:class:`BriefedError`. The API layer maps subclasses to HTTP status
codes; workers map them to retryable/non-retryable outcomes.
"""

from __future__ import annotations


class BriefedError(Exception):
    """Base class for all Briefed domain errors."""


class AuthError(BriefedError):
    """Authentication / authorization failure (401 / 403 at the API layer)."""


class NotFoundError(BriefedError):
    """A requested resource does not exist (404 at the API layer)."""


class ConflictError(BriefedError):
    """A requested change conflicts with existing state (409 at the API layer)."""


class QuotaExceededError(BriefedError):
    """The caller hit an upstream rate-limit (retryable with backoff)."""


class StaleCursorError(BriefedError):
    """Provider rejected a sync cursor (ingestion falls back to bounded scan)."""


class ProviderError(BriefedError):
    """Upstream provider returned an unrecoverable error."""


class CryptoError(BriefedError):
    """Envelope crypto / KMS wrap-unwrap failure."""
