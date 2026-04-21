"""Unit tests for :mod:`app.core.content_crypto` (plan §20.10)."""

from __future__ import annotations

from uuid import uuid4

from app.core.content_crypto import content_context
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


def test_email_excerpt_helpers_treat_empty_as_absent() -> None:
    assert encrypt_excerpt("", message_id=uuid4(), user_id=uuid4(), cipher=None) is None
    assert decrypt_excerpt(None, user_id=uuid4(), cipher=None) == ""
