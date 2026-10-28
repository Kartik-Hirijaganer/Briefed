"""Unit tests for :mod:`app.core.content_crypto` (plan §20.10)."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from app.core.content_crypto import content_context
from app.core.errors import CryptoError
from app.core.security import EnvelopeCipher
from app.db.models import EmailContentBlob
from app.services.ingestion.content import decrypt_excerpt, encrypt_excerpt


class _FakeKms:
    def encrypt(
        self,
        *,
        KeyId: str,
        Plaintext: bytes,
        EncryptionContext: dict[str, str],
    ) -> dict[str, object]:
        return {"CiphertextBlob": b"F:" + Plaintext}

    def decrypt(
        self,
        *,
        CiphertextBlob: bytes,
        EncryptionContext: dict[str, str],
        KeyId: str | None = None,
    ) -> dict[str, object]:
        return {"Plaintext": CiphertextBlob[2:]}


class _ContextCheckingKms:
    """KMS stub that, like real KMS, refuses a Decrypt under a different context."""

    def __init__(self) -> None:
        self._wrapped: dict[bytes, tuple[bytes, dict[str, str]]] = {}

    def encrypt(
        self,
        *,
        KeyId: str,
        Plaintext: bytes,
        EncryptionContext: dict[str, str],
    ) -> dict[str, object]:
        handle = f"W{len(self._wrapped):04d}".encode()
        self._wrapped[handle] = (Plaintext, dict(EncryptionContext))
        return {"CiphertextBlob": handle}

    def decrypt(
        self,
        *,
        CiphertextBlob: bytes,
        EncryptionContext: dict[str, str],
        KeyId: str | None = None,
    ) -> dict[str, object]:
        dek, context = self._wrapped[bytes(CiphertextBlob)]
        if context != EncryptionContext:
            raise RuntimeError("InvalidCiphertextException")
        return {"Plaintext": dek}


def _legacy_unbound_excerpt(cipher: EnvelopeCipher, *, user_id: UUID) -> bytes:
    """Encrypt the way ingest did before it assigned ``Email.id`` up front."""
    context = content_context(
        table="email_content_blobs",
        row_id="None",
        purpose="email_body_excerpt",
        user_id=str(user_id),
    )
    return cipher.encrypt(b"legacy", context).ciphertext


def test_context_binds_table_and_row() -> None:
    ctx = content_context(
        table="classifications",
        row_id="abc-123",
        purpose="classifications_reasons",
    )
    assert ctx.as_kms_dict() == {
        "table": "classifications",
        "row_id": "abc-123",
        "purpose": "classifications_reasons",
    }


def test_context_includes_user_when_supplied() -> None:
    ctx = content_context(
        table="summaries",
        row_id="x",
        purpose="summaries_body",
        user_id="u-1",
    )
    assert ctx.as_kms_dict()["user_id"] == "u-1"


def test_context_mutation_is_isolated() -> None:
    ctx = content_context(
        table="t",
        row_id="r",
        purpose="p",
    )
    first = ctx.as_kms_dict()
    first["table"] = "mutated"
    assert ctx.as_kms_dict()["table"] == "t"


def test_email_excerpt_helpers_pass_through_without_cipher() -> None:
    message_id = uuid4()
    user_id = uuid4()
    ciphertext = encrypt_excerpt(
        "hello",
        message_id=message_id,
        user_id=user_id,
        cipher=None,
    )
    row = EmailContentBlob(message_id=message_id, plain_text_excerpt_ct=ciphertext)
    assert decrypt_excerpt(row, user_id=user_id, cipher=None) == "hello"


def test_email_excerpt_helpers_encrypt_with_content_cipher() -> None:
    message_id = uuid4()
    user_id = uuid4()
    cipher = EnvelopeCipher(key_id="alias/content", client=_FakeKms())
    ciphertext = encrypt_excerpt(
        "secret",
        message_id=message_id,
        user_id=user_id,
        cipher=cipher,
    )
    assert ciphertext is not None
    assert b"secret" not in ciphertext
    row = EmailContentBlob(message_id=message_id, plain_text_excerpt_ct=ciphertext)
    assert decrypt_excerpt(row, user_id=user_id, cipher=cipher) == "secret"


def test_email_excerpt_decrypt_refuses_another_rows_context() -> None:
    user_id = uuid4()
    cipher = EnvelopeCipher(key_id="alias/content", client=_ContextCheckingKms())
    ciphertext = encrypt_excerpt("secret", message_id=uuid4(), user_id=user_id, cipher=cipher)
    row = EmailContentBlob(message_id=uuid4(), plain_text_excerpt_ct=ciphertext)
    with pytest.raises(CryptoError):
        decrypt_excerpt(row, user_id=user_id, cipher=cipher)


def test_email_excerpt_decrypt_reads_legacy_unbound_rows() -> None:
    user_id = uuid4()
    cipher = EnvelopeCipher(key_id="alias/content", client=_ContextCheckingKms())
    row = EmailContentBlob(
        message_id=uuid4(),
        plain_text_excerpt_ct=_legacy_unbound_excerpt(cipher, user_id=user_id),
    )
    assert decrypt_excerpt(row, user_id=user_id, cipher=cipher) == "legacy"


def test_email_excerpt_legacy_fallback_still_binds_owner() -> None:
    cipher = EnvelopeCipher(key_id="alias/content", client=_ContextCheckingKms())
    row = EmailContentBlob(
        message_id=uuid4(),
        plain_text_excerpt_ct=_legacy_unbound_excerpt(cipher, user_id=uuid4()),
    )
    with pytest.raises(CryptoError):
        decrypt_excerpt(row, user_id=uuid4(), cipher=cipher)


def test_email_excerpt_helpers_treat_empty_as_absent() -> None:
    assert encrypt_excerpt("", message_id=uuid4(), user_id=uuid4(), cipher=None) is None
    assert decrypt_excerpt(None, user_id=uuid4(), cipher=None) == ""
