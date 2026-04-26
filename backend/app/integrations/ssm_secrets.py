"""AWS SSM Parameter Store secret loader (plan §19.15).

The Briefed API + worker Lambdas ship no secrets inside the container
image. Instead, module-level startup code calls into this module to
pull every required secret from SSM Parameter Store on cold-start; the
values are then cached for the warm window. SnapStart captures the
snapshot *after* this call completes so subsequent restores skip the
round-trip.

Design notes
------------
* The only public entrypoint is :func:`fetch_parameters` — callers pass
  the SSM prefix (e.g. ``"/briefed/dev/"``) + the list of parameter
  short-names they expect; the function returns a ``dict[str, str]``
  keyed on short-name.
* Missing / empty / placeholder parameters raise
  :class:`MissingSecretError`. The Phase 0 exit-criteria unit test
  exercises exactly this branch (config loader must reject missing SSM
  parameters — see :mod:`backend.tests.unit.test_config`).
* The module is import-safe without AWS credentials — ``boto3`` is
  imported lazily inside :func:`fetch_parameters` so local dev / unit
  tests that never call it do not pay the import cost and do not
  require AWS creds on ``$PATH``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:  # pragma: no cover
    from typing import Protocol

    class _SsmClient(Protocol):
        """Structural typing for the subset of the boto3 SSM client we use."""

        def get_parameters(
            self,
            *,
            Names: list[str],
            WithDecryption: bool,
        ) -> dict[str, Any]: ...


_PLACEHOLDER_PREFIX = "PLACEHOLDER"
"""Terraform seeds SSM parameters with this literal so we can detect unset values."""


class MissingSecretError(RuntimeError):
    """Raised when one or more required SSM parameters are missing or unset.

    Attributes:
        missing: Short-names of the parameters that could not be resolved.
    """

    def __init__(self, missing: Iterable[str]) -> None:
        """Build the error with a sorted list of missing parameter names.

        Args:
            missing: Short-names of the required parameters that are absent
                or still hold the Terraform placeholder value.
        """
        self.missing: tuple[str, ...] = tuple(sorted(set(missing)))
        joined = ", ".join(self.missing)
        super().__init__(
            f"Missing required SSM parameters: {joined}. "
            "Set them via `aws ssm put-parameter --overwrite` before deploying.",
        )


def _build_client() -> _SsmClient:
    """Construct the boto3 SSM client using the ambient AWS config.

    Imports ``boto3`` lazily so importing this module has no AWS cost.

    Returns:
        A boto3 SSM client honoring ``AWS_ENDPOINT_URL`` when set (local
        LocalStack development).
    """
    import boto3  # type: ignore[import-untyped]  # noqa: PLC0415 — deliberately lazy

    return cast("_SsmClient", boto3.client("ssm"))


def fetch_parameters(
    *,
    prefix: str,
    required: Iterable[str],
    optional: Iterable[str] = (),
    client: _SsmClient | None = None,
) -> dict[str, str]:
    """Fetch SSM parameters under ``prefix`` and return a name→value mapping.

    Every string in ``required`` MUST resolve to a non-empty, non-placeholder
    value or :class:`MissingSecretError` is raised. ``optional`` parameters
    are silently skipped when absent.

    Args:
        prefix: SSM path prefix (e.g. ``"/briefed/dev/"``). The prefix is
            prepended to each short-name; trailing slash is preserved.
        required: Short-names that must resolve (values written by
            operators via ``aws ssm put-parameter``).
        optional: Short-names that may be absent — returned mapping omits
            them rather than raising.
        client: Pre-built SSM client; if ``None`` a fresh client is created
            via :func:`_build_client`. Tests inject a mock here.

    Returns:
        Mapping from short-name (without the prefix) to decrypted value.

    Raises:
        MissingSecretError: If any ``required`` parameter is absent or
            still holds the placeholder value.
    """
    ssm: _SsmClient = client if client is not None else _build_client()
    required_set = set(required)
    optional_set = set(optional)
    all_names = sorted(required_set | optional_set)

    if not all_names:
        return {}

    fq_to_short = {f"{prefix}{name}": name for name in all_names}
    response = ssm.get_parameters(
        Names=list(fq_to_short.keys()),
        WithDecryption=True,
    )

    found: dict[str, str] = {}
    for entry in response.get("Parameters", []) or []:
        fq_name = str(entry.get("Name", ""))
        value = str(entry.get("Value", ""))
        short = fq_to_short.get(fq_name)
        if short is None:
            continue
        if not value or value.startswith(_PLACEHOLDER_PREFIX):
            continue
        found[short] = value

    missing = required_set - found.keys()
    if missing:
        raise MissingSecretError(missing)

    return found


def merge_with_env(
    *,
    env: Mapping[str, str],
    ssm_values: Mapping[str, str],
    field_to_ssm: Mapping[str, str],
) -> dict[str, str]:
    """Merge environment-variable defaults with SSM-resolved values.

    Env vars win for locals / overrides; SSM values fill the rest. This
    helper keeps :mod:`backend.app.core.config` free of ad-hoc dict
    wiring logic and gives the merge a single test surface.

    Args:
        env: The current environment mapping (typically ``os.environ``).
        ssm_values: Short-name → value mapping returned by
            :func:`fetch_parameters`.
        field_to_ssm: Mapping from config-field name to the SSM short-name
            it resolves from (e.g. ``{"openrouter_api_key": "openrouter_api_key"}``).

    Returns:
        A new ``dict[str, str]`` keyed by config-field name.
    """
    merged: dict[str, str] = {}
    for field, ssm_name in field_to_ssm.items():
        env_value = env.get(field.upper())
        if env_value:
            merged[field] = env_value
        elif ssm_name in ssm_values:
            merged[field] = ssm_values[ssm_name]
    return merged
