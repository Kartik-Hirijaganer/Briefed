"""``JobMatchesRepo`` persistence boundary (plan §14 Phase 4, §20.10).

Reads + writes ``job_matches`` rows with transparent envelope
encryption on :attr:`app.db.models.JobMatch.match_reason`. Metadata
columns (title, company, comp bounds, seniority) stay plaintext so
:mod:`app.services.jobs.predicate` can evaluate filters without
round-tripping through KMS per row.

One row per source email. Re-extraction replaces the row in place so
``filter_version`` + ``passed_filter`` stay fresh.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select

from app.core.content_crypto import content_context
from app.core.logging import get_logger
from app.core.security import EncryptedBlob
from app.db.models import JobMatch

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.core.security import EnvelopeCipher


logger = get_logger(__name__)

_PURPOSE = "job_match_reason"
"""Encryption-context purpose string for ``job_matches.match_reason``."""


@dataclass(frozen=True)
class JobMatchWrite:
    """Payload the extractor hands the repo on persist.

    Attributes:
        email_id: Source email (1:1).
        user_id: Owner — bound into the encryption context so
            re-assigning the row to another user makes the ciphertext
            unreadable.
        title: Role title.
        company: Hiring company.
        location: Free-text location or ``None``.
        remote: Tri-state remote flag.
        comp_min: Lower compensation bound.
        comp_max: Upper compensation bound.
        currency: ISO-4217 code.
        comp_phrase: Verbatim salary phrase (audit + corroboration).
        seniority: Normalized tier.
        source_url: Apply / posting URL.
        match_score: Calibrated ``[0, 1]``.
        filter_version: Snapshot of the active job-filter version set.
        passed_filter: Filter outcome at write time.
        prompt_version_id: FK into :class:`PromptVersion`; ``None`` for
            hand-imported rows.
        model: Provider-scoped model identifier.
        tokens_in: Input tokens billed.
        tokens_out: Output tokens billed.
        match_reason: Plaintext rationale — encrypted by the repo.
    """

    email_id: UUID
    user_id: UUID
    title: str
    company: str
    location: str | None
    remote: bool | None
    comp_min: int | None
    comp_max: int | None
    currency: str | None
    comp_phrase: str | None
    seniority: str | None
    source_url: str | None
    match_score: Decimal
    filter_version: int
    passed_filter: bool
    prompt_version_id: UUID | None
    model: str
    tokens_in: int
    tokens_out: int
    match_reason: str


class JobMatchesRepo:
    """Encrypt-on-write / decrypt-on-read gateway for ``job_matches``.

    Attributes:
        cipher: Injected :class:`EnvelopeCipher` bound to the content
            CMK (``alias/briefed-<env>-content-encrypt``). ``None`` in
            tests disables encryption (pass-through).
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
        payload: JobMatchWrite,
    ) -> JobMatch:
        """Insert or replace the ``job_matches`` row for ``email_id``.

        Args:
            session: Active async session (caller owns commit).
            payload: :class:`JobMatchWrite` with plaintext fields.

        Returns:
            The attached :class:`JobMatch` ORM row (ciphertext column
            populated).
        """
        existing = (
            (
                await session.execute(
                    select(JobMatch).where(JobMatch.email_id == payload.email_id),
                )
            )
            .scalars()
            .first()
        )
        if existing is None:
            existing = JobMatch(email_id=payload.email_id)
            session.add(existing)

        existing.title = payload.title
        existing.company = payload.company
        existing.location = payload.location
        existing.remote = payload.remote
        existing.comp_min = payload.comp_min
        existing.comp_max = payload.comp_max
        existing.currency = payload.currency
        existing.comp_phrase = payload.comp_phrase
        existing.seniority = payload.seniority
        existing.source_url = payload.source_url
        existing.match_score = payload.match_score
        existing.filter_version = payload.filter_version
        existing.passed_filter = payload.passed_filter
        existing.prompt_version_id = payload.prompt_version_id
        existing.model = payload.model
        existing.tokens_in = payload.tokens_in
        existing.tokens_out = payload.tokens_out
        existing.match_reason_ct = self._encrypt_reason(
            reason=payload.match_reason,
            email_id=payload.email_id,
            user_id=payload.user_id,
        )
        existing.match_reason_dek_wrapped = None

        await session.flush()
        return existing

    def decrypt_reason(self, *, row: JobMatch, user_id: UUID) -> str:
        """Reverse :meth:`_encrypt_reason`.

        Args:
            row: ORM row with ``match_reason_ct`` populated.
            user_id: Owner for encryption-context binding.

        Returns:
            Plaintext match-reason paragraph. Empty string if the row
            never carried one.
        """
        ciphertext = bytes(row.match_reason_ct)
        if not ciphertext:
            return ""
        if self._cipher is None:
            data = ciphertext
            return "" if data == b"\x00" else data.decode("utf-8")
        ctx = content_context(
            table="job_matches",
            row_id=str(row.email_id),
            purpose=_PURPOSE,
            user_id=str(user_id),
        )
        plaintext = self._cipher.decrypt(EncryptedBlob(ciphertext=ciphertext), ctx)
        return "" if plaintext == b"\x00" else plaintext.decode("utf-8")

    def _encrypt_reason(
        self,
        *,
        reason: str,
        email_id: UUID,
        user_id: UUID,
    ) -> bytes:
        """Envelope-encrypt the plaintext rationale.

        Args:
            reason: Plaintext match-reason paragraph.
            email_id: FK bound into the encryption context.
            user_id: Owner bound into the encryption context.

        Returns:
            Ciphertext bytes (or the UTF-8 plaintext when no cipher is
            configured — tests only).
        """
        data = reason.encode("utf-8")
        if not data:
            data = b"\x00"
        if self._cipher is None:
            return data
        ctx = content_context(
            table="job_matches",
            row_id=str(email_id),
            purpose=_PURPOSE,
            user_id=str(user_id),
        )
        return self._cipher.encrypt(data, ctx).ciphertext


__all__ = ["JobMatchWrite", "JobMatchesRepo"]
