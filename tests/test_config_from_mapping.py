from __future__ import annotations

from pathlib import Path

import pytest

from Undefined.config import Config, set_config


_MINIMAL_MAPPING = {
    "onebot": {"ws_url": "ws://127.0.0.1:3001"},
    "models": {
        "chat": {
            "api_url": "https://api.example/v1",
            "api_key": "sk-test",
            "model_name": "gpt-test",
        },
        "vision": {
            "api_url": "https://api.example/v1",
            "api_key": "sk-test",
            "model_name": "vision-test",
        },
        "agent": {
            "api_url": "https://api.example/v1",
            "api_key": "sk-test",
            "model_name": "agent-test",
        },
    },
}


def test_from_mapping_builds_without_toml() -> None:
    cfg = Config.from_mapping(_MINIMAL_MAPPING, strict=False)
    assert cfg.onebot_ws_url == "ws://127.0.0.1:3001"
    assert cfg.chat_model.model_name == "gpt-test"


def test_tool_search_defaults() -> None:
    cfg = Config.from_mapping(_MINIMAL_MAPPING, strict=False)

    assert cfg.tool_search_enabled is False
    assert cfg.tool_search_always_loaded == ["send_message", "end"]
    assert cfg.tool_search_max_results == 5


def test_tool_search_config_parsing_and_normalization() -> None:
    mapping = {
        **_MINIMAL_MAPPING,
        "skills": {
            "tool_search_enabled": True,
            "tool_search_always_loaded": [],
            "tool_search_max_results": 0,
        },
    }

    cfg = Config.from_mapping(mapping, strict=False)

    assert cfg.tool_search_enabled is True
    assert cfg.tool_search_always_loaded == []
    assert cfg.tool_search_max_results == 1


def test_builder_with_mapping() -> None:
    cfg = Config.builder().with_mapping(_MINIMAL_MAPPING).build(strict=False)
    assert cfg.agent_model.model_name == "agent-test"


def test_set_config_injects_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    import Undefined.config as config_pkg

    monkeypatch.setattr(config_pkg, "_config", None)
    monkeypatch.setattr(config_pkg, "_config_manager", None)
    cfg = Config.from_mapping(_MINIMAL_MAPPING, strict=False)
    set_config(cfg)
    assert config_pkg.get_config(strict=False) is cfg
    assert config_pkg.get_config_manager().load(strict=False) is cfg


def test_from_mapping_matches_load(tmp_path: Path) -> None:
    toml = """
[onebot]
ws_url = "ws://127.0.0.1:3001"
[models.chat]
api_url = "https://api.example/v1"
api_key = "sk-test"
model_name = "gpt-test"
[models.vision]
api_url = "https://api.example/v1"
api_key = "sk-test"
model_name = "vision-test"
[models.agent]
api_url = "https://api.example/v1"
api_key = "sk-test"
model_name = "agent-test"
"""
    path = tmp_path / "config.toml"
    path.write_text(toml, encoding="utf-8")
    from_file = Config.load(path, strict=False)
    from_map = Config.from_mapping(
        {
            "onebot": {"ws_url": "ws://127.0.0.1:3001"},
            "models": {
                "chat": {
                    "api_url": "https://api.example/v1",
                    "api_key": "sk-test",
                    "model_name": "gpt-test",
                },
                "vision": {
                    "api_url": "https://api.example/v1",
                    "api_key": "sk-test",
                    "model_name": "vision-test",
                },
                "agent": {
                    "api_url": "https://api.example/v1",
                    "api_key": "sk-test",
                    "model_name": "agent-test",
                },
            },
        },
        strict=False,
    )
    assert from_file.chat_model.model_name == from_map.chat_model.model_name
    assert from_file.onebot_ws_url == from_map.onebot_ws_url
