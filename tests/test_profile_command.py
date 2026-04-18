from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from Undefined.services.commands.context import CommandContext
from Undefined.skills.commands.profile.handler import execute as profile_execute


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
    cognitive_service: Any = None,
    scope: str = "group",
    group_id: int = 123456,
    sender_id: int = 10002,
    user_id: int | None = None,
) -> CommandContext:
    stub = cast(Any, SimpleNamespace())
    if sender is None:
        sender = _DummySender()
    return CommandContext(
        group_id=group_id,
        sender_id=sender_id,
        config=stub,
        sender=cast(Any, sender),
        ai=stub,
        faq_storage=stub,
        onebot=stub,
        security=stub,
        queue_manager=None,
        rate_limiter=None,
        dispatcher=stub,
        registry=stub,
        scope=scope,
        user_id=user_id,
        cognitive_service=cognitive_service,
    )


# -- Private chat tests --


@pytest.mark.asyncio
async def test_profile_private_own_profile_found() -> None:
    """Private chat, own profile found → sends profile via send_private_message."""
    sender = _DummySender()
    cognitive_service = AsyncMock()
    cognitive_service.get_profile = AsyncMock(return_value="这是一个用户侧写")

    context = _build_context(
        sender=sender,
        cognitive_service=cognitive_service,
        scope="private",
        group_id=0,
        sender_id=99999,
        user_id=99999,
    )

    await profile_execute([], context)

    assert len(sender.private_messages) == 1
    assert sender.private_messages[0][0] == 99999
    assert "这是一个用户侧写" in sender.private_messages[0][1]
    cognitive_service.get_profile.assert_called_once_with("users", "99999")


@pytest.mark.asyncio
async def test_profile_private_own_profile_not_found() -> None:
    """Private chat, own profile not found → sends '暂无侧写数据'."""
    sender = _DummySender()
    cognitive_service = AsyncMock()
    cognitive_service.get_profile = AsyncMock(return_value="")

    context = _build_context(
        sender=sender,
        cognitive_service=cognitive_service,
        scope="private",
        group_id=0,
        sender_id=88888,
        user_id=88888,
    )

    await profile_execute([], context)

    assert len(sender.private_messages) == 1
    assert "📭 暂无侧写数据" in sender.private_messages[0][1]


@pytest.mark.asyncio
async def test_profile_private_group_subcommand_rejected() -> None:
    """Private chat, `/profile group` rejected → sends error message."""
    sender = _DummySender()
    cognitive_service = AsyncMock()

    context = _build_context(
        sender=sender,
        cognitive_service=cognitive_service,
        scope="private",
        group_id=0,
        sender_id=77777,
        user_id=77777,
    )

    await profile_execute(["group"], context)

    assert len(sender.private_messages) == 1
    assert "❌ 私聊中不支持查看群聊侧写" in sender.private_messages[0][1]
    cognitive_service.get_profile.assert_not_called()


# -- Group chat tests --


@pytest.mark.asyncio
async def test_profile_group_own_profile() -> None:
    """Group chat, own profile → sends profile via send_group_message."""
    sender = _DummySender()
    cognitive_service = AsyncMock()
    cognitive_service.get_profile = AsyncMock(return_value="群成员侧写数据")

    context = _build_context(
        sender=sender,
        cognitive_service=cognitive_service,
        scope="group",
        group_id=123456,
        sender_id=55555,
    )

    await profile_execute([], context)

    assert len(sender.group_messages) == 1
    assert sender.group_messages[0][0] == 123456
    assert "群成员侧写数据" in sender.group_messages[0][1]
    cognitive_service.get_profile.assert_called_once_with("users", "55555")


@pytest.mark.asyncio
async def test_profile_group_profile_subcommand() -> None:
    """Group chat, `/profile group` → sends group profile via send_group_message."""
    sender = _DummySender()
    cognitive_service = AsyncMock()
    cognitive_service.get_profile = AsyncMock(return_value="群聊整体侧写")

    context = _build_context(
        sender=sender,
        cognitive_service=cognitive_service,
        scope="group",
        group_id=654321,
        sender_id=44444,
    )

    await profile_execute(["GROUP"], context)  # Test case-insensitive

    assert len(sender.group_messages) == 1
    assert sender.group_messages[0][0] == 654321
    assert "群聊整体侧写" in sender.group_messages[0][1]
    cognitive_service.get_profile.assert_called_once_with("groups", "654321")


@pytest.mark.asyncio
async def test_profile_group_profile_not_found() -> None:
    """Group chat, group profile not found → sends '暂无群聊侧写数据'."""
    sender = _DummySender()
    cognitive_service = AsyncMock()
    cognitive_service.get_profile = AsyncMock(return_value=None)

    context = _build_context(
        sender=sender,
        cognitive_service=cognitive_service,
        scope="group",
        group_id=111111,
        sender_id=33333,
    )

    await profile_execute(["group"], context)

    assert len(sender.group_messages) == 1
    assert "📭 暂无群聊侧写数据" in sender.group_messages[0][1]


# -- Edge cases --


@pytest.mark.asyncio
async def test_profile_no_cognitive_service() -> None:
    """No cognitive_service → sends '侧写服务未启用'."""
    sender = _DummySender()

    context = _build_context(
        sender=sender,
        cognitive_service=None,
        scope="group",
        group_id=123456,
        sender_id=22222,
    )

    await profile_execute([], context)

    assert len(sender.group_messages) == 1
    assert "❌ 侧写服务未启用" in sender.group_messages[0][1]


@pytest.mark.asyncio
async def test_profile_truncation() -> None:
    """Profile > 3000 chars gets truncated."""
    sender = _DummySender()
    cognitive_service = AsyncMock()
    long_profile = "A" * 3500  # Longer than 3000 chars
    cognitive_service.get_profile = AsyncMock(return_value=long_profile)

    context = _build_context(
        sender=sender,
        cognitive_service=cognitive_service,
        scope="group",
        group_id=123456,
        sender_id=11111,
    )

    await profile_execute([], context)

    assert len(sender.group_messages) == 1
    message = sender.group_messages[0][1]
    assert len(message) <= 3100  # 3000 + truncation notice
    assert "[侧写过长,已截断]" in message
    assert message.count("A") == 3000  # Exactly 3000 'A's before truncation
