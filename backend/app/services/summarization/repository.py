"""Summary persistence boundary (plan §14 Phase 3, §20.10).

Reads + writes ``summaries`` rows with transparent envelope encryption
on ``body_md`` and ``entities``. Service-layer code stays plaintext;
encrypt/decrypt happens here.

Email summaries go through :class:`SummariesRepo.upsert_email`; cluster
summaries go through :meth:`SummariesRepo.upsert_tech_news_cluster`.
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
from app.db.models import Summary

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.core.security import EnvelopeCipher


logger = get_logger(__name__)

_EMAIL_BODY_PURPOSE = "summaries_body_md_email"
"""Encryption-context purpose for per-email ``summaries.body_md``."""

_EMAIL_ENTITIES_PURPOSE = "summaries_entities_email"
"""Encryption-context purpose for per-email ``summaries.entities``."""

_CLUSTER_BODY_PURPOSE = "summaries_body_md_cluster"
"""Encryption-context purpose for cluster ``summaries.body_md``."""

_CLUSTER_ENTITIES_PURPOSE = "summaries_entities_cluster"
"""Encryption-context purpose for cluster ``summaries.entities``."""


@dataclass(frozen=True)
class SummaryEmailWrite:
    """Payload for persisting a per-email summary.

    Attributes:
        email_id: Target email.
        user_id: Owner — bound into the encryption context so re-assigning
            the row makes the ciphertext unreadable.
        prompt_version_id: FK into :class:`app.db.models.PromptVersion`.
        model: Provider-scoped model identifier.
        tokens_in: Tokens billed on input.
        tokens_out: Tokens billed on output.
        body_md: Plaintext markdown body (TL;DR + bullets).
        entities: Plaintext tuple of entity chips.
        confidence: Calibrated ``[0, 1]``.
        cache_hit: Whether the provider reported any cache-read tokens.
        batch_id: Optional Batch API job id when produced asynchronously.
    """

    email_id: UUID
    user_id: UUID
    prompt_version_id: UUID | None
    model: str
    tokens_in: int
    tokens_out: int
    body_md: str
    entities: tuple[str, ...]
    confidence: Decimal
    cache_hit: bool
    batch_id: str | None


@dataclass(frozen=True)
class SummaryTechNewsWrite:
    """Payload for persisting a cluster summary.

    Attributes:
        cluster_id: Target cluster.
        user_id: Owner.
        prompt_version_id: FK into :class:`app.db.models.PromptVersion`.
        model: Provider-scoped model identifier.
        tokens_in: Tokens billed on input.
        tokens_out: Tokens billed on output.
        body_md: Plaintext markdown body (headline + bullets).
        sources: Plaintext tuple of source subjects / URLs.
        confidence: Calibrated ``[0, 1]``.
        cache_hit: Whether the provider reported any cache-read tokens.
        batch_id: Optional Batch API job id.
    """

    cluster_id: UUID
    user_id: UUID
    prompt_version_id: UUID | None
    model: str
    tokens_in: int
    tokens_out: int
    body_md: str
    sources: tuple[str, ...]
    confidence: Decimal
    cache_hit: bool
    batch_id: str | None


class SummariesRepo:
    """Encrypt-on-write / decrypt-on-read gateway for ``summaries``.

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

    async def upsert_email(
        self,
        session: AsyncSession,
        payload: SummaryEmailWrite,
    ) -> Summary:
        """Insert or replace the per-email ``summaries`` row.

        Args:
            session: Active async session (caller owns commit).
            payload: :class:`SummaryEmailWrite` with plaintext fields.

        Returns:
            The attached :class:`Summary` ORM row (ciphertext columns
            populated).
        """
        existing = (
            (
                await session.execute(
                    select(Summary).where(
                        Summary.kind == "email",
                        Summary.email_id == payload.email_id,
                    ),
                )
            )
            .scalars()
            .first()
        )
        if existing is None:
            existing = Summary(
                kind="email",
                email_id=payload.email_id,
                cluster_id=None,
            )
            session.add(existing)

        existing.prompt_version_id = payload.prompt_version_id
        existing.model = payload.model
        existing.tokens_in = payload.tokens_in
        existing.tokens_out = payload.tokens_out
        existing.cache_hit = payload.cache_hit
        existing.confidence = payload.confidence
        existing.batch_id = payload.batch_id

        existing.body_md_ct = self._encrypt_text(
            plaintext=payload.body_md,
            row_id=str(payload.email_id),
            user_id=str(payload.user_id),
            purpose=_EMAIL_BODY_PURPOSE,
        )
        existing.entities_ct = self._encrypt_json(
            payload=list(payload.entities),
            row_id=str(payload.email_id),
            user_id=str(payload.user_id),
            purpose=_EMAIL_ENTITIES_PURPOSE,
        )

        await session.flush()
        return existing

    async def upsert_tech_news_cluster(
        self,
        session: AsyncSession,
        payload: SummaryTechNewsWrite,
    ) -> Summary:
        """Insert or replace the cluster ``summaries`` row.

        Args:
            session: Active async session (caller owns commit).
            payload: :class:`SummaryTechNewsWrite` with plaintext fields.

        Returns:
            The attached :class:`Summary` ORM row.
        """
        existing = (
            (
                await session.execute(
                    select(Summary).where(
                        Summary.kind == "tech_news_cluster",
                        Summary.cluster_id == payload.cluster_id,
                    ),
                )
            )
            .scalars()
            .first()
        )
        if existing is None:
            existing = Summary(
                kind="tech_news_cluster",
                email_id=None,
                cluster_id=payload.cluster_id,
            )
            session.add(existing)

        existing.prompt_version_id = payload.prompt_version_id
        existing.model = payload.model
        existing.tokens_in = payload.tokens_in
        existing.tokens_out = payload.tokens_out
        existing.cache_hit = payload.cache_hit
        existing.confidence = payload.confidence
        existing.batch_id = payload.batch_id

        existing.body_md_ct = self._encrypt_text(
            plaintext=payload.body_md,
            row_id=str(payload.cluster_id),
            user_id=str(payload.user_id),
            purpose=_CLUSTER_BODY_PURPOSE,
        )
        existing.entities_ct = self._encrypt_json(
            payload=list(payload.sources),
            row_id=str(payload.cluster_id),
            user_id=str(payload.user_id),
            purpose=_CLUSTER_ENTITIES_PURPOSE,
        )

        await session.flush()
        return existing

    def decrypt_email_body(self, *, row: Summary, user_id: UUID) -> str:
        """Reverse :meth:`_encrypt_text` for a per-email summary.

        Args:
            row: ORM row with ``kind='email'``.
            user_id: Owner for encryption-context binding.

        Returns:
            Plaintext markdown body.

        Raises:
            ValueError: If the row is not a per-email summary.
        """
        if row.kind != "email" or row.email_id is None:
            raise ValueError("expected per-email summary row")
        return self._decrypt_text(
            ciphertext=bytes(row.body_md_ct),
            row_id=str(row.email_id),
            user_id=str(user_id),
            purpose=_EMAIL_BODY_PURPOSE,
        )

    def decrypt_email_entities(
        self,
        *,
        row: Summary,
        user_id: UUID,
    ) -> tuple[str, ...]:
        """Decrypt the per-email entity chips.

        Args:
            row: ORM row with ``kind='email'``.
            user_id: Owner for context binding.

        Returns:
            Plaintext tuple of entity strings; empty when absent.
        """
        if row.kind != "email" or row.email_id is None:
            raise ValueError("expected per-email summary row")
        if row.entities_ct is None:
            return ()
        decoded = self._decrypt_json(
            ciphertext=bytes(row.entities_ct),
            row_id=str(row.email_id),
            user_id=str(user_id),
            purpose=_EMAIL_ENTITIES_PURPOSE,
        )
        if not isinstance(decoded, list):
            raise ValueError("entities must decode to a JSON array")
        return tuple(str(item) for item in decoded)

    def decrypt_cluster_body(self, *, row: Summary, user_id: UUID) -> str:
        """Decrypt the cluster-summary body.

        Args:
            row: ORM row with ``kind='tech_news_cluster'``.
            user_id: Owner for context binding.

        Returns:
            Plaintext markdown body.
        """
        if row.kind != "tech_news_cluster" or row.cluster_id is None:
            raise ValueError("expected tech-news cluster summary row")
        return self._decrypt_text(
            ciphertext=bytes(row.body_md_ct),
            row_id=str(row.cluster_id),
            user_id=str(user_id),
            purpose=_CLUSTER_BODY_PURPOSE,
        )

    def decrypt_cluster_sources(
        self,
        *,
        row: Summary,
        user_id: UUID,
    ) -> tuple[str, ...]:
        """Decrypt the cluster-summary source list."""
        if row.kind != "tech_news_cluster" or row.cluster_id is None:
            raise ValueError("expected tech-news cluster summary row")
        if row.entities_ct is None:
            return ()
        decoded = self._decrypt_json(
            ciphertext=bytes(row.entities_ct),
            row_id=str(row.cluster_id),
            user_id=str(user_id),
            purpose=_CLUSTER_ENTITIES_PURPOSE,
        )
        if not isinstance(decoded, list):
            raise ValueError("sources must decode to a JSON array")
        return tuple(str(item) for item in decoded)

    def _encrypt_text(
        self,
        *,
        plaintext: str,
        row_id: str,
        user_id: str,
        purpose: str,
    ) -> bytes:
        """Envelope-encrypt ``plaintext`` into a ``BYTEA`` blob."""
        data = plaintext.encode("utf-8")
        if not data:
            data = b"\x00"  # guard: EnvelopeCipher refuses empty plaintext.
        if self._cipher is None:
            return data
        ctx = content_context(
            table="summaries",
            row_id=row_id,
            purpose=purpose,
            user_id=user_id,
        )
        return self._cipher.encrypt(data, ctx).ciphertext

    def _decrypt_text(
        self,
        *,
        ciphertext: bytes,
        row_id: str,
        user_id: str,
        purpose: str,
    ) -> str:
        """Reverse :meth:`_encrypt_text`; returns the UTF-8 plaintext."""
        if self._cipher is None:
            data = bytes(ciphertext)
            return "" if data == b"\x00" else data.decode("utf-8")
        ctx = content_context(
            table="summaries",
            row_id=row_id,
            purpose=purpose,
            user_id=user_id,
        )
        data = self._cipher.decrypt(EncryptedBlob(ciphertext=bytes(ciphertext)), ctx)
        return "" if data == b"\x00" else data.decode("utf-8")

    def _encrypt_json(
        self,
        *,
        payload: list[str],
        row_id: str,
        user_id: str,
        purpose: str,
    ) -> bytes | None:
        """Envelope-encrypt a JSON-serializable list payload."""
        if not payload:
            return None
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        if self._cipher is None:
            return data
        ctx = content_context(
            table="summaries",
            row_id=row_id,
            purpose=purpose,
            user_id=user_id,
        )
        return self._cipher.encrypt(data, ctx).ciphertext

    def _decrypt_json(
        self,
        *,
        ciphertext: bytes,
        row_id: str,
        user_id: str,
        purpose: str,
    ) -> object:
        """Reverse :meth:`_encrypt_json`; returns the parsed JSON value."""
        if self._cipher is None:
            return json.loads(bytes(ciphertext).decode("utf-8"))
        ctx = content_context(
            table="summaries",
            row_id=row_id,
            purpose=purpose,
            user_id=user_id,
        )
        plaintext = self._cipher.decrypt(EncryptedBlob(ciphertext=bytes(ciphertext)), ctx)
        return json.loads(plaintext.decode("utf-8"))


__all__ = ["SummariesRepo", "SummaryEmailWrite", "SummaryTechNewsWrite"]
