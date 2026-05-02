from __future__ import annotations

from types import SimpleNamespace
from typing import cast

from Undefined.ai.client import _resolve_summary_model_config
from Undefined.config import AgentModelConfig, ChatModelConfig, Config


def _chat_config(model_name: str = "chat-model") -> ChatModelConfig:
    return ChatModelConfig(
        api_url="https://api.example.com/v1",
        api_key="key",
        model_name=model_name,
        max_tokens=4096,
    )


def _summary_config(model_name: str = "summary-model") -> AgentModelConfig:
    return AgentModelConfig(
        api_url="https://api.example.com/v1",
        api_key="key",
        model_name=model_name,
        max_tokens=2048,
    )


def test_resolve_summary_model_uses_chat_when_not_configured() -> None:
    chat_config = _chat_config()
    runtime_config = cast(
        Config,
        SimpleNamespace(
            summary_model_configured=False,
            summary_model=_summary_config(),
        ),
    )

    assert _resolve_summary_model_config(runtime_config, chat_config) is chat_config


def test_resolve_summary_model_uses_dedicated_summary_when_configured() -> None:
    chat_config = _chat_config()
    summary_config = _summary_config()
    runtime_config = cast(
        Config,
        SimpleNamespace(
            summary_model_configured=True,
            summary_model=summary_config,
        ),
    )

    assert _resolve_summary_model_config(runtime_config, chat_config) is summary_config
