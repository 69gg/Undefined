from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

from Undefined.ai.client import AIClient, _resolve_summary_model_config
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


def test_apply_runtime_config_rebuilds_summary_service_for_summary_model() -> None:
    chat_config = _chat_config()
    old_summary_config = _summary_config("summary-old")
    new_summary_config = _summary_config("summary-new")
    old_runtime_config = cast(
        Config,
        SimpleNamespace(
            summary_model_configured=True,
            summary_model=old_summary_config,
        ),
    )
    new_runtime_config = cast(
        Config,
        SimpleNamespace(
            summary_model_configured=True,
            summary_model=new_summary_config,
        ),
    )

    ai_client = cast(Any, AIClient.__new__(AIClient))
    ai_client.chat_config = chat_config
    ai_client.runtime_config = old_runtime_config
    ai_client._requester = object()
    ai_client._token_counter = object()
    ai_client._rebuild_summary_service()
    old_summary_service = ai_client._summary_service

    ai_client.apply_runtime_config(new_runtime_config)

    assert ai_client._summary_service is not old_summary_service
    assert ai_client._summary_service._chat_config is new_summary_config
