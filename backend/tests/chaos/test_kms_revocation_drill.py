"""Chaos drill — KMS revocation (plan §20.6, §20.10 Phase 8).

Plan exit criterion: "revoke ``kms:Decrypt`` on the app role → assert
tokens become unreadable → restore → assert recovery." We model the
revocation by swapping the boto3 client for one that raises a
``KMS.AccessDeniedException`` analogue; the cipher must surface a
:class:`CryptoError` and the application layer must not silently
return plaintext.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.core.errors import CryptoError
from app.core.security import EncryptionContext, EnvelopeCipher

pytestmark = pytest.mark.chaos


class _AccessDeniedError(Exception):
    """Stand-in for ``botocore.exceptions.ClientError`` AccessDeniedException."""


class _StubKms:
    """Tiny KMS double that round-trips DEKs without crypto."""

    def __init__(self) -> None:
        self.revoked = False

    def encrypt(
        self,
        *,
        KeyId: str,
        Plaintext: bytes,
        EncryptionContext: dict[str, str],
    ) -> dict[str, Any]:
        if self.revoked:
            raise _AccessDeniedError("AccessDeniedException")
        # Pack KeyId + context + plaintext into the ciphertext blob so a
        # later Decrypt can verify the binding.
        marker = repr((KeyId, sorted(EncryptionContext.items()))).encode()
        return {"CiphertextBlob": b"|" + marker + b"|" + Plaintext}

    def decrypt(
        self,
        *,
        CiphertextBlob: bytes,
        EncryptionContext: dict[str, str],
        KeyId: str | None = None,
    ) -> dict[str, Any]:
        if self.revoked:
            raise _AccessDeniedError("AccessDeniedException")
        # Mirror real KMS: the stored context (encoded into the blob)
        # must match what the caller supplies, otherwise reject.
        marker_end = CiphertextBlob.index(b"|", 1)
        marker = CiphertextBlob[1:marker_end]
        stored_repr = marker.decode()
        encoded_ctx = repr((KeyId, sorted(EncryptionContext.items())))
        if encoded_ctx != stored_repr:
            raise _AccessDeniedError("InvalidCiphertextException")
        plaintext = CiphertextBlob[marker_end + 1 :]
        return {"Plaintext": plaintext}


def test_revocation_breaks_decrypt_then_restoration_recovers() -> None:
    kms = _StubKms()
    cipher = EnvelopeCipher(key_id="alias/briefed-test-content", client=kms)
    ctx = EncryptionContext(fields={"user_id": "u-1", "purpose": "content"})

    blob = cipher.encrypt(b"sensitive-summary", ctx)
    assert cipher.decrypt(blob, ctx) == b"sensitive-summary"

    # Simulate IAM revoking kms:Decrypt — every read fails.
    kms.revoked = True
    with pytest.raises(CryptoError):
        cipher.decrypt(blob, ctx)

    # Restoration: grant returns, reads succeed again with the same blob.
    kms.revoked = False
    assert cipher.decrypt(blob, ctx) == b"sensitive-summary"


def test_context_mismatch_refuses_decrypt() -> None:
    """KMS rejects a Decrypt whose context differs (§20.10)."""
    kms = _StubKms()
    cipher = EnvelopeCipher(key_id="alias/briefed-test-content", client=kms)
    blob = cipher.encrypt(
        b"row-1-content",
        EncryptionContext(fields={"user_id": "u-1", "table": "summaries", "row_id": "1"}),
    )
    # Same key, different row — must not decrypt.
    with pytest.raises(CryptoError):
        cipher.decrypt(
            blob,
            EncryptionContext(
                fields={"user_id": "u-1", "table": "summaries", "row_id": "2"},
            ),
        )
