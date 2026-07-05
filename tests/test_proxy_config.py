from __future__ import annotations

from typing import Any

import pytest

from Undefined.config import Config


_PROXY_ENV_KEYS = (
    "USE_PROXY",
    "ATTACHMENTS_USE_PROXY",
    "SEARCH_USE_PROXY",
    "RENDER_USE_PROXY",
    "IMAGE_GEN_USE_PROXY",
    "MESSAGES_USE_PROXY",
    "BILIBILI_USE_PROXY",
    "ARXIV_USE_PROXY",
    "GITHUB_USE_PROXY",
    "API_TOOL_INVOKE_CALLBACK_USE_PROXY",
    "NAGA_USE_PROXY",
    "CHAT_MODEL_USE_PROXY",
    "VISION_MODEL_USE_PROXY",
    "SECURITY_MODEL_USE_PROXY",
    "NAGA_MODEL_USE_PROXY",
    "AGENT_MODEL_USE_PROXY",
    "HISTORIAN_MODEL_USE_PROXY",
    "SUMMARY_MODEL_USE_PROXY",
    "GROK_MODEL_USE_PROXY",
    "EMBEDDING_MODEL_USE_PROXY",
    "RERANK_MODEL_USE_PROXY",
    "IMAGE_GEN_MODEL_USE_PROXY",
    "IMAGE_EDIT_MODEL_USE_PROXY",
)


def _clear_proxy_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _PROXY_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def _minimal_mapping() -> dict[str, Any]:
    return {
        "onebot": {"ws_url": "ws://127.0.0.1:3001"},
        "models": {
            "chat": {
                "api_url": "https://api.example/v1",
                "api_key": "sk-chat",
                "model_name": "gpt-chat",
            },
            "vision": {
                "api_url": "https://api.example/v1",
                "api_key": "sk-vision",
                "model_name": "gpt-vision",
            },
            "agent": {
                "api_url": "https://api.example/v1",
                "api_key": "sk-agent",
                "model_name": "gpt-agent",
            },
        },
    }


def test_proxy_switches_default_false_and_legacy_global_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_proxy_env(monkeypatch)
    monkeypatch.setenv("USE_PROXY", "true")
    mapping = _minimal_mapping()
    mapping["proxy"] = {
        "use_proxy": True,
        "http_proxy": "http://127.0.0.1:7890",
        "https_proxy": "http://127.0.0.1:7891",
    }

    cfg = Config.from_mapping(mapping, strict=False)

    assert not hasattr(cfg, "use_proxy")
    assert cfg.http_proxy == "http://127.0.0.1:7890"
    assert cfg.https_proxy == "http://127.0.0.1:7891"
    assert cfg.attachment_use_proxy is False
    assert cfg.search_use_proxy is False
    assert cfg.render_use_proxy is False
    assert cfg.image_gen.use_proxy is False
    assert cfg.messages_use_proxy is False
    assert cfg.bilibili_use_proxy is False
    assert cfg.arxiv_use_proxy is False
    assert cfg.github_use_proxy is False
    assert cfg.api.tool_invoke_callback_use_proxy is False
    assert cfg.naga.use_proxy is False
    assert cfg.chat_model.use_proxy is False
    assert cfg.vision_model.use_proxy is False
    assert cfg.security_model.use_proxy is False
    assert cfg.naga_model.use_proxy is False
    assert cfg.agent_model.use_proxy is False
    assert cfg.historian_model.use_proxy is False
    assert cfg.summary_model.use_proxy is False
    assert cfg.grok_model.use_proxy is False
    assert cfg.embedding_model.use_proxy is False
    assert cfg.rerank_model.use_proxy is False
    assert cfg.models_image_gen.use_proxy is False
    assert cfg.models_image_edit.use_proxy is False


