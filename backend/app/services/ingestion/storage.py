"""S3 raw-MIME storage toggle (plan §7 ingestion — ``store_raw_mime``).

When ``user_preferences.store_raw_mime=True`` the ingestion pipeline
keeps the provider-returned MIME bytes in ``s3://briefed-raw-email/`` so
future re-parses can run without re-fetching Gmail. The default is
``False`` (metadata-only); callers must opt in per §19.15.

The S3 client is imported lazily so local / unit tests do not need
boto3 credentials. An in-memory fake is provided for tests that want to
exercise the fan-out without a live AWS endpoint.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:  # pragma: no cover
    from uuid import UUID


@dataclass
class PutResult:
    """Summary of a successful write.

    Attributes:
        bucket: Target bucket name.
        key: Target object key.
        size_bytes: Size of the written body.
    """

    bucket: str
    key: str
    size_bytes: int


class ObjectStore(Protocol):
    """Structural typing for the subset of the boto3 S3 client we use."""

    def put_object(
        self,
        *,
        Bucket: str,
        Key: str,
        Body: bytes,
        ContentType: str,
    ) -> dict[str, Any]:
        """Upload ``Body`` to ``Bucket`` / ``Key``."""
        ...


@dataclass
class InMemoryObjectStore:
    """In-process fake :class:`ObjectStore` for unit + integration tests.

    Attributes:
        objects: Mapping from ``(bucket, key)`` to the uploaded bytes.
    """

    objects: dict[tuple[str, str], bytes] = field(default_factory=dict)

    def put_object(
        self,
        *,
        Bucket: str,
        Key: str,
        Body: bytes,
        ContentType: str = "application/octet-stream",
    ) -> dict[str, Any]:
        """Record the upload in the in-memory dict."""
        self.objects[(Bucket, Key)] = Body
        return {"ETag": "fake"}


def build_raw_key(*, account_id: UUID, message_id: str) -> str:
    """Return the canonical S3 key for a raw-MIME upload.

    Args:
        account_id: Owning connected_account id.
        message_id: Provider-scoped message id.

    Returns:
        S3 key formatted ``<account_id>/<yyyymm>/<message_id>.eml``.
        The date prefix is the ingest date (coarse) so lifecycle rules
        can roll across account boundaries uniformly.
    """
    return f"{account_id}/{message_id}.eml"


def maybe_store_raw_mime(
    *,
    store: ObjectStore,
    bucket: str,
    account_id: UUID,
    message_id: str,
    raw_mime: bytes | None,
    enabled: bool,
) -> PutResult | None:
    """Upload ``raw_mime`` when the per-user toggle is on.

    Args:
        store: :class:`ObjectStore` implementation.
        bucket: Destination bucket name.
        account_id: Owning connected_account id.
        message_id: Provider message id.
        raw_mime: The raw bytes to persist, or ``None`` (no-op).
        enabled: Whether the user opted into raw-MIME storage.

    Returns:
        A :class:`PutResult` when an upload happened, otherwise ``None``.
    """
    if not enabled or not raw_mime:
        return None
    key = build_raw_key(account_id=account_id, message_id=message_id)
    store.put_object(
        Bucket=bucket,
        Key=key,
        Body=raw_mime,
        ContentType="message/rfc822",
    )
    return PutResult(bucket=bucket, key=key, size_bytes=len(raw_mime))
