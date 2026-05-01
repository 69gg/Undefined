"""FAQ 合并命令 handler 单元测试"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from Undefined.faq import FAQ
from Undefined.services.command import CommandDispatcher
from Undefined.services.commands.context import CommandContext
from Undefined.skills.commands.faq import handler as faq_handler


class _DummySender:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str, bool]] = []

    async def send_group_message(
        self, group_id: int, message: str, mark_sent: bool = False
    ) -> None:
        self.messages.append((group_id, message, mark_sent))


def _make_faq(**overrides: Any) -> FAQ:
    defaults: dict[str, str | int] = dict(
        id="20241205-001",
        group_id=10001,
        target_qq=12345,
        start_time="2024-12-05",
        end_time="2024-12-06",
        created_at="2024-12-05T10:00:00",
        title="测试FAQ",
        content="这是FAQ内容",
    )
    defaults.update(overrides)
    return FAQ(**defaults)  # type: ignore[arg-type]


def _build_context(
    sender: _DummySender,
    *,
    group_id: int = 10001,
    sender_id: int = 10002,
    is_admin: bool = False,
    is_superadmin: bool = False,
    faq_storage: Any | None = None,
) -> CommandContext:
    config = cast(
        Any,
        SimpleNamespace(
            is_admin=lambda _sid: is_admin,
            is_superadmin=lambda _sid: is_superadmin,
        ),
    )
    storage = faq_storage or cast(Any, SimpleNamespace())
    stub = cast(Any, SimpleNamespace())
    return CommandContext(
        group_id=group_id,
        sender_id=sender_id,
        config=config,
        sender=cast(Any, sender),
        ai=stub,
        faq_storage=storage,
        onebot=stub,
        security=stub,
        queue_manager=None,
        rate_limiter=None,
        dispatcher=stub,
        registry=cast(Any, SimpleNamespace()),
        scope="group",
    )


# ---------------------------------------------------------------------------
# 自动推断
# ---------------------------------------------------------------------------


def test_infer_no_args_returns_ls() -> None:
    subcmd, sub_args = faq_handler._infer_subcommand([])
    assert subcmd == "ls"
    assert sub_args == []


def test_infer_id_format_returns_view() -> None:
    subcmd, sub_args = faq_handler._infer_subcommand(["20241205-001"])
    assert subcmd == "view"
    assert sub_args == ["20241205-001"]


def test_infer_non_id_format_returns_search() -> None:
    subcmd, sub_args = faq_handler._infer_subcommand(["登录"])
    assert subcmd == "search"
    assert sub_args == ["登录"]


def test_infer_multi_word_non_id_returns_search() -> None:
    subcmd, sub_args = faq_handler._infer_subcommand(["数据", "导入"])
    assert subcmd == "search"
    assert sub_args == ["数据", "导入"]


# ---------------------------------------------------------------------------
# ls 子命令
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ls_shows_faq_list() -> None:
    sender = _DummySender()
    storage = cast(
        Any,
        SimpleNamespace(
            list_all=AsyncMock(
                return_value=[
                    _make_faq(id="20241205-001", title="FAQ甲"),
                    _make_faq(id="20241206-002", title="FAQ乙"),
                ]
            )
        ),
    )
    context = _build_context(sender, faq_storage=storage)

    await faq_handler.execute([], context)

    output = sender.messages[-1][1]
    assert "FAQ 列表" in output
    assert "20241205-001" in output
    assert "FAQ甲" in output
    assert "20241206-002" in output
    assert "FAQ乙" in output


@pytest.mark.asyncio
async def test_ls_shows_empty() -> None:
    sender = _DummySender()
    storage = cast(Any, SimpleNamespace(list_all=AsyncMock(return_value=[])))
    context = _build_context(sender, faq_storage=storage)

    await faq_handler.execute([], context)

    output = sender.messages[-1][1]
    assert "没有保存的 FAQ" in output


@pytest.mark.asyncio
async def test_ls_explicit_subcommand() -> None:
    sender = _DummySender()
    storage = cast(Any, SimpleNamespace(list_all=AsyncMock(return_value=[])))
    context = _build_context(sender, faq_storage=storage)

    await faq_handler.execute(["ls"], context)

    output = sender.messages[-1][1]
    assert "没有保存的 FAQ" in output


# ---------------------------------------------------------------------------
# view 子命令
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_view_by_id_inferred() -> None:
    sender = _DummySender()
    faq = _make_faq()
    storage = cast(Any, SimpleNamespace(get=AsyncMock(return_value=faq)))
    context = _build_context(sender, faq_storage=storage)

    await faq_handler.execute(["20241205-001"], context)

    output = sender.messages[-1][1]
    assert "FAQ: 测试FAQ" in output
    assert "20241205-001" in output


@pytest.mark.asyncio
async def test_view_explicit_subcommand() -> None:
    sender = _DummySender()
    faq = _make_faq()
    storage = cast(Any, SimpleNamespace(get=AsyncMock(return_value=faq)))
    context = _build_context(sender, faq_storage=storage)

    await faq_handler.execute(["view", "20241205-001"], context)

    output = sender.messages[-1][1]
    assert "FAQ: 测试FAQ" in output


@pytest.mark.asyncio
async def test_view_not_found() -> None:
    sender = _DummySender()
    storage = cast(Any, SimpleNamespace(get=AsyncMock(return_value=None)))
    context = _build_context(sender, faq_storage=storage)

    await faq_handler.execute(["view", "99999999-999"], context)

    output = sender.messages[-1][1]
    assert "FAQ 不存在" in output


@pytest.mark.asyncio
async def test_view_no_args_shows_usage() -> None:
    sender = _DummySender()
    context = _build_context(sender)

    await faq_handler.execute(["view"], context)

    output = sender.messages[-1][1]
    assert "用法" in output


# ---------------------------------------------------------------------------
# search 子命令
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_by_keyword_inferred() -> None:
    sender = _DummySender()
    faq = _make_faq(title="登录问题")
    storage = cast(Any, SimpleNamespace(search=AsyncMock(return_value=[faq])))
    context = _build_context(sender, faq_storage=storage)

    await faq_handler.execute(["登录"], context)

    output = sender.messages[-1][1]
    assert "搜索" in output
    assert "登录" in output


@pytest.mark.asyncio
async def test_search_explicit_subcommand() -> None:
    sender = _DummySender()
    storage = cast(Any, SimpleNamespace(search=AsyncMock(return_value=[])))
    context = _build_context(sender, faq_storage=storage)

    await faq_handler.execute(["search", "关键词"], context)

    output = sender.messages[-1][1]
    assert "未找到" in output


@pytest.mark.asyncio
async def test_search_no_args_shows_usage() -> None:
    sender = _DummySender()
    context = _build_context(sender)

    await faq_handler.execute(["search"], context)

    output = sender.messages[-1][1]
    assert "用法" in output


# ---------------------------------------------------------------------------
# del 子命令
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_del_requires_admin() -> None:
    sender = _DummySender()
    context = _build_context(sender, is_admin=False, is_superadmin=False)

    await faq_handler.execute(["del", "20241205-001"], context)

    output = sender.messages[-1][1]
    assert "权限不足" in output


@pytest.mark.asyncio
async def test_del_succeeds_as_admin() -> None:
    sender = _DummySender()
    faq = _make_faq()
    storage = cast(
        Any,
        SimpleNamespace(
            get=AsyncMock(return_value=faq),
            delete=AsyncMock(return_value=True),
        ),
    )
    context = _build_context(sender, is_admin=True, faq_storage=storage)

    await faq_handler.execute(["del", "20241205-001"], context)

    output = sender.messages[-1][1]
    assert "已删除" in output


@pytest.mark.asyncio
async def test_del_succeeds_as_superadmin() -> None:
    sender = _DummySender()
    faq = _make_faq()
    storage = cast(
        Any,
        SimpleNamespace(
            get=AsyncMock(return_value=faq),
            delete=AsyncMock(return_value=True),
        ),
    )
    context = _build_context(
        sender, is_admin=False, is_superadmin=True, faq_storage=storage
    )

    await faq_handler.execute(["del", "20241205-001"], context)

    output = sender.messages[-1][1]
    assert "已删除" in output


@pytest.mark.asyncio
async def test_del_not_found() -> None:
    sender = _DummySender()
    storage = cast(Any, SimpleNamespace(get=AsyncMock(return_value=None)))
    context = _build_context(sender, is_admin=True, faq_storage=storage)

    await faq_handler.execute(["del", "99999999-999"], context)

    output = sender.messages[-1][1]
    assert "FAQ 不存在" in output


@pytest.mark.asyncio
async def test_del_no_args_shows_usage() -> None:
    sender = _DummySender()
    context = _build_context(sender, is_admin=True)

    await faq_handler.execute(["del"], context)

    output = sender.messages[-1][1]
    assert "用法" in output


# ---------------------------------------------------------------------------
# 注册与别名
# ---------------------------------------------------------------------------


def test_faq_command_is_registered() -> None:
    dispatcher = CommandDispatcher(
        config=cast(
            Any,
            SimpleNamespace(is_superadmin=lambda _x: False, is_admin=lambda _x: False),
        ),
        sender=cast(Any, _DummySender()),
        ai=cast(Any, SimpleNamespace()),
        faq_storage=cast(Any, SimpleNamespace()),
        onebot=cast(Any, SimpleNamespace()),
        security=cast(Any, SimpleNamespace(rate_limiter=None)),
    )

    meta = dispatcher.command_registry.resolve("faq")
    assert meta is not None
    assert meta.allow_in_private is False
    assert "f" in meta.aliases


def test_faq_alias_f_resolves() -> None:
    dispatcher = CommandDispatcher(
        config=cast(
            Any,
            SimpleNamespace(is_superadmin=lambda _x: False, is_admin=lambda _x: False),
        ),
        sender=cast(Any, _DummySender()),
        ai=cast(Any, SimpleNamespace()),
        faq_storage=cast(Any, SimpleNamespace()),
        onebot=cast(Any, SimpleNamespace()),
        security=cast(Any, SimpleNamespace(rate_limiter=None)),
    )

    meta = dispatcher.command_registry.resolve("f")
    assert meta is not None
    assert meta.name == "faq"
