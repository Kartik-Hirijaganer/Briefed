"""Unit tests for :mod:`app.core.app_config`."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.app_config import (
    AppConfig,
    AppConfigError,
    default_app_config_path,
    get_app_config,
    load_app_config,
)


def test_app_config_yaml_matches_model_defaults() -> None:
    config = load_app_config(default_app_config_path(), runtime="local")
    assert config == AppConfig()


def test_app_config_is_frozen_and_extra_forbid() -> None:
    config = AppConfig()
    with pytest.raises(ValidationError):
        config.features.jobs = False
    with pytest.raises(ValidationError):
        AppConfig.model_validate({"features": {"jobs": True, "unknown": True}})


def test_local_missing_config_falls_back_to_defaults(tmp_path: Path) -> None:
    config = load_app_config(tmp_path / "missing.yml", runtime="local")
    assert config == AppConfig()


def test_local_malformed_config_falls_back_to_defaults(tmp_path: Path) -> None:
    path = tmp_path / "app_config.yml"
    path.write_text("- not-a-mapping\n", encoding="utf-8")

    config = load_app_config(path, runtime="local")

    assert config == AppConfig()


def test_lambda_missing_config_raises(tmp_path: Path) -> None:
    with pytest.raises(AppConfigError):
        load_app_config(tmp_path / "missing.yml", runtime="lambda-api")


def test_lambda_malformed_config_raises(tmp_path: Path) -> None:
    path = tmp_path / "app_config.yml"
    path.write_text("- not-a-mapping\n", encoding="utf-8")

    with pytest.raises(AppConfigError):
        load_app_config(path, runtime="lambda-worker")


def test_get_app_config_is_memoized() -> None:
    get_app_config.cache_clear()
    try:
        assert get_app_config() is get_app_config()
    finally:
        get_app_config.cache_clear()
