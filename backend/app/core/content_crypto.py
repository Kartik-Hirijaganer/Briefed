"""Content-at-rest envelope encryption (plan §20.10).

Separate from :mod:`app.core.security` (which handles OAuth tokens)
because the two use **different** KMS CMKs with different IAM grants
and different rotation cadences:

* ``alias/briefed-<env>-token-wrap``     — OAuth token wrap key.
* ``alias/briefed-<env>-content-encrypt`` — content-at-rest wrap key.

Each encrypted row is packed identically to
:class:`app.core.security.EnvelopeCipher` — a version-prefixed,
length-delimited blob — so both modules share the same header format
and tests.

``content_context(...)`` is the canonical helper for building encryption
contexts. The row's ``{table, row_id, purpose}`` are bound into the KMS
Encrypt/Decrypt call so an attacker cannot swap ciphertexts between
rows. Purposes in use today:

* ``classifications_reasons`` (Phase 2).
* ``summaries_body`` (Phase 3).
* ``email_body_excerpt`` (Phase 3).
* ``job_match_reason`` (Phase 4).
"""

from __future__ import annotations

from app.core.security import EncryptionContext


def content_context(
    *,
    table: str,
    row_id: str,
    purpose: str,
    user_id: str | None = None,
) -> EncryptionContext:
    """Build the encryption context for a content-at-rest envelope.

    Args:
        table: Destination table (``classifications``, ``summaries``,
            ``email_content_blobs``, ``job_matches``).
        row_id: Primary key of the target row (string form).
        purpose: Column-level discriminator (e.g.
            ``classifications_reasons``). Pick a stable string —
            changing it makes old ciphertexts undecryptable.
        user_id: Optional owner scope. When supplied the binding is even
            tighter — decrypt refuses a row re-assigned to another
            owner.

    Returns:
        An :class:`EncryptionContext` to pass to :class:`app.core.security.EnvelopeCipher`.
    """
    fields: dict[str, str] = {
        "table": table,
        "row_id": row_id,
        "purpose": purpose,
    }
    if user_id is not None:
        fields["user_id"] = user_id
    return EncryptionContext(fields=fields)


__all__ = ["content_context"]
