from __future__ import annotations

import pytest

from Undefined.config import Config
from Undefined.config.env_registry import env_key_for_path
from Undefined.webui.utils import load_comment_map, load_default_data


def test_lxmusic2api_defaults() -> None:
    config = Config.from_mapping({}, strict=False)

    assert config.lxmusic2api_base_url == "http://127.0.0.1:3000"
    assert config.lxmusic2api_api_key == ""


def test_lxmusic2api_mapping_is_normalized() -> None:
    config = Config.from_mapping(
        {
            "lxmusic2api": {
                "base_url": " https://music.example.test/gateway/ ",
                "api_key": " configured-key ",
            }
        },
        strict=False,
    )

    assert config.lxmusic2api_base_url == "https://music.example.test/gateway"
    assert config.lxmusic2api_api_key == "configured-key"


def test_lxmusic2api_environment_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LXMUSIC2API_BASE_URL", "https://env.example.test/")
    monkeypatch.setenv("LXMUSIC2API_API_KEY", "env-key")

    config = Config.from_mapping({}, strict=False)

    assert config.lxmusic2api_base_url == "https://env.example.test"
    assert config.lxmusic2api_api_key == "env-key"


def test_lxmusic2api_mapping_precedes_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LXMUSIC2API_BASE_URL", "https://env.example.test")
    monkeypatch.setenv("LXMUSIC2API_API_KEY", "env-key")

    config = Config.from_mapping(
        {
            "lxmusic2api": {
                "base_url": "https://mapping.example.test",
                "api_key": "mapping-key",
            }
        },
        strict=False,
    )

    assert config.lxmusic2api_base_url == "https://mapping.example.test"
    assert config.lxmusic2api_api_key == "mapping-key"


def test_lxmusic2api_environment_variables_are_registered() -> None:
    assert env_key_for_path(("lxmusic2api", "base_url")) == "LXMUSIC2API_BASE_URL"
    assert env_key_for_path(("lxmusic2api", "api_key")) == "LXMUSIC2API_API_KEY"


def test_lxmusic2api_config_updates_in_place() -> None:
    current = Config.from_mapping({}, strict=False)
    updated = Config.from_mapping(
        {
            "lxmusic2api": {
                "base_url": "https://updated.example.test",
                "api_key": "updated-key",
            }
        },
        strict=False,
    )

    changes = current.update_from(updated)

    assert changes["lxmusic2api_base_url"] == (
        "http://127.0.0.1:3000",
        "https://updated.example.test",
    )
    assert changes["lxmusic2api_api_key"] == ("", "updated-key")
    assert current.lxmusic2api_api_key == "updated-key"


def test_lxmusic2api_is_available_in_management_config_template() -> None:
    defaults = load_default_data()
    comments = load_comment_map()

    assert defaults["lxmusic2api"] == {
        "base_url": "http://127.0.0.1:3000",
        "api_key": "",
    }
    assert "lxmusic2api.base_url" in comments
    assert "lxmusic2api.api_key" in comments
