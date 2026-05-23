from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

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
        ai = AsyncMock()
        ai.summarize_command_session = AsyncMock()
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


def test_parse_args_empty() -> None:
    count, time_range, custom_prompt = _parse_args([])
    assert count == 50
    assert time_range is None
    assert custom_prompt == ""


def test_parse_args_count_only() -> None:
    count, time_range, custom_prompt = _parse_args(["100"])
    assert count == 100
    assert time_range is None
    assert custom_prompt == ""


def test_parse_args_time_range_only() -> None:
    count, time_range, custom_prompt = _parse_args(["1d"])
    assert count is None
    assert time_range == "1d"
    assert custom_prompt == ""


def test_parse_args_count_with_custom_prompt() -> None:
    count, time_range, custom_prompt = _parse_args(["100", "技术讨论"])
    assert count == 100
    assert time_range is None
    assert custom_prompt == "技术讨论"


def test_build_prompt_with_count() -> None:
    prompt = _build_prompt(100, None, "")
    assert "请总结最近 100 条聊天消息" in prompt


def test_build_prompt_with_time_range() -> None:
    prompt = _build_prompt(None, "1d", "")
    assert "请总结过去 1d 内的聊天消息" in prompt


@pytest.mark.asyncio
async def test_summary_no_history_manager() -> None:
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
async def test_summary_direct_call_success() -> None:
    sender = _DummySender()
    history_manager = AsyncMock()
    ai = AsyncMock()
    ai.summarize_command_session = AsyncMock(
        return_value="总结内容：最近讨论了技术话题。"
    )

    context = _build_context(
        sender=sender,
        history_manager=history_manager,
        ai=ai,
        scope="group",
        group_id=123456,
        sender_id=10002,
    )

    await summary_execute(["50"], context)

    assert len(sender.group_messages) == 1
    assert "总结内容：最近讨论了技术话题。" in sender.group_messages[0][1]
    ai.summarize_command_session.assert_called_once_with(
        history_manager,
        group_id=123456,
        user_id=10002,
        count=50,
        time_range=None,
        instruction="请总结最近 50 条聊天消息",
    )


@pytest.mark.asyncio
async def test_summary_direct_call_failure() -> None:
    sender = _DummySender()
    history_manager = AsyncMock()
    ai = AsyncMock()
    ai.summarize_command_session = AsyncMock(side_effect=Exception("LLM error"))

    context = _build_context(
        sender=sender,
        history_manager=history_manager,
        ai=ai,
        scope="group",
        group_id=123456,
        sender_id=10002,
    )

    await summary_execute([], context)

    assert len(sender.group_messages) == 1
    assert "❌ 消息总结失败，请稍后重试" in sender.group_messages[0][1]


@pytest.mark.asyncio
async def test_summary_direct_call_returns_empty() -> None:
    sender = _DummySender()
    history_manager = AsyncMock()
    ai = AsyncMock()
    ai.summarize_command_session = AsyncMock(return_value="   ")

    context = _build_context(
        sender=sender,
        history_manager=history_manager,
        ai=ai,
        scope="group",
        group_id=123456,
        sender_id=10002,
    )

    await summary_execute([], context)

    assert len(sender.group_messages) == 1
    assert "📭 未能生成总结内容" in sender.group_messages[0][1]


@pytest.mark.asyncio
async def test_summary_private_chat() -> None:
    sender = _DummySender()
    history_manager = AsyncMock()
    ai = AsyncMock()
    ai.summarize_command_session = AsyncMock(return_value="私聊总结结果")

    context = _build_context(
        sender=sender,
        history_manager=history_manager,
        ai=ai,
        scope="private",
        group_id=0,
        sender_id=88888,
        user_id=88888,
    )

    await summary_execute(["1d", "重要消息"], context)

    assert len(sender.private_messages) == 1
    assert "私聊总结结果" in sender.private_messages[0][1]
    ai.summarize_command_session.assert_called_once_with(
        history_manager,
        group_id=0,
        user_id=88888,
        count=None,
        time_range="1d",
        instruction="请总结过去 1d 内的聊天消息，重点关注：重要消息",
    )


@pytest.mark.asyncio
async def test_summary_passes_time_range_and_focus() -> None:
    sender = _DummySender()
    history_manager = AsyncMock()
    ai = AsyncMock()
    ai.summarize_command_session = AsyncMock(return_value="总结")

    context = _build_context(
        sender=sender,
        history_manager=history_manager,
        ai=ai,
        scope="group",
        group_id=123456,
        sender_id=10002,
    )

    await summary_execute(["1d", "技术讨论"], context)

    ai.summarize_command_session.assert_called_once_with(
        history_manager,
        group_id=123456,
        user_id=10002,
        count=None,
        time_range="1d",
        instruction="请总结过去 1d 内的聊天消息，重点关注：技术讨论",
    )
