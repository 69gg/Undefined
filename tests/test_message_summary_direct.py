from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from Undefined.ai.client import AIClient, _resolve_summary_model_config
from Undefined.ai.summaries import SummaryService
from Undefined.config.models import AgentModelConfig
from Undefined.services.message_summary_fetch import fetch_session_messages


def _agent_config(model_name: str = "agent-model") -> AgentModelConfig:
    return AgentModelConfig(
        api_url="https://api.example.com/v1",
        api_key="key",
        model_name=model_name,
        max_tokens=4096,
    )


def test_fetch_session_messages_returns_empty_when_no_history() -> None:
    history_manager = MagicMock()
    history_manager.get_recent.return_value = []

    result = fetch_session_messages(
        history_manager,
        group_id=123,
        user_id=456,
        count=10,
    )

    assert result == ""


def test_fetch_session_messages_invalid_time_range() -> None:
    history_manager = MagicMock()

    result = fetch_session_messages(
        history_manager,
        group_id=123,
        user_id=456,
        time_range="bad",
    )

    assert result.startswith("无法解析时间范围")


@pytest.mark.asyncio
async def test_summarize_command_session_uses_queued_llm_without_tools() -> None:
    ai_client = cast(Any, AIClient.__new__(AIClient))
    ai_client.runtime_config = SimpleNamespace(
        summary_model_configured=True,
        summary_model=_agent_config("summary-model"),
    )
    ai_client.agent_config = _agent_config()
    ai_client._summary_service = AsyncMock()
    ai_client._summary_service.build_message_summary_messages = AsyncMock(
        return_value=[
            {"role": "system", "content": "system"},
            {"role": "user", "content": "user"},
        ]
    )
    ai_client.count_tokens = MagicMock(return_value=100)
    ai_client.split_messages_by_tokens = MagicMock()
    ai_client.merge_summaries = AsyncMock()
    ai_client.submit_queued_llm_call = AsyncMock(
        return_value={"choices": [{"message": {"content": "总结结果"}}]}
    )

    history_manager = MagicMock()
    with patch(
        "Undefined.ai.client.fetch_session_messages",
        return_value="共获取 2 条消息\n\n<message>...</message>",
    ):
        result = await ai_client.summarize_command_session(
            history_manager,
            group_id=123,
            user_id=456,
            count=2,
            instruction="请总结最近 2 条聊天消息",
        )

    assert result == "总结结果"
    ai_client.submit_queued_llm_call.assert_called_once()
    call_kwargs = ai_client.submit_queued_llm_call.call_args.kwargs
    assert call_kwargs["tools"] is None
    assert call_kwargs["call_type"] == "message_summary"
    assert call_kwargs["model_config"].model_name == "summary-model"


@pytest.mark.asyncio
async def test_summarize_command_session_splits_long_history() -> None:
    ai_client = cast(Any, AIClient.__new__(AIClient))
    ai_client.runtime_config = None
    ai_client.agent_config = _agent_config("agent-fallback")
    ai_client._summary_service = AsyncMock()
    ai_client._summary_service.build_message_summary_messages = AsyncMock(
        side_effect=lambda text, instruction: [
            {"role": "system", "content": "system"},
            {"role": "user", "content": f"{instruction}\n{text}"},
        ]
    )
    ai_client.count_tokens = MagicMock(return_value=10000)
    ai_client.split_messages_by_tokens = MagicMock(return_value=["chunk-1", "chunk-2"])
    ai_client.merge_summaries = AsyncMock(return_value="合并总结")
    ai_client.submit_queued_llm_call = AsyncMock(
        side_effect=[
            {"choices": [{"message": {"content": "part-1"}}]},
            {"choices": [{"message": {"content": "part-2"}}]},
        ]
    )

    history_manager = MagicMock()
    with patch(
        "Undefined.ai.client.fetch_session_messages",
        return_value="很长的聊天记录",
    ):
        result = await ai_client.summarize_command_session(
            history_manager,
            group_id=123,
            user_id=456,
            count=100,
            instruction="请总结",
        )

    assert result == "合并总结"
    assert ai_client.submit_queued_llm_call.call_count == 2
    ai_client.merge_summaries.assert_awaited_once_with(["part-1", "part-2"])


@pytest.mark.asyncio
async def test_summary_service_summarize_message_history() -> None:
    requester = AsyncMock()
    requester.request = AsyncMock(
        return_value={"choices": [{"message": {"content": "直连总结"}}]}
    )
    service = SummaryService(
        requester,
        _agent_config("summary-model"),
        MagicMock(),
    )

    with patch.object(
        service,
        "build_message_summary_messages",
        new=AsyncMock(
            return_value=[
                {"role": "system", "content": "system"},
                {"role": "user", "content": "user"},
            ]
        ),
    ):
        result = await service.summarize_message_history("messages", "instruction")

    assert result == "直连总结"
    requester.request.assert_awaited_once()
    call_kwargs = requester.request.call_args.kwargs
    assert call_kwargs["call_type"] == "message_summary"


def test_resolve_summary_model_falls_back_to_agent() -> None:
    agent = _agent_config()
    runtime_config = cast(
        Any,
        SimpleNamespace(summary_model_configured=False),
    )
    assert _resolve_summary_model_config(runtime_config, agent) is agent
