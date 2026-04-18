from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, patch

import pytest

from Undefined.services.commands.context import CommandContext
from Undefined.skills.commands.summary.handler import (
    _build_prompt,
    _parse_args,
    execute as summary_execute,
)


class _DummySender:
    def __init__(self) -> None:
        self.group_messages: list[tuple[int, str]] = []
        self.private_messages: list[tuple[int, str]] = []

    async def send_group_message(
        self, group_id: int, message: str, mark_sent: bool = False
    ) -> None:
        _ = mark_sent
        self.group_messages.append((group_id, message))

    async def send_private_message(
        self,
        user_id: int,
        message: str,
        auto_history: bool = True,
        *,
        mark_sent: bool = True,
    ) -> None:
        _ = (auto_history, mark_sent)
        self.private_messages.append((user_id, message))


def _build_context(
    *,
    sender: _DummySender | None = None,
    history_manager: Any = None,
    scope: str = "group",
    group_id: int = 123456,
    sender_id: int = 10002,
    user_id: int | None = None,
    ai: Any = None,
) -> CommandContext:
    stub = cast(Any, SimpleNamespace())
    if sender is None:
        sender = _DummySender()
    if ai is None:
        ai = stub
    return CommandContext(
        group_id=group_id,
        sender_id=sender_id,
        config=stub,
        sender=cast(Any, sender),
        ai=ai,
        faq_storage=stub,
        onebot=stub,
        security=stub,
        queue_manager=None,
        rate_limiter=None,
        dispatcher=stub,
        registry=stub,
        scope=scope,
        user_id=user_id,
        history_manager=history_manager,
    )


# -- _parse_args unit tests --


def test_parse_args_empty() -> None:
    """Empty args → (50, None, '')."""
    count, time_range, custom_prompt = _parse_args([])
    assert count == 50
    assert time_range is None
    assert custom_prompt == ""


def test_parse_args_count_only() -> None:
    """['100'] → (100, None, '')."""
    count, time_range, custom_prompt = _parse_args(["100"])
    assert count == 100
    assert time_range is None
    assert custom_prompt == ""


def test_parse_args_time_range_only() -> None:
    """['1d'] → (None, '1d', '')."""
    count, time_range, custom_prompt = _parse_args(["1d"])
    assert count is None
    assert time_range == "1d"
    assert custom_prompt == ""


def test_parse_args_count_with_custom_prompt() -> None:
    """['100', '技术讨论'] → (100, None, '技术讨论')."""
    count, time_range, custom_prompt = _parse_args(["100", "技术讨论"])
    assert count == 100
    assert time_range is None
    assert custom_prompt == "技术讨论"


def test_parse_args_time_range_with_custom_prompt() -> None:
    """['1d', '总结技术'] → (None, '1d', '总结技术')."""
    count, time_range, custom_prompt = _parse_args(["1d", "总结技术"])
    assert count is None
    assert time_range == "1d"
    assert custom_prompt == "总结技术"


def test_parse_args_custom_prompt_only() -> None:
    """['技术讨论'] → (50, None, '技术讨论')."""
    count, time_range, custom_prompt = _parse_args(["技术讨论"])
    assert count == 50
    assert time_range is None
    assert custom_prompt == "技术讨论"


def test_parse_args_count_capped_at_500() -> None:
    """['999'] → (500, None, '') (capped)."""
    count, time_range, custom_prompt = _parse_args(["999"])
    assert count == 500
    assert time_range is None
    assert custom_prompt == ""


def test_parse_args_multiple_words_prompt() -> None:
    """['技术', '讨论', '总结'] → (50, None, '技术 讨论 总结')."""
    count, time_range, custom_prompt = _parse_args(["技术", "讨论", "总结"])
    assert count == 50
    assert time_range is None
    assert custom_prompt == "技术 讨论 总结"


# -- _build_prompt unit tests --


def test_build_prompt_with_count() -> None:
    """With count → '请总结最近 X 条聊天消息'."""
    prompt = _build_prompt(100, None, "")
    assert "请总结最近 100 条聊天消息" in prompt


def test_build_prompt_with_time_range() -> None:
    """With time_range → '请总结过去 X 内的聊天消息'."""
    prompt = _build_prompt(None, "1d", "")
    assert "请总结过去 1d 内的聊天消息" in prompt


def test_build_prompt_with_custom_prompt() -> None:
    """With custom_prompt → adds '重点关注：...'."""
    prompt = _build_prompt(50, None, "技术讨论")
    assert "请总结最近 50 条聊天消息" in prompt
    assert "重点关注：技术讨论" in prompt


def test_build_prompt_default_count() -> None:
    """Default count when both are None."""
    prompt = _build_prompt(None, None, "")
    assert "请总结最近 50 条聊天消息" in prompt


def test_build_prompt_time_range_and_custom() -> None:
    """Time range with custom prompt."""
    prompt = _build_prompt(None, "6h", "重要公告")
    assert "请总结过去 6h 内的聊天消息" in prompt
    assert "重点关注：重要公告" in prompt


