"""AWS SSM Parameter Store secret loader.

Lambda containers do not bake application secrets into the image. During
cold start, the settings layer can hydrate missing runtime secrets from SSM
SecureString parameters created by Terraform and populated by deploy workflows.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Protocol, cast

from pydantic import BaseModel, ConfigDict, Field

_PLACEHOLDER_PREFIX = "PLACEHOLDER"
_MAX_GET_PARAMETERS_NAMES = 10


class SsmParameter(BaseModel):
    """Single SSM parameter returned by ``get_parameters``.

    Attributes:
        name: Fully qualified SSM parameter path.
        value: Decrypted parameter value.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    name: str = Field(validation_alias="Name", description="Fully qualified SSM parameter path.")
    value: str = Field(validation_alias="Value", description="Decrypted SSM parameter value.")


class SsmGetParametersResponse(BaseModel):
    """Subset of the SSM ``get_parameters`` response used by Briefed.

    Attributes:
        parameters: Successfully resolved parameters.
        invalid_parameters: Fully qualified paths SSM could not resolve.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    parameters: tuple[SsmParameter, ...] = Field(
        default=(),
        validation_alias="Parameters",
        description="Parameters returned by SSM.",
    )
    invalid_parameters: tuple[str, ...] = Field(
        default=(),
        validation_alias="InvalidParameters",
        description="Parameter names SSM could not resolve.",
    )


class SsmClient(Protocol):
    """Structural type for the subset of the boto3 SSM client used here."""

    def get_parameters(
        self,
        *,
        Names: list[str],
        WithDecryption: bool,
    ) -> Mapping[str, object]:
        """Return decrypted SSM parameters for ``Names``."""
        ...  # pragma: no cover


class MissingSecretError(RuntimeError):
    """Raised when one or more required SSM parameters are absent or unset.

    Attributes:
        missing: Sorted short names of missing parameters.
    """

    missing: tuple[str, ...]

    def __init__(self, missing: Iterable[str]) -> None:
        """Build an error for missing parameter short names.

        Args:
            missing: Required SSM short names that are absent, empty, or
                still set to Terraform's placeholder value.
        """
        self.missing = tuple(sorted(set(missing)))
        joined = ", ".join(self.missing)
        super().__init__(
            f"Missing required SSM parameters: {joined}. "
            "Set them via `aws ssm put-parameter --overwrite` before deploying.",
        )


def _build_client() -> SsmClient:
    """Construct an SSM client using the ambient AWS runtime configuration.

    Returns:
        Boto3 SSM client narrowed to :class:`SsmClient`.
    """
    import boto3  # type: ignore[import-untyped]  # noqa: PLC0415

    return cast("SsmClient", boto3.client("ssm"))


def _normalize_prefix(prefix: str) -> str:
    """Return ``prefix`` with exactly one trailing slash.

    Args:
        prefix: SSM parameter prefix from Terraform.

    Returns:
        Prefix with a trailing slash.
    """
    return prefix if prefix.endswith("/") else f"{prefix}/"


def _chunks(values: Sequence[str], size: int) -> Iterable[Sequence[str]]:
    """Yield fixed-size slices from ``values``.

    Args:
        values: Ordered values to chunk.
        size: Maximum slice size.

    Yields:
        Slices with at most ``size`` items.
    """
    for index in range(0, len(values), size):
        yield values[index : index + size]


def _is_usable_secret(value: str | None) -> bool:
    """Return whether ``value`` is non-empty and not a placeholder.

    Args:
        value: Secret value to inspect.

    Returns:
        ``True`` when the value can be used at runtime.
    """
    if value is None:
        return False
    stripped = value.strip()
    return bool(stripped) and not stripped.startswith(_PLACEHOLDER_PREFIX)


def fetch_parameters(
    *,
    prefix: str,
    required: Iterable[str],
    optional: Iterable[str] = (),
    client: SsmClient | None = None,
) -> dict[str, str]:
    """Fetch decrypted SSM parameters under ``prefix``.

    Args:
        prefix: SSM path prefix, for example ``/briefed/prod/``.
        required: Short names that must resolve to non-placeholder values.
        optional: Short names that may be absent.
        client: Optional prebuilt SSM client for tests.

    Returns:
        Mapping from parameter short name to decrypted value.

    Raises:
        MissingSecretError: If any required short name is absent, empty, or
            still has Terraform's placeholder value.
        ValidationError: If AWS returns a response shape that does not match
            the SSM contract this loader expects.
    """
    normalized_prefix = _normalize_prefix(prefix)
    required_set = set(required)
    optional_set = set(optional)
    all_short_names = sorted(required_set | optional_set)
    if not all_short_names:
        return {}

    active_client = client if client is not None else _build_client()
    full_to_short = {f"{normalized_prefix}{name}": name for name in all_short_names}
    found: dict[str, str] = {}
    missing = set(required_set)

    for names in _chunks(list(full_to_short), _MAX_GET_PARAMETERS_NAMES):
        response = SsmGetParametersResponse.model_validate(
            active_client.get_parameters(
                Names=list(names),
                WithDecryption=True,
            ),
        )
        for invalid_name in response.invalid_parameters:
            short_name = full_to_short.get(invalid_name)
            if short_name in required_set:
                missing.add(short_name)
        for parameter in response.parameters:
            short_name = full_to_short.get(parameter.name)
            if short_name is None:
                continue
            if not _is_usable_secret(parameter.value):
                if short_name in required_set:
                    missing.add(short_name)
                continue
            found[short_name] = parameter.value
            missing.discard(short_name)

    if missing:
        raise MissingSecretError(missing)
    return found


def merge_with_env(
    *,
    env: Mapping[str, str],
    ssm_values: Mapping[str, str],
    field_to_ssm: Mapping[str, str],
) -> dict[str, str]:
    """Merge environment variables with SSM values for settings fields.

    Environment values win so local overrides and direct Infisical injection
    remain authoritative. SSM fills only fields whose env aliases are absent,
    empty, or placeholders.

    Args:
        env: Current process environment.
        ssm_values: Short-name values returned by :func:`fetch_parameters`.
        field_to_ssm: Mapping from settings field names to SSM short names.

    Returns:
        Settings keyword arguments keyed by field name.
    """
    merged: dict[str, str] = {}
    for field_name, ssm_name in field_to_ssm.items():
        field_env_name = field_name.upper()
        for env_name in (f"BRIEFED_{field_env_name}", field_env_name):
            env_value = env.get(env_name)
            if env_value is not None and _is_usable_secret(env_value):
                merged[field_name] = env_value
                break
        else:
            ssm_value = ssm_values.get(ssm_name)
            if ssm_value is not None and _is_usable_secret(ssm_value):
                merged[field_name] = ssm_value
    return merged


__all__ = [
    "MissingSecretError",
    "SsmClient",
    "fetch_parameters",
    "merge_with_env",
]
