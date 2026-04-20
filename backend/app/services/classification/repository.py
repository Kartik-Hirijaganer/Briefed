"""Classification persistence boundary (plan §20.10).

Reads + writes ``classifications`` rows with transparent envelope
encryption on the ``reasons`` payload. Service-layer code stays
plaintext; the encrypt/decrypt round-trip happens here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select

from app.core.content_crypto import content_context
from app.core.logging import get_logger
from app.core.security import EncryptedBlob
from app.db.models import Classification

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.core.security import EnvelopeCipher


logger = get_logger(__name__)

_PURPOSE = "classifications_reasons"
"""Encryption-context purpose string for ``classifications.reasons``."""


@dataclass(frozen=True)
class ClassificationWrite:
    """Payload the pipeline hands the repo on persist.

    Attributes:
        email_id: Target email.
        label: Final triage bucket.
        score: Confidence in ``[0, 1]``.
        rubric_version: Plumbed through from the winning rule.
        prompt_version_id: Non-``None`` when the LLM was consulted.
        decision_source: ``rule`` / ``model`` / ``hybrid``.
        model: Model identifier (empty for rule-only).
        tokens_in: Tokens billed (0 for rule-only).
        tokens_out: Tokens billed.
        reasons: Plaintext JSON-serializable rationale payload.
        user_id: Owner id — bound into the encryption context so
            re-assigning the row to another owner makes the ciphertext
            unreadable.
    """

    email_id: UUID
    label: str
    score: Decimal
    rubric_version: int
    prompt_version_id: UUID | None
    decision_source: str
    model: str
    tokens_in: int
    tokens_out: int
    reasons: dict[str, object]
    user_id: UUID


class ClassificationsRepo:
    """Encrypt-on-write / decrypt-on-read gateway.

    Attributes:
        cipher: Injected :class:`EnvelopeCipher` bound to the content
            CMK (``alias/briefed-<env>-content-encrypt``).
    """

    def __init__(self, *, cipher: EnvelopeCipher | None) -> None:
        """Store the cipher; ``None`` disables encryption (tests).

        Args:
            cipher: The content envelope cipher, or ``None`` for a
                pass-through mode used by pure-SQLite unit tests.
        """
        self._cipher = cipher

    async def upsert(
        self,
        session: AsyncSession,
        payload: ClassificationWrite,
    ) -> Classification:
        """Insert or replace the ``classifications`` row for ``email_id``.

        Args:
            session: Active async session (caller owns commit).
            payload: :class:`ClassificationWrite` with plaintext reasons.

        Returns:
            The attached :class:`Classification` ORM row (reasons still
            encrypted).
        """
        existing = (
            (
                await session.execute(
                    select(Classification).where(
                        Classification.email_id == payload.email_id,
                    ),
                )
            )
            .scalars()
            .first()
        )
        if existing is None:
            existing = Classification(email_id=payload.email_id)
            session.add(existing)

        existing.label = payload.label
        existing.score = payload.score
        existing.rubric_version = payload.rubric_version
        existing.prompt_version_id = payload.prompt_version_id
        existing.decision_source = payload.decision_source
        existing.model = payload.model
        existing.tokens_in = payload.tokens_in
        existing.tokens_out = payload.tokens_out

        ciphertext = self._encrypt_reasons(
            reasons=payload.reasons,
            email_id=payload.email_id,
            user_id=payload.user_id,
        )
        existing.reasons_ct = ciphertext
        existing.reasons_dek_wrapped = None

        await session.flush()
        return existing

    def _encrypt_reasons(
        self,
        *,
        reasons: dict[str, object],
        email_id: UUID,
        user_id: UUID,
    ) -> bytes | None:
        """Envelope-encrypt the JSON reasons payload.

        Args:
            reasons: Plaintext dict.
            email_id: FK bound into the encryption context.
            user_id: Owner bound into the encryption context.

        Returns:
            Ciphertext bytes, or the JSON utf-8 plaintext when no
            cipher is configured (tests).
        """
        plaintext = json.dumps(reasons, separators=(",", ":")).encode("utf-8")
        if self._cipher is None:
            return plaintext
        ctx = content_context(
            table="classifications",
            row_id=str(email_id),
            purpose=_PURPOSE,
            user_id=str(user_id),
        )
        blob = self._cipher.encrypt(plaintext, ctx)
        return blob.ciphertext

    def decrypt_reasons(
        self,
        *,
        row: Classification,
        user_id: UUID,
    ) -> dict[str, object]:
        """Reverse :meth:`_encrypt_reasons`.

        Args:
            row: ORM row with ``reasons_ct`` populated.
            user_id: Owner for context binding.

        Returns:
            The plaintext reasons dict. Empty dict if the row never
            carried a rationale.
        """
        if row.reasons_ct is None:
            return {}
        if self._cipher is None:
            parsed = json.loads(row.reasons_ct.decode("utf-8"))
        else:
            ctx = content_context(
                table="classifications",
                row_id=str(row.email_id),
                purpose=_PURPOSE,
                user_id=str(user_id),
            )
            plaintext = self._cipher.decrypt(EncryptedBlob(ciphertext=bytes(row.reasons_ct)), ctx)
            parsed = json.loads(plaintext.decode("utf-8"))
        if not isinstance(parsed, dict):
            raise ValueError("classifications.reasons must decode to a JSON object")
        return dict(parsed)


__all__ = ["ClassificationWrite", "ClassificationsRepo"]
