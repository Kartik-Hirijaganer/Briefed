"""``UnsubscribeSuggestionsRepo`` persistence boundary (plan §14 Phase 5, §20.10).

Reads + writes :class:`app.db.models.UnsubscribeSuggestion` rows with
transparent envelope encryption on ``rationale``. Aggregate metadata
(frequency, engagement, waste rate, ``list_unsubscribe`` target) stays
plaintext so the hygiene-stats endpoint can aggregate across the
table without round-tripping through KMS per row.

Upsert semantics: one row per ``(account_id, sender_email)``. Every
re-run of the aggregate replaces the numeric columns + rationale but
**preserves** ``dismissed`` + ``dismissed_at`` so a sender the user
silenced does not re-surface. Plan §19.7 retention cleanup hard-deletes
rows where ``dismissed AND dismissed_at < now() - interval '180 days'``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import select

from app.core.content_crypto import content_context
from app.core.logging import get_logger
from app.core.security import EncryptedBlob
from app.db.models import UnsubscribeSuggestion

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.core.security import EnvelopeCipher


logger = get_logger(__name__)

_PURPOSE = "unsubscribe_rationale"
"""Encryption-context purpose string for the rationale column."""


@dataclass(frozen=True)
class UnsubscribeSuggestionWrite:
    """Payload handed to :meth:`UnsubscribeSuggestionsRepo.upsert`.

    Attributes:
        account_id: Owning connected account. Upsert key component.
        user_id: Owner — bound into the encryption context so a row
            re-assigned to another owner becomes unreadable.
        sender_domain: Normalized sender domain.
        sender_email: Normalized full sender address. Upsert key
            component.
        frequency_30d: Last-30-day email count.
        engagement_score: Positive-label ratio in ``[0, 1]``.
        waste_rate: Waste/ignore ratio in ``[0, 1]``.
        list_unsubscribe: Normalized ``List-Unsubscribe`` dict from
            :class:`app.services.unsubscribe.parser.UnsubscribeAction`
            (or ``None`` when no email carried the header).
        confidence: Calibrated ``[0, 1]``.
        decision_source: ``rule`` or ``model``.
        rationale: Plaintext rationale — encrypted by the repo.
        prompt_version_id: FK into :class:`app.db.models.PromptVersion`;
            ``None`` for rule-only rows.
        model: Provider-scoped model identifier (empty for rule-only).
        tokens_in: Input tokens billed (0 for rule-only).
        tokens_out: Output tokens billed (0 for rule-only).
        last_email_at: UTC timestamp of the most recent email from
            this sender.
    """

    account_id: UUID
    user_id: UUID
    sender_domain: str
    sender_email: str
    frequency_30d: int
    engagement_score: Decimal
    waste_rate: Decimal
    list_unsubscribe: dict[str, Any] | None
    confidence: Decimal
    decision_source: str
    rationale: str
    prompt_version_id: UUID | None
    model: str
    tokens_in: int
    tokens_out: int
    last_email_at: datetime | None


class UnsubscribeSuggestionsRepo:
    """Encrypt-on-write / decrypt-on-read gateway for ``unsubscribe_suggestions``.

    Attributes:
        cipher: Injected :class:`EnvelopeCipher` bound to the content
            CMK (``alias/briefed-<env>-content-encrypt``). ``None``
            disables encryption (pass-through); used in tests and in
            the local dev runtime when no KMS alias is configured.
    """

    def __init__(self, *, cipher: EnvelopeCipher | None) -> None:
        """Store the cipher; ``None`` disables encryption.

        Args:
            cipher: The content envelope cipher, or ``None`` for a
                pass-through mode used by pure-SQLite unit tests.
        """
        self._cipher = cipher

    async def upsert(
        self,
        session: AsyncSession,
        payload: UnsubscribeSuggestionWrite,
    ) -> UnsubscribeSuggestion:
        """Insert or replace the row for ``(account_id, sender_email)``.

        ``dismissed`` + ``dismissed_at`` are **never overwritten** on
        replace — the user's prior dismissal survives every aggregate
        re-run (plan §7 recommend-only guarantee).

        Args:
            session: Active async session (caller owns commit).
            payload: :class:`UnsubscribeSuggestionWrite` with plaintext
                rationale.

        Returns:
            The attached :class:`UnsubscribeSuggestion` ORM row.
        """
        existing = (
            (
                await session.execute(
                    select(UnsubscribeSuggestion).where(
                        UnsubscribeSuggestion.account_id == payload.account_id,
                        UnsubscribeSuggestion.sender_email == payload.sender_email,
                    ),
                )
            )
            .scalars()
            .first()
        )
        if existing is None:
            existing = UnsubscribeSuggestion(
                account_id=payload.account_id,
                sender_email=payload.sender_email,
            )
            session.add(existing)

        existing.sender_domain = payload.sender_domain
        existing.frequency_30d = payload.frequency_30d
        existing.engagement_score = payload.engagement_score
        existing.waste_rate = payload.waste_rate
        existing.list_unsubscribe = payload.list_unsubscribe
        existing.confidence = payload.confidence
        existing.decision_source = payload.decision_source
        existing.prompt_version_id = payload.prompt_version_id
        existing.model = payload.model
        existing.tokens_in = payload.tokens_in
        existing.tokens_out = payload.tokens_out
        existing.last_email_at = payload.last_email_at
        existing.rationale_ct = self._encrypt_rationale(
            rationale=payload.rationale,
            account_id=payload.account_id,
            sender_email=payload.sender_email,
            user_id=payload.user_id,
        )

        await session.flush()
        return existing

    def decrypt_rationale(
        self,
        *,
        row: UnsubscribeSuggestion,
        user_id: UUID,
    ) -> str:
        r"""Reverse :meth:`_encrypt_rationale`.

        Args:
            row: ORM row with ``rationale_ct`` populated.
            user_id: Owner for encryption-context binding.

        Returns:
            Plaintext rationale. Empty string when the row never had
            one (pass-through ``b"\\x00"`` sentinel).
        """
        ciphertext = bytes(row.rationale_ct)
        if not ciphertext:
            return ""
        if self._cipher is None:
            return "" if ciphertext == b"\x00" else ciphertext.decode("utf-8")
        ctx = content_context(
            table="unsubscribe_suggestions",
            row_id=f"{row.account_id}:{row.sender_email}",
            purpose=_PURPOSE,
            user_id=str(user_id),
        )
        plaintext = self._cipher.decrypt(EncryptedBlob(ciphertext=ciphertext), ctx)
        return "" if plaintext == b"\x00" else plaintext.decode("utf-8")

    def _encrypt_rationale(
        self,
        *,
        rationale: str,
        account_id: UUID,
        sender_email: str,
        user_id: UUID,
    ) -> bytes:
        """Envelope-encrypt the plaintext rationale.

        Args:
            rationale: Plaintext rationale.
            account_id: Bound into the encryption context.
            sender_email: Bound into the encryption context.
            user_id: Bound into the encryption context.

        Returns:
            Ciphertext bytes (or the UTF-8 plaintext when no cipher is
            configured — tests only).
        """
        data = rationale.encode("utf-8")
        if not data:
            data = b"\x00"
        if self._cipher is None:
            return data
        ctx = content_context(
            table="unsubscribe_suggestions",
            row_id=f"{account_id}:{sender_email}",
            purpose=_PURPOSE,
            user_id=str(user_id),
        )
        return self._cipher.encrypt(data, ctx).ciphertext


__all__ = ["UnsubscribeSuggestionWrite", "UnsubscribeSuggestionsRepo"]
