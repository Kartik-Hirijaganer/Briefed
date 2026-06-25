"""Ensure LocalStack KMS aliases required by local development exist."""

from __future__ import annotations

import os
import time
from typing import Protocol, TypedDict, cast

import boto3
from botocore.exceptions import BotoCoreError, ClientError, EndpointConnectionError

_ALIASES: tuple[str, ...] = (
    "alias/briefed-dev-token-wrap",
    "alias/briefed-dev-content-encrypt",
)
"""LocalStack KMS aliases expected by Infisical development secrets."""

_MAX_ATTEMPTS = 30
"""Maximum LocalStack readiness attempts before failing."""


class _KeyMetadata(TypedDict):
    """Subset of ``create_key`` metadata used by this script."""

    KeyId: str


class _CreateKeyResponse(TypedDict):
    """Subset of the KMS ``create_key`` response used by this script."""

    KeyMetadata: _KeyMetadata


class _Alias(TypedDict, total=False):
    """Subset of a KMS alias row used by this script."""

    AliasName: str


class _ListAliasesResponse(TypedDict):
    """Subset of the KMS ``list_aliases`` response used by this script."""

    Aliases: list[_Alias]


class _KmsClient(Protocol):
    """Protocol for the small KMS client surface used here."""

    def list_aliases(self) -> _ListAliasesResponse:
        """List aliases in the configured LocalStack KMS account.

        Returns:
            Alias listing response.
        """

    def create_key(self, *, Description: str) -> _CreateKeyResponse:  # noqa: N803
        """Create a KMS key.

        Args:
            Description: Human-readable key description.

        Returns:
            Created key metadata response.
        """

    def create_alias(self, *, AliasName: str, TargetKeyId: str) -> None:  # noqa: N803
        """Create a KMS alias.

        Args:
            AliasName: Alias name, including the ``alias/`` prefix.
            TargetKeyId: KMS key id to target.
        """


def _build_client() -> _KmsClient:
    """Build a KMS client pointed at LocalStack.

    Returns:
        Boto3 KMS client narrowed to the protocol used by this script.
    """
    endpoint_url = os.environ.get("AWS_ENDPOINT_URL", "http://localhost:4566")
    region_name = os.environ.get("AWS_REGION", "us-east-1")
    return cast(
        "_KmsClient",
        boto3.client("kms", endpoint_url=endpoint_url, region_name=region_name),
    )


def _ensure_aliases(client: _KmsClient) -> None:
    """Create missing local KMS aliases.

    Args:
        client: LocalStack KMS client.
    """
    existing = {
        alias["AliasName"] for alias in client.list_aliases()["Aliases"] if "AliasName" in alias
    }
    for alias_name in _ALIASES:
        if alias_name in existing:
            print(f"{alias_name} exists")
            continue
        response = client.create_key(Description=alias_name)
        client.create_alias(AliasName=alias_name, TargetKeyId=response["KeyMetadata"]["KeyId"])
        print(f"{alias_name} created")


def main() -> None:
    """Wait for LocalStack and ensure local KMS aliases exist.

    Raises:
        SystemExit: If LocalStack KMS is not reachable after retrying.
    """
    client = _build_client()
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            _ensure_aliases(client)
            return
        except (BotoCoreError, ClientError, EndpointConnectionError) as exc:
            if attempt == _MAX_ATTEMPTS:
                raise SystemExit(f"LocalStack KMS did not become ready: {exc}") from exc
            time.sleep(1)


if __name__ == "__main__":
    main()
