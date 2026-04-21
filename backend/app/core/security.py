"""Envelope encryption for OAuth tokens (plan §20.3).

Every OAuth refresh token is stored in ``oauth_tokens`` as an envelope
ciphertext:

1. A 256-bit data-encryption key (DEK) is generated per write.
2. The plaintext is AES-GCM-encrypted under that DEK.
3. The DEK is wrapped by the customer-managed KMS CMK
   (``alias/${env}-token-wrap``) via ``kms:Encrypt`` with an
   :class:`EncryptionContext` binding that rejects cross-row reuse.
4. The wrapped DEK plus the ciphertext + nonce + auth-tag are packed
   into a single ``BYTEA`` blob with a one-byte version prefix.

The wrap-key material **never** leaves AWS KMS — every unwrap is a
``kms:Decrypt`` call logged in CloudTrail. Revoking the app role's
``kms:Decrypt`` IAM grant instantly bricks all token reads.

This module is listed in plan §20.1 as one of the five 100%-coverage
targets. Tests in :mod:`backend.tests.unit.test_security` cover every
branch.
"""

from __future__ import annotations

import os
import struct
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.errors import CryptoError

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Mapping


_VERSION_BYTE = 0x01
"""Version prefix on every envelope blob; bumps when the layout changes."""

_NONCE_LEN = 12
"""AES-GCM nonce length in bytes."""

_DEK_LEN = 32
"""Size of the per-row data-encryption key in bytes (AES-256)."""

_HEADER_STRUCT = struct.Struct(">BH H")
"""Header layout: ``version (u8)``, ``wrapped_dek_len (u16)``, ``nonce_len (u16)``."""


@dataclass(frozen=True)
class EncryptionContext:
    """Key-value context bound into KMS Encrypt/Decrypt calls.

    KMS rejects a Decrypt whose context differs from the Encrypt context;
    this is how we stop an attacker swapping ciphertexts between rows
    (plan §20.10). Keys + values must be printable strings.

    Attributes:
        fields: Mapping baked into the KMS call.
    """

    fields: Mapping[str, str] = field(default_factory=dict)

    def as_kms_dict(self) -> dict[str, str]:
        """Return a plain ``dict`` suitable for boto3 keyword arguments.

        Returns:
            Shallow copy of the context. The copy guards against callers
            mutating the underlying mapping after the Encrypt call.
        """
        return dict(self.fields)


@dataclass(frozen=True)
class EncryptedBlob:
    """Packed envelope ciphertext ready for a ``BYTEA`` column.

    Attributes:
        ciphertext: The opaque blob written to the DB.
    """

    ciphertext: bytes


class KmsClient(Protocol):
    """Structural typing for the subset of boto3's KMS client we rely on."""

    def encrypt(
        self,
        *,
        KeyId: str,
        Plaintext: bytes,
        EncryptionContext: dict[str, str],
    ) -> dict[str, Any]:
        """Wrap ``Plaintext`` with ``KeyId`` + ``EncryptionContext``."""
        ...  # pragma: no cover

    def decrypt(
        self,
        *,
        CiphertextBlob: bytes,
        EncryptionContext: dict[str, str],
        KeyId: str | None = None,
    ) -> dict[str, Any]:
        """Unwrap ``CiphertextBlob`` under ``EncryptionContext``."""
        ...  # pragma: no cover