# -- Command execution tests --


@pytest.mark.asyncio
async def test_summary_no_history_manager() -> None:
    """No history_manager → sends error message."""
    sender = _DummySender()
    context = _build_context(
        sender=sender,
        history_manager=None,
        scope="group",
        group_id=123456,
        sender_id=10002,
    )

    await summary_execute([], context)

    assert len(sender.group_messages) == 1
    assert "❌ 历史记录管理器未配置" in sender.group_messages[0][1]


@pytest.mark.asyncio
async def test_summary_agent_call_success() -> None:
    """Agent call success → result forwarded to user."""
    sender = _DummySender()
    history_manager = AsyncMock()
    ai = AsyncMock()
    ai.runtime_config = None

    context = _build_context(
        sender=sender,
        history_manager=history_manager,
        ai=ai,
        scope="group",
        group_id=123456,
        sender_id=10002,
    )

    with patch(
        "Undefined.skills.agents.summary_agent.handler.execute",
        new=AsyncMock(return_value="总结内容：最近讨论了技术话题。"),
    ) as mock_agent:
        await summary_execute(["50"], context)

    assert len(sender.group_messages) == 2
    assert "📝 正在总结消息，请稍候..." in sender.group_messages[0][1]
    assert "总结内容：最近讨论了技术话题。" in sender.group_messages[1][1]
    mock_agent.assert_called_once()
    call_args = mock_agent.call_args
    assert call_args[0][0]["prompt"] == "请总结最近 50 条聊天消息"


@pytest.mark.asyncio
async def test_summary_agent_call_failure() -> None:
    """Agent call failure → sends error message."""
    sender = _DummySender()
    history_manager = AsyncMock()
    ai = AsyncMock()

    context = _build_context(
        sender=sender,
        history_manager=history_manager,
        ai=ai,
        scope="group",
        group_id=123456,
        sender_id=10002,
    )

    with patch(
        "Undefined.skills.agents.summary_agent.handler.execute",
        new=AsyncMock(side_effect=Exception("Agent error")),
    ):
        await summary_execute([], context)

    assert len(sender.group_messages) == 2
    assert "📝 正在总结消息，请稍候..." in sender.group_messages[0][1]
    assert "❌ 消息总结失败，请稍后重试" in sender.group_messages[1][1]


@pytest.mark.asyncio
async def test_summary_agent_returns_empty() -> None:
    """Agent returns empty result → sends '未能生成总结内容'."""
    sender = _DummySender()
    history_manager = AsyncMock()
    ai = AsyncMock()

    context = _build_context(
        sender=sender,
        history_manager=history_manager,
        ai=ai,
        scope="group",
        group_id=123456,
        sender_id=10002,
    )

    with patch(
        "Undefined.skills.agents.summary_agent.handler.execute",
        new=AsyncMock(return_value="   "),
    ):
        await summary_execute([], context)

    assert len(sender.group_messages) == 2
    assert "📭 未能生成总结内容" in sender.group_messages[1][1]


@pytest.mark.asyncio
async def test_summary_private_chat() -> None:
    """Private chat → uses send_private_message."""
    sender = _DummySender()
    history_manager = AsyncMock()
    ai = AsyncMock()

    context = _build_context(
        sender=sender,
        history_manager=history_manager,
        ai=ai,
        scope="private",
        group_id=0,
        sender_id=88888,
        user_id=88888,
    )

    with patch(
        "Undefined.skills.agents.summary_agent.handler.execute",
        new=AsyncMock(return_value="私聊总结结果"),
    ):
        await summary_execute(["1d", "重要消息"], context)

    assert len(sender.private_messages) == 2
    assert "📝 正在总结消息，请稍候..." in sender.private_messages[0][1]
    assert "私聊总结结果" in sender.private_messages[1][1]


@pytest.mark.asyncio
async def test_summary_passes_correct_context_to_agent() -> None:
    """Agent receives correct context parameters."""
    sender = _DummySender()
    history_manager = AsyncMock()
    ai = AsyncMock()
    ai.runtime_config = SimpleNamespace(some_config="value")

    context = _build_context(
        sender=sender,
        history_manager=history_manager,
        ai=ai,
        scope="group",
        group_id=999888,
        sender_id=777666,
        user_id=None,
    )

    with patch(
        "Undefined.skills.agents.summary_agent.handler.execute",
        new=AsyncMock(return_value="总结"),
    ) as mock_agent:
        await summary_execute([], context)

    call_args = mock_agent.call_args
    agent_context = call_args[0][1]
    assert agent_context["ai_client"] is ai
    assert agent_context["history_manager"] is history_manager
    assert agent_context["group_id"] == 999888
    assert agent_context["sender_id"] == 777666
    assert agent_context["user_id"] == 777666
    assert agent_context["request_type"] == "group"
    assert agent_context["runtime_config"] is ai.runtime_config
