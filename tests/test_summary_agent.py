from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from Undefined.skills.agents.summary_agent.handler import (
    execute as summary_agent_execute,
)


@pytest.mark.asyncio
async def test_summary_agent_normal_execution() -> None:
    """Normal execution → calls run_agent_with_tools with correct params."""
    context: dict[str, Any] = {
        "ai_client": AsyncMock(),
        "history_manager": AsyncMock(),
        "group_id": 123456,
        "user_id": 10002,
        "sender_id": 10002,
        "request_type": "group",
        "runtime_config": None,
        "queue_lane": None,
    }

    with patch(
        "Undefined.skills.agents.summary_agent.handler.run_agent_with_tools",
        new=AsyncMock(return_value="总结结果：讨论了技术话题"),
    ) as mock_run_agent:
        result = await summary_agent_execute(
            {"prompt": "请总结最近 50 条消息"},
            context,
        )

    assert result == "总结结果：讨论了技术话题"
    mock_run_agent.assert_called_once()

    call_kwargs = mock_run_agent.call_args.kwargs
    assert call_kwargs["agent_name"] == "summary_agent"
    assert call_kwargs["user_content"] == "请总结最近 50 条消息"
    assert call_kwargs["empty_user_content_message"] == "请提供您的总结需求"
    assert "消息总结助手" in call_kwargs["default_prompt"]
    assert call_kwargs["context"] is context
    assert isinstance(call_kwargs["agent_dir"], Path)
    assert call_kwargs["max_iterations"] == 10
    assert call_kwargs["tool_error_prefix"] == "错误"


@pytest.mark.asyncio
async def test_summary_agent_empty_prompt() -> None:
    """Empty prompt → returns '请提供您的总结需求'."""
    context: dict[str, Any] = {
        "ai_client": AsyncMock(),
        "history_manager": AsyncMock(),
    }

    with patch(
        "Undefined.skills.agents.summary_agent.handler.run_agent_with_tools",
        new=AsyncMock(return_value="请提供您的总结需求"),
    ) as mock_run_agent:
        result = await summary_agent_execute({"prompt": ""}, context)

    assert result == "请提供您的总结需求"
    mock_run_agent.assert_called_once()
    call_kwargs = mock_run_agent.call_args.kwargs
    assert call_kwargs["user_content"] == ""


@pytest.mark.asyncio
async def test_summary_agent_whitespace_prompt() -> None:
    """Whitespace-only prompt → treated as empty."""
    context: dict[str, Any] = {
        "ai_client": AsyncMock(),
        "history_manager": AsyncMock(),
    }

    with patch(
        "Undefined.skills.agents.summary_agent.handler.run_agent_with_tools",
        new=AsyncMock(return_value="请提供您的总结需求"),
    ) as mock_run_agent:
        result = await summary_agent_execute({"prompt": "   "}, context)

    assert result == "请提供您的总结需求"
    call_kwargs = mock_run_agent.call_args.kwargs
    assert call_kwargs["user_content"] == ""


@pytest.mark.asyncio
async def test_summary_agent_missing_prompt_arg() -> None:
    """Missing 'prompt' arg → defaults to empty string."""
    context: dict[str, Any] = {
        "ai_client": AsyncMock(),
        "history_manager": AsyncMock(),
    }

    with patch(
        "Undefined.skills.agents.summary_agent.handler.run_agent_with_tools",
        new=AsyncMock(return_value="请提供您的总结需求"),
    ) as mock_run_agent:
        result = await summary_agent_execute({}, context)

    assert result == "请提供您的总结需求"
    call_kwargs = mock_run_agent.call_args.kwargs
    assert call_kwargs["user_content"] == ""


@pytest.mark.asyncio
async def test_summary_agent_complex_prompt() -> None:
    """Complex prompt with time range and custom instructions."""
    context: dict[str, Any] = {
        "ai_client": AsyncMock(),
        "history_manager": AsyncMock(),
        "group_id": 654321,
        "user_id": 99999,
    }

    with patch(
        "Undefined.skills.agents.summary_agent.handler.run_agent_with_tools",
        new=AsyncMock(return_value="详细总结内容"),
    ) as mock_run_agent:
        result = await summary_agent_execute(
            {"prompt": "请总结过去 1d 内的聊天消息，重点关注：技术讨论"},
            context,
        )

    assert result == "详细总结内容"
    call_kwargs = mock_run_agent.call_args.kwargs
    assert (
        call_kwargs["user_content"] == "请总结过去 1d 内的聊天消息，重点关注：技术讨论"
    )


@pytest.mark.asyncio
async def test_summary_agent_propagates_exception() -> None:
    """Exception from run_agent_with_tools propagates up."""
    context: dict[str, Any] = {
        "ai_client": AsyncMock(),
        "history_manager": AsyncMock(),
    }

    with patch(
        "Undefined.skills.agents.summary_agent.handler.run_agent_with_tools",
        new=AsyncMock(side_effect=RuntimeError("Agent failure")),
    ):
        with pytest.raises(RuntimeError, match="Agent failure"):
            await summary_agent_execute({"prompt": "test"}, context)