def test_proxy_switches_parse_per_feature_and_per_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_proxy_env(monkeypatch)
    mapping = _minimal_mapping()
    mapping.update(
        {
            "attachments": {"use_proxy": True},
            "search": {"use_proxy": True},
            "render": {"use_proxy": True},
            "image_gen": {"use_proxy": True},
            "messages": {"use_proxy": True},
            "bilibili": {"use_proxy": True},
            "arxiv": {"use_proxy": True},
            "github": {"use_proxy": True},
            "api": {"tool_invoke_callback_use_proxy": True},
            "naga": {"use_proxy": True},
        }
    )
    models = mapping["models"]
    assert isinstance(models, dict)
    models["chat"] = {
        **models["chat"],
        "use_proxy": True,
        "pool": {
            "enabled": True,
            "models": [
                {
                    "model_name": "gpt-chat-pool-proxy",
                    "api_url": "https://pool.example/v1",
                    "api_key": "sk-pool",
                    "use_proxy": True,
                },
                {
                    "model_name": "gpt-chat-pool-direct",
                    "api_url": "https://pool.example/v1",
                    "api_key": "sk-pool",
                },
            ],
        },
    }
    models["vision"] = {**models["vision"], "use_proxy": True}
    models["security"] = {
        "api_url": "https://api.example/v1",
        "api_key": "sk-security",
        "model_name": "gpt-security",
        "use_proxy": True,
    }
    models["naga"] = {
        "api_url": "https://api.example/v1",
        "api_key": "sk-naga",
        "model_name": "gpt-naga",
        "use_proxy": True,
    }
    models["agent"] = {
        **models["agent"],
        "use_proxy": True,
        "pool": {
            "enabled": True,
            "models": [
                {
                    "model_name": "gpt-agent-pool-proxy",
                    "api_url": "https://pool.example/v1",
                    "api_key": "sk-pool",
                    "use_proxy": True,
                },
                {
                    "model_name": "gpt-agent-pool-direct",
                    "api_url": "https://pool.example/v1",
                    "api_key": "sk-pool",
                },
            ],
        },
    }
    models["historian"] = {"model_name": "gpt-historian", "use_proxy": True}
    models["summary"] = {"model_name": "gpt-summary", "use_proxy": True}
    models["grok"] = {
        "api_url": "https://grok.example/v1",
        "api_key": "sk-grok",
        "model_name": "grok-4-search",
        "use_proxy": True,
    }
    models["embedding"] = {
        "api_url": "https://api.example/v1",
        "api_key": "sk-embedding",
        "model_name": "text-embedding-3-small",
        "use_proxy": True,
    }
    models["rerank"] = {
        "api_url": "https://api.example/v1",
        "api_key": "sk-rerank",
        "model_name": "text-rerank-001",
        "use_proxy": True,
    }
    models["image_gen"] = {
        "api_url": "https://image.example/v1",
        "api_key": "sk-image",
        "model_name": "gpt-image-1",
        "use_proxy": True,
    }
    models["image_edit"] = {
        "api_url": "https://image.example/v1",
        "api_key": "sk-image",
        "model_name": "gpt-image-1",
        "use_proxy": True,
    }

    cfg = Config.from_mapping(mapping, strict=False)

    assert cfg.attachment_use_proxy is True
    assert cfg.search_use_proxy is True
    assert cfg.render_use_proxy is True
    assert cfg.image_gen.use_proxy is True
    assert cfg.messages_use_proxy is True
    assert cfg.bilibili_use_proxy is True
    assert cfg.arxiv_use_proxy is True
    assert cfg.github_use_proxy is True
    assert cfg.api.tool_invoke_callback_use_proxy is True
    assert cfg.naga.use_proxy is True
    assert cfg.chat_model.use_proxy is True
    assert cfg.chat_model.pool is not None
    assert cfg.chat_model.pool.models[0].use_proxy is True
    assert cfg.chat_model.pool.models[1].use_proxy is False
    assert cfg.vision_model.use_proxy is True
    assert cfg.security_model.use_proxy is True
    assert cfg.naga_model.use_proxy is True
    assert cfg.agent_model.use_proxy is True
    assert cfg.agent_model.pool is not None
    assert cfg.agent_model.pool.models[0].use_proxy is True
    assert cfg.agent_model.pool.models[1].use_proxy is False
    assert cfg.historian_model.use_proxy is True
    assert cfg.summary_model.use_proxy is True
    assert cfg.grok_model.use_proxy is True
    assert cfg.embedding_model.use_proxy is True
    assert cfg.rerank_model.use_proxy is True
    assert cfg.models_image_gen.use_proxy is True
    assert cfg.models_image_edit.use_proxy is True


def test_scoped_proxy_env_vars_enable_scoped_switches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_proxy_env(monkeypatch)
    monkeypatch.setenv("SEARCH_USE_PROXY", "true")
    monkeypatch.setenv("GITHUB_USE_PROXY", "true")
    monkeypatch.setenv("CHAT_MODEL_USE_PROXY", "true")
    monkeypatch.setenv("IMAGE_GEN_MODEL_USE_PROXY", "true")

    cfg = Config.from_mapping(_minimal_mapping(), strict=False)

    assert cfg.search_use_proxy is True
    assert cfg.github_use_proxy is True
    assert cfg.chat_model.use_proxy is True
    assert cfg.models_image_gen.use_proxy is True
    assert cfg.render_use_proxy is False
    assert cfg.agent_model.use_proxy is False
