"""100%-coverage tests for envelope crypto (plan §20.1)."""

from __future__ import annotations

from typing import Any

import pytest

from app.core.errors import CryptoError
from app.core.security import (
    EncryptedBlob,
    EncryptionContext,
    EnvelopeCipher,
    token_context,
)


class _FakeKms:
    """In-memory KMS stub that wraps DEKs with a one-time-pad XOR."""

    def __init__(self) -> None:
        self._master = b"M" * 32
        self.encrypt_calls: list[dict[str, Any]] = []
        self.decrypt_calls: list[dict[str, Any]] = []

    def encrypt(
        self,
        *,
        KeyId: str,
        Plaintext: bytes,
        EncryptionContext: dict[str, str],
    ) -> dict[str, Any]:
        self.encrypt_calls.append({"KeyId": KeyId, "EncryptionContext": dict(EncryptionContext)})
        wrapped = bytes(b ^ m for b, m in zip(Plaintext, self._master, strict=True))
        header = len(Plaintext).to_bytes(2, "big")
        context_blob = "|".join(f"{k}={v}" for k, v in sorted(EncryptionContext.items())).encode(
            "utf-8"
        )
        return {"CiphertextBlob": header + context_blob + b"::" + wrapped}

    def decrypt(
        self,
        *,
        CiphertextBlob: bytes,
        EncryptionContext: dict[str, str],
        KeyId: str | None = None,
    ) -> dict[str, Any]:
        self.decrypt_calls.append({"KeyId": KeyId, "EncryptionContext": dict(EncryptionContext)})
        length = int.from_bytes(CiphertextBlob[:2], "big")
        body = CiphertextBlob[2:]
        context_blob, wrapped = body.split(b"::", 1)
        expected = "|".join(f"{k}={v}" for k, v in sorted(EncryptionContext.items())).encode(
            "utf-8"
        )
        if context_blob != expected:
            msg = "context mismatch"
            raise RuntimeError(msg)
        plaintext = bytes(b ^ m for b, m in zip(wrapped, self._master, strict=True))
        assert len(plaintext) == length
        return {"Plaintext": plaintext}


def test_envelope_roundtrip_succeeds() -> None:
    kms = _FakeKms()
    cipher = EnvelopeCipher(key_id="alias/test", client=kms)
    ctx = EncryptionContext(fields={"account_id": "a", "purpose": "refresh"})

    blob = cipher.encrypt(b"super-secret-refresh-token", ctx)
    assert isinstance(blob, EncryptedBlob)
    assert len(blob.ciphertext) > 32
    # First byte is the version prefix
    assert blob.ciphertext[0] == 0x01

    assert cipher.decrypt(blob, ctx) == b"super-secret-refresh-token"
    # KMS was called exactly once each way with the matching context.
    assert len(kms.encrypt_calls) == 1
    assert len(kms.decrypt_calls) == 1
    assert kms.encrypt_calls[0]["EncryptionContext"] == {
        "account_id": "a",
        "purpose": "refresh",
    }


def test_empty_key_id_rejected() -> None:
    with pytest.raises(CryptoError):
        EnvelopeCipher(key_id="", client=_FakeKms())


def test_empty_plaintext_rejected() -> None:
    cipher = EnvelopeCipher(key_id="alias/test", client=_FakeKms())
    with pytest.raises(CryptoError):
        cipher.encrypt(b"", EncryptionContext())


def test_encrypt_raises_when_kms_fails() -> None:
    class _Bad:
        def encrypt(self, **_: Any) -> dict[str, Any]:
            raise RuntimeError("boom")

        def decrypt(self, **_: Any) -> dict[str, Any]:  # pragma: no cover
            raise AssertionError("unreachable")

    cipher = EnvelopeCipher(key_id="alias/test", client=_Bad())
    with pytest.raises(CryptoError):
        cipher.encrypt(b"payload", EncryptionContext())


