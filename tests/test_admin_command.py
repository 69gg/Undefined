from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, call

import pytest

from Undefined.services.command import CommandDispatcher
from Undefined.services.commands.context import CommandContext
from Undefined.skills.commands.admin.handler import execute


class _DummySender:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str, bool]] = []

    async def send_group_message(
        self,
        group_id: int,
        message: str,
        mark_sent: bool = False,
    ) -> None:
        self.messages.append((group_id, message, mark_sent))


def _build_context(
    *,
    config: Any,
    onebot: Any,
    sender: _DummySender,
) -> CommandContext:
    stub = cast(Any, SimpleNamespace())
    return CommandContext(
        group_id=12345,
        sender_id=54321,
        config=cast(Any, config),
        sender=cast(Any, sender),
        ai=stub,
        faq_storage=stub,
        onebot=cast(Any, onebot),
        security=stub,
        queue_manager=None,
        rate_limiter=None,
        dispatcher=stub,
        registry=stub,
    )


@pytest.mark.asyncio
async def test_admin_ls_outputs_names_without_qq_leakage() -> None:
    sender = _DummySender()
    onebot = SimpleNamespace(
        get_group_member_list=AsyncMock(
            return_value=[
                {"user_id": 10001, "card": "超管群名片", "nickname": "超管昵称"},
                {"user_id": 10002, "card": "", "nickname": "群管理员"},
            ]
        ),
        get_stranger_info=AsyncMock(return_value={"nickname": "QQ管理员"}),
    )
    config = SimpleNamespace(superadmin_qq=10001, admin_qqs=[10001, 10002, 10003])
    context = _build_context(config=config, onebot=onebot, sender=sender)

    await execute([], context)

    assert sender.messages
    output = sender.messages[-1][1]
    assert "👑 超级管理员: 超管群名片" in output
    assert "- 群管理员" in output
    assert "- QQ管理员" in output
    assert "10001" not in output
    assert "10002" not in output
    assert "10003" not in output
    onebot.get_group_member_list.assert_awaited_once_with(12345)
    onebot.get_stranger_info.assert_awaited_once_with(10003)


@pytest.mark.asyncio
async def test_admin_ls_falls_back_to_unknown_name_without_exposing_qq() -> None:
    sender = _DummySender()
    onebot = SimpleNamespace(
        get_group_member_list=AsyncMock(side_effect=RuntimeError("boom")),
        get_stranger_info=AsyncMock(return_value={}),
    )
    config = SimpleNamespace(superadmin_qq=20001, admin_qqs=[20001, 20002])
    context = _build_context(config=config, onebot=onebot, sender=sender)

    await execute([], context)

    assert sender.messages
    output = sender.messages[-1][1]
    assert "未知成员" in output
    assert "20001" not in output
    assert "20002" not in output
    assert onebot.get_stranger_info.await_args_list == [call(20001), call(20002)]


def test_admin_requires_admin_permission() -> None:
    dispatcher = CommandDispatcher(
        config=cast(Any, SimpleNamespace()),
        sender=cast(Any, _DummySender()),
        ai=cast(Any, SimpleNamespace()),
        faq_storage=cast(Any, SimpleNamespace()),
        onebot=cast(Any, SimpleNamespace()),
        security=cast(Any, SimpleNamespace(rate_limiter=None)),
    )

    meta = dispatcher.command_registry.resolve("admin")

    assert meta is not None
    assert meta.permission == "admin"


def test_admin_subcommands_require_superadmin() -> None:
    """子命令 add/del 必须覆盖为 superadmin；ls 继承顶层 admin。"""
    dispatcher = CommandDispatcher(
        config=cast(Any, SimpleNamespace()),
        sender=cast(Any, _DummySender()),
        ai=cast(Any, SimpleNamespace()),
        faq_storage=cast(Any, SimpleNamespace()),
        onebot=cast(Any, SimpleNamespace()),
        security=cast(Any, SimpleNamespace(rate_limiter=None)),
    )

    meta = dispatcher.command_registry.resolve("admin")
    assert meta is not None
    subs = getattr(meta, "subcommands", {}) or {}
    assert subs["add"].permission == "superadmin"
    assert subs["del"].permission == "superadmin"
    # ls 不显式覆盖：使用顶层 admin
    assert subs["ls"].permission == "admin"


@pytest.mark.asyncio
async def test_admin_add_success_persists_via_config() -> None:
    sender = _DummySender()
    add_admin_calls: list[int] = []

    class _Config:
        superadmin_qq = 10001
        admin_qqs = [10001]

        def is_admin(self, qq: int) -> bool:
            return qq in self.admin_qqs

        def is_superadmin(self, qq: int) -> bool:
            return qq == self.superadmin_qq

        def add_admin(self, qq: int) -> bool:
            add_admin_calls.append(qq)
            self.admin_qqs.append(qq)
            return True

        def remove_admin(self, qq: int) -> bool:  # pragma: no cover - 未触发
            return False

    config = _Config()
    onebot = SimpleNamespace()
    context = _build_context(config=config, onebot=onebot, sender=sender)

    await execute(["add", "30001"], context)

    assert add_admin_calls == [30001]
    assert sender.messages
    assert "已添加管理员: 30001" in sender.messages[-1][1]


