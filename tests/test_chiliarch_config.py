from __future__ import annotations

from typing import Any

import pytest

from Undefined.config import Config
from Undefined.config.models import ChiliarchConfig
from Undefined.config.hot_reload import _RESTART_REQUIRED_KEYS


def test_defaults_disabled_and_no_virtual_qq() -> None:
    cfg = Config.from_mapping({}, strict=False).chiliarch
    assert not cfg.enabled
    assert cfg.logical_identity == "chiliarch_main"
    assert cfg.max_concurrent_tasks == 1
    assert "chiliarch" in _RESTART_REQUIRED_KEYS


@pytest.mark.parametrize(
    "identity", ["42", "../qq", "a/b", "a\\b", "", ".", "C:qq", "a\0b"]
)
def test_identity_cannot_be_numeric_or_path(identity: str) -> None:
    with pytest.raises(ValueError):
        ChiliarchConfig(logical_identity=identity)


@pytest.mark.parametrize("capacity", [0, -1, True, 1.5, "oops"])
def test_invalid_capacity(capacity: Any) -> None:
    with pytest.raises(ValueError):
        Config.from_mapping(
            {"chiliarch": {"max_concurrent_tasks": capacity}}, strict=False
        )


def test_mapping_environment_and_restart(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHILIARCH_ENABLED", "true")
    monkeypatch.setenv("CHILIARCH_LOGICAL_IDENTITY", "internal_test")
    monkeypatch.setenv("CHILIARCH_MAX_CONCURRENT_TASKS", "2")
    cfg = Config.from_mapping({}, strict=False)
    assert cfg.chiliarch.enabled
    assert cfg.chiliarch.logical_identity == "internal_test"
    assert cfg.chiliarch.max_concurrent_tasks == 2
    newer = Config.from_mapping({"chiliarch": {"enabled": False}}, strict=False)
    assert not newer.chiliarch.enabled
    changes = cfg.update_from(newer)
    assert "chiliarch" in changes
