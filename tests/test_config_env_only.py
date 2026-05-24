from __future__ import annotations


import pytest

from Undefined.config import Config


def test_env_only_chat_model_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ONEBOT_WS_URL", "ws://env-only:3001")
    monkeypatch.setenv("CHAT_MODEL_API_URL", "https://env.example/v1")
    monkeypatch.setenv("CHAT_MODEL_API_KEY", "env-key")
    monkeypatch.setenv("CHAT_MODEL_NAME", "env-chat")
    monkeypatch.setenv("VISION_MODEL_API_URL", "https://env.example/v1")
    monkeypatch.setenv("VISION_MODEL_API_KEY", "env-key")
    monkeypatch.setenv("VISION_MODEL_NAME", "env-vision")
    monkeypatch.setenv("AGENT_MODEL_API_URL", "https://env.example/v1")
    monkeypatch.setenv("AGENT_MODEL_API_KEY", "env-key")
    monkeypatch.setenv("AGENT_MODEL_NAME", "env-agent")

    cfg = Config.from_mapping({}, strict=False)
    assert cfg.onebot_ws_url == "ws://env-only:3001"
    assert cfg.chat_model.model_name == "env-chat"
    assert cfg.vision_model.model_name == "env-vision"
    assert cfg.agent_model.model_name == "env-agent"


def test_env_overridden_by_mapping(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHAT_MODEL_NAME", "from-env")
    cfg = Config.from_mapping(
        {
            "onebot": {"ws_url": "ws://x"},
            "models": {
                "chat": {
                    "api_url": "u",
                    "api_key": "k",
                    "model_name": "from-toml",
                },
                "vision": {"api_url": "u", "api_key": "k", "model_name": "v"},
                "agent": {"api_url": "u", "api_key": "k", "model_name": "a"},
            },
        },
        strict=False,
    )
    assert cfg.chat_model.model_name == "from-toml"


def test_http_proxy_env_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:7890")
    cfg = Config.from_mapping(
        {
            "onebot": {"ws_url": "ws://x"},
            "models": {
                "chat": {"api_url": "u", "api_key": "k", "model_name": "m"},
                "vision": {"api_url": "u", "api_key": "k", "model_name": "v"},
                "agent": {"api_url": "u", "api_key": "k", "model_name": "a"},
            },
        },
        strict=False,
    )
    assert cfg.http_proxy == "http://127.0.0.1:7890"