def test_decrypt_rejects_short_blob() -> None:
    cipher = EnvelopeCipher(key_id="alias/test", client=_FakeKms())
    with pytest.raises(CryptoError):
        cipher.decrypt(EncryptedBlob(ciphertext=b"\x00"), EncryptionContext())


def test_decrypt_rejects_bad_version() -> None:
    cipher = EnvelopeCipher(key_id="alias/test", client=_FakeKms())
    blob = EncryptedBlob(ciphertext=b"\x99\x00\x01\x00\x0c" + b"\x00" * 40)
    with pytest.raises(CryptoError):
        cipher.decrypt(blob, EncryptionContext())


def test_decrypt_rejects_bad_nonce_len() -> None:
    cipher = EnvelopeCipher(key_id="alias/test", client=_FakeKms())
    # version=0x01, wrapped_len=1, nonce_len=8 (invalid)
    blob = EncryptedBlob(ciphertext=b"\x01\x00\x01\x00\x08" + b"\x00" * 20)
    with pytest.raises(CryptoError):
        cipher.decrypt(blob, EncryptionContext())


def test_decrypt_rejects_truncated_blob() -> None:
    cipher = EnvelopeCipher(key_id="alias/test", client=_FakeKms())
    # version=1, wrapped_len=32, nonce_len=12, but no payload bytes
    blob = EncryptedBlob(ciphertext=b"\x01\x00\x20\x00\x0c")
    with pytest.raises(CryptoError):
        cipher.decrypt(blob, EncryptionContext())


def test_decrypt_rejects_kms_failure() -> None:
    kms = _FakeKms()
    cipher = EnvelopeCipher(key_id="alias/test", client=kms)
    ctx = EncryptionContext(fields={"account_id": "a", "purpose": "refresh"})
    blob = cipher.encrypt(b"payload", ctx)

    # Decrypt with a mismatched context → KMS stub raises.
    other = EncryptionContext(fields={"account_id": "b", "purpose": "refresh"})
    with pytest.raises(CryptoError):
        cipher.decrypt(blob, other)


def test_decrypt_rejects_bad_dek_length() -> None:
    class _ShortDek:
        def encrypt(self, **_: Any) -> dict[str, Any]:  # pragma: no cover
            raise AssertionError("unused")

        def decrypt(self, **_: Any) -> dict[str, Any]:
            return {"Plaintext": b"too short"}

    cipher = EnvelopeCipher(key_id="alias/test", client=_ShortDek())
    blob = EncryptedBlob(
        ciphertext=b"\x01\x00\x20\x00\x0c" + b"\x00" * 32 + b"\x00" * 12 + b"\x00" * 20,
    )
    with pytest.raises(CryptoError):
        cipher.decrypt(blob, EncryptionContext())


def test_decrypt_rejects_bad_auth_tag() -> None:
    kms = _FakeKms()
    cipher = EnvelopeCipher(key_id="alias/test", client=kms)
    ctx = EncryptionContext(fields={"a": "b"})
    blob = cipher.encrypt(b"payload", ctx)
    # Flip one byte inside the ciphertext body so AES-GCM auth fails.
    tampered = bytearray(blob.ciphertext)
    tampered[-1] ^= 0xFF
    with pytest.raises(CryptoError):
        cipher.decrypt(EncryptedBlob(ciphertext=bytes(tampered)), ctx)


def test_token_context_fields() -> None:
    ctx = token_context(account_id="abc-123", purpose="access_token")
    assert ctx.as_kms_dict() == {
        "account_id": "abc-123",
        "purpose": "access_token",
    }


def test_key_id_property() -> None:
    cipher = EnvelopeCipher(key_id="alias/prod", client=_FakeKms())
    assert cipher.key_id == "alias/prod"


def test_encryption_context_copy_is_defensive() -> None:
    original = {"k": "v"}
    ctx = EncryptionContext(fields=original)
    as_dict = ctx.as_kms_dict()
    as_dict["k"] = "mutated"
    # Mutating the returned dict must not affect subsequent calls.
    assert ctx.as_kms_dict() == {"k": "v"}
