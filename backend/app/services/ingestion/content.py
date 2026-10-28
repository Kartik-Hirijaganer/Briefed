"""Encryption helpers for stored email body excerpts."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from app.core.content_crypto import content_context
from app.core.errors import CryptoError
from app.core.security import EncryptedBlob, EncryptionContext

if TYPE_CHECKING:  # pragma: no cover
    from app.core.security import EnvelopeCipher
    from app.db.models import EmailContentBlob


_PURPOSE = "email_body_excerpt"

_LEGACY_UNBOUND_ROW_ID = "None"
"""``row_id`` bound into excerpts that ingest encrypted before ``Email.id`` existed.

Ingest used to build the ORM row without an id (the default only fires at
flush), so those excerpts carry ``row_id="None"``. Decrypt retries with it
so they stay readable; they remain bound to their owner's ``user_id``.
"""


def _excerpt_context(*, row_id: str, user_id: UUID) -> EncryptionContext:
    """Build the KMS encryption context for one excerpt.

    Args:
        row_id: ``email_content_blobs.message_id`` in string form.
        user_id: Owner of the email.

    Returns:
        Context bound into the excerpt's envelope.
    """
    return content_context(
        table="email_content_blobs",
        row_id=row_id,
        purpose=_PURPOSE,
        user_id=str(user_id),
    )


def encrypt_excerpt(
    plaintext: str,
    *,
    message_id: UUID,
    user_id: UUID,
    cipher: EnvelopeCipher | None,
) -> bytes | None:
    """Return ciphertext for ``email_content_blobs.plain_text_excerpt_ct``.

    With no cipher configured, tests keep using UTF-8 plaintext bytes so
    pipeline tests do not need KMS. Empty excerpts are represented as
    ``NULL`` because the prompt consumers already fall back to snippets.
    """
    if not plaintext:
        return None
    encoded = plaintext.encode("utf-8")
    if cipher is None:
        return encoded
    context = _excerpt_context(row_id=str(message_id), user_id=user_id)
    return cipher.encrypt(encoded, context).ciphertext


def decrypt_excerpt(
    row: EmailContentBlob | None,
    *,
    user_id: UUID,
    cipher: EnvelopeCipher | None,
) -> str:
    """Return the plaintext excerpt for prompt rendering.

    Falls back to the legacy ``row_id="None"`` context when the row-bound
    context is refused, so excerpts written before the fix stay readable.

    Raises:
        CryptoError: If neither context decrypts the excerpt.
    """
    if row is None or not row.plain_text_excerpt_ct:
        return ""
    ciphertext = bytes(row.plain_text_excerpt_ct)
    if cipher is None:
        return ciphertext.decode("utf-8")
    blob = EncryptedBlob(ciphertext=ciphertext)
    try:
        plaintext = cipher.decrypt(
            blob,
            _excerpt_context(row_id=str(row.message_id), user_id=user_id),
        )
    except CryptoError:
        plaintext = cipher.decrypt(
            blob,
            _excerpt_context(row_id=_LEGACY_UNBOUND_ROW_ID, user_id=user_id),
        )
    return plaintext.decode("utf-8")


__all__ = ["decrypt_excerpt", "encrypt_excerpt"]