class EnvelopeCipher:
    """Encrypt + decrypt small values with per-row DEKs wrapped by KMS.

    The cipher is stateless apart from the KMS client; instantiate once at
    module import time so the Lambda warm window amortises client init.

    Args:
        key_id: KMS CMK alias or ARN (e.g. ``alias/briefed-dev-token-wrap``).
        client: Pre-built boto3 KMS client. Injectable for tests.
    """

    def __init__(self, *, key_id: str, client: KmsClient) -> None:
        """Store the key id + client. No network call at construction time."""
        if not key_id:
            raise CryptoError("EnvelopeCipher requires a non-empty key_id")
        self._key_id = key_id
        self._client = client

    @property
    def key_id(self) -> str:
        """Return the configured KMS CMK identifier."""
        return self._key_id

    def encrypt(self, plaintext: bytes, context: EncryptionContext) -> EncryptedBlob:
        """Encrypt ``plaintext`` and return a packed :class:`EncryptedBlob`.

        Args:
            plaintext: Raw bytes to encrypt (must be non-empty).
            context: Encryption context bound into the KMS Encrypt call;
                the same context is required to decrypt.

        Returns:
            A packed envelope blob suitable for persistence.

        Raises:
            CryptoError: If the KMS wrap fails or the plaintext is empty.
        """
        if not plaintext:
            raise CryptoError("plaintext must be non-empty")

        dek = os.urandom(_DEK_LEN)
        nonce = os.urandom(_NONCE_LEN)
        aesgcm = AESGCM(dek)
        ciphertext = aesgcm.encrypt(nonce, plaintext, None)

        try:
            wrapped = self._client.encrypt(
                KeyId=self._key_id,
                Plaintext=dek,
                EncryptionContext=context.as_kms_dict(),
            )
        except Exception as exc:  # pragma: no cover — boto raises subclasses
            raise CryptoError(f"KMS Encrypt failed: {exc}") from exc

        wrapped_dek = bytes(wrapped["CiphertextBlob"])
        header = _HEADER_STRUCT.pack(_VERSION_BYTE, len(wrapped_dek), len(nonce))
        return EncryptedBlob(ciphertext=header + wrapped_dek + nonce + ciphertext)

    def decrypt(self, blob: EncryptedBlob, context: EncryptionContext) -> bytes:
        """Reverse :meth:`encrypt` — returns the original plaintext.

        Args:
            blob: The envelope blob produced by :meth:`encrypt`.
            context: Same :class:`EncryptionContext` supplied at encrypt
                time; KMS will refuse a Decrypt with a different context.

        Returns:
            The original plaintext bytes.

        Raises:
            CryptoError: If the blob is malformed, KMS refuses the unwrap,
                or the authenticated decrypt fails.
        """
        packed = blob.ciphertext
        if len(packed) < _HEADER_STRUCT.size:
            raise CryptoError("envelope blob too short to contain a header")

        version, wrapped_len, nonce_len = _HEADER_STRUCT.unpack_from(packed, 0)
        if version != _VERSION_BYTE:
            raise CryptoError(f"unsupported envelope version: {version}")
        if nonce_len != _NONCE_LEN:
            raise CryptoError(f"unexpected nonce length: {nonce_len}")

        offset = _HEADER_STRUCT.size
        wrapped_dek = packed[offset : offset + wrapped_len]
        offset += wrapped_len
        nonce = packed[offset : offset + nonce_len]
        offset += nonce_len
        ciphertext = packed[offset:]

        if len(wrapped_dek) != wrapped_len or len(nonce) != nonce_len or not ciphertext:
            raise CryptoError("envelope blob is truncated")

        try:
            unwrapped = self._client.decrypt(
                CiphertextBlob=wrapped_dek,
                EncryptionContext=context.as_kms_dict(),
                KeyId=self._key_id,
            )
        except Exception as exc:
            raise CryptoError(f"KMS Decrypt failed: {exc}") from exc

        dek = bytes(unwrapped["Plaintext"])
        if len(dek) != _DEK_LEN:
            raise CryptoError("KMS returned an unexpected DEK length")

        try:
            return AESGCM(dek).decrypt(nonce, ciphertext, None)
        except InvalidTag as exc:
            raise CryptoError("AES-GCM authentication failed") from exc


def token_context(*, account_id: str, purpose: str) -> EncryptionContext:
    """Build the encryption context used by OAuth-token envelopes.

    Args:
        account_id: ``connected_accounts.id`` (string form).
        purpose: ``"access_token"`` or ``"refresh_token"``.

    Returns:
        An :class:`EncryptionContext` suitable for :meth:`EnvelopeCipher.encrypt`.
    """
    return EncryptionContext(fields={"account_id": account_id, "purpose": purpose})