@pytest.mark.asyncio
async def test_admin_add_rejects_duplicate_without_calling_config() -> None:
    sender = _DummySender()
    calls: list[int] = []

    class _Config:
        superadmin_qq = 10001
        admin_qqs = [10001, 30001]

        def is_admin(self, qq: int) -> bool:
            return qq in self.admin_qqs

        def is_superadmin(self, qq: int) -> bool:
            return qq == self.superadmin_qq

        def add_admin(self, qq: int) -> bool:  # pragma: no cover - 不应触发
            calls.append(qq)
            return False

        def remove_admin(self, qq: int) -> bool:  # pragma: no cover - 不应触发
            return False

    config = _Config()
    context = _build_context(config=config, onebot=SimpleNamespace(), sender=sender)

    await execute(["add", "30001"], context)

    assert calls == []
    assert "已经是管理员" in sender.messages[-1][1]


@pytest.mark.asyncio
async def test_admin_add_rejects_non_numeric_qq() -> None:
    sender = _DummySender()

    class _Config:
        superadmin_qq = 10001
        admin_qqs = [10001]

        def is_admin(self, qq: int) -> bool:  # pragma: no cover - 不应触发
            return False

        def is_superadmin(self, qq: int) -> bool:  # pragma: no cover
            return False

        def add_admin(self, qq: int) -> bool:  # pragma: no cover - 不应触发
            return False

        def remove_admin(self, qq: int) -> bool:  # pragma: no cover
            return False

    config = _Config()
    context = _build_context(config=config, onebot=SimpleNamespace(), sender=sender)

    await execute(["add", "abc"], context)

    assert "QQ 号格式错误" in sender.messages[-1][1]


@pytest.mark.asyncio
async def test_admin_del_success_removes_admin() -> None:
    sender = _DummySender()
    removed: list[int] = []

    class _Config:
        superadmin_qq = 10001
        admin_qqs = [10001, 30001]

        def is_admin(self, qq: int) -> bool:
            return qq in self.admin_qqs

        def is_superadmin(self, qq: int) -> bool:
            return qq == self.superadmin_qq

        def add_admin(self, qq: int) -> bool:  # pragma: no cover
            return False

        def remove_admin(self, qq: int) -> bool:
            removed.append(qq)
            self.admin_qqs.remove(qq)
            return True

    config = _Config()
    context = _build_context(config=config, onebot=SimpleNamespace(), sender=sender)

    await execute(["del", "30001"], context)

    assert removed == [30001]
    assert "已移除管理员: 30001" in sender.messages[-1][1]


@pytest.mark.asyncio
async def test_admin_del_refuses_to_remove_superadmin() -> None:
    sender = _DummySender()
    removed: list[int] = []

    class _Config:
        superadmin_qq = 10001
        admin_qqs = [10001]

        def is_admin(self, qq: int) -> bool:
            return qq in self.admin_qqs

        def is_superadmin(self, qq: int) -> bool:
            return qq == self.superadmin_qq

        def add_admin(self, qq: int) -> bool:  # pragma: no cover
            return False

        def remove_admin(self, qq: int) -> bool:  # pragma: no cover - 不应触发
            removed.append(qq)
            return True

    config = _Config()
    context = _build_context(config=config, onebot=SimpleNamespace(), sender=sender)

    await execute(["del", "10001"], context)

    assert removed == []
    assert "无法移除超级管理员" in sender.messages[-1][1]


@pytest.mark.asyncio
async def test_admin_del_rejects_non_admin_target() -> None:
    sender = _DummySender()

    class _Config:
        superadmin_qq = 10001
        admin_qqs = [10001]

        def is_admin(self, qq: int) -> bool:
            return qq in self.admin_qqs

        def is_superadmin(self, qq: int) -> bool:
            return qq == self.superadmin_qq

        def add_admin(self, qq: int) -> bool:  # pragma: no cover
            return False

        def remove_admin(self, qq: int) -> bool:  # pragma: no cover
            return False

    config = _Config()
    context = _build_context(config=config, onebot=SimpleNamespace(), sender=sender)

    await execute(["del", "30001"], context)

    assert "不是管理员" in sender.messages[-1][1]


@pytest.mark.asyncio
async def test_admin_unknown_subcommand_shows_usage() -> None:
    sender = _DummySender()

    class _Config:
        superadmin_qq = 10001
        admin_qqs = [10001]

        def is_admin(self, qq: int) -> bool:  # pragma: no cover
            return False

        def is_superadmin(self, qq: int) -> bool:  # pragma: no cover
            return False

        def add_admin(self, qq: int) -> bool:  # pragma: no cover
            return False

        def remove_admin(self, qq: int) -> bool:  # pragma: no cover
            return False

    config = _Config()
    context = _build_context(config=config, onebot=SimpleNamespace(), sender=sender)

    await execute(["foo"], context)

    assert "用法：/admin" in sender.messages[-1][1]
