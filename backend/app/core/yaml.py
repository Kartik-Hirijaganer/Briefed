"""Small YAML loading helpers for repository-owned config files."""

from __future__ import annotations

from pathlib import Path

import yaml


class YamlConfigError(ValueError):
    """Raised when a YAML config payload is missing or malformed."""


def safe_load_yaml_mapping(text: str, *, source: str) -> dict[str, object]:
    """Parse a YAML document and require a mapping at the top level.

    Args:
        text: YAML document text.
        source: Human-readable source name for diagnostics.

    Returns:
        Parsed top-level mapping.

    Raises:
        YamlConfigError: If YAML parsing fails or the payload is not a mapping.
    """
    try:
        payload: object = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise YamlConfigError(f"{source}: malformed YAML") from exc
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise YamlConfigError(f"{source}: expected a YAML mapping")
    return {str(key): value for key, value in payload.items()}


def safe_load_yaml_file(path: Path) -> dict[str, object]:
    """Read and parse a YAML mapping from ``path``.

    Args:
        path: Config file path.

    Returns:
        Parsed top-level mapping.

    Raises:
        YamlConfigError: If the file cannot be read or parsed as a mapping.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise YamlConfigError(f"{path}: cannot read YAML file") from exc
    return safe_load_yaml_mapping(text, source=str(path))


__all__ = ["YamlConfigError", "safe_load_yaml_file", "safe_load_yaml_mapping"]
