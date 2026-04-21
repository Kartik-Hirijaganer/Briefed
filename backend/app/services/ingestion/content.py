"""Encryption helpers for stored email body excerpts."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from app.core.content_crypto import content_context
from app.core.security import EncryptedBlob

if TYPE_CHECKING:  # pragma: no cover
    from app.core.security import EnvelopeCipher
    from app.db.models import EmailContentBlob


_PURPOSE = "email_body_excerpt"


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
    context = content_context(
        table="email_content_blobs",
        row_id=str(message_id),
        purpose=_PURPOSE,
        user_id=str(user_id),
    )
    return cipher.encrypt(encoded, context).ciphertext


def decrypt_excerpt(
    row: EmailContentBlob | None,
    *,
    user_id: UUID,
    cipher: EnvelopeCipher | None,
) -> str:
    """Return the plaintext excerpt for prompt rendering."""
    if row is None or not row.plain_text_excerpt_ct:
        return ""
    ciphertext = bytes(row.plain_text_excerpt_ct)
    if cipher is None:
        return ciphertext.decode("utf-8")
    context = content_context(
        table="email_content_blobs",
        row_id=str(row.message_id),
        purpose=_PURPOSE,
        user_id=str(user_id),
    )
    plaintext = cipher.decrypt(EncryptedBlob(ciphertext=ciphertext), context)
    return plaintext.decode("utf-8")


__all__ = ["decrypt_excerpt", "encrypt_excerpt"]
