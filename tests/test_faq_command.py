"""FAQ 合并命令单元测试（含注册表子命令推断）"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from Undefined.faq import FAQ
from Undefined.services.command import CommandDispatcher
from Undefined.services.commands.context import CommandContext
from Undefined.services.commands.registry import CommandRegistry
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
# 注册表：子命令推断
# ---------------------------------------------------------------------------


def _commands_dir() -> Path:
    return Path(__import__("Undefined").__path__[0]) / "skills" / "commands"


def _load_faq_meta() -> Any:
    registry = CommandRegistry(_commands_dir())
    registry.load_commands()
    return registry.resolve("faq")


def test_registry_faq_has_subcommands() -> None:
    meta = _load_faq_meta()
    assert meta is not None
    assert "ls" in meta.subcommands
    assert "view" in meta.subcommands
    assert "search" in meta.subcommands
    assert "del" in meta.subcommands


def test_registry_faq_has_inference() -> None:
    meta = _load_faq_meta()
    assert meta is not None
    assert meta.inference is not None
    assert meta.inference.default == "ls"
    assert meta.inference.fallback == "search"
    assert len(meta.inference.rules) == 1


def test_registry_resolve_explicit_subcommand() -> None:
    registry = CommandRegistry(_commands_dir())
    registry.load_commands()
    meta = registry.resolve("faq")
    assert meta is not None
    subcmd, args, submeta = registry.resolve_subcommand(meta, ["del", "20241205-001"])
    assert subcmd == "del"
    assert args == ["del", "20241205-001"]
    assert submeta is not None
    assert submeta.permission == "admin"


def test_registry_infer_no_args_default_ls() -> None:
    registry = CommandRegistry(_commands_dir())
    registry.load_commands()
    meta = registry.resolve("faq")
    assert meta is not None
    subcmd, args, submeta = registry.resolve_subcommand(meta, [])
    assert subcmd == "ls"
    assert args == ["ls"]
    assert submeta is not None


def test_registry_infer_id_pattern_view() -> None:
    registry = CommandRegistry(_commands_dir())
    registry.load_commands()
    meta = registry.resolve("faq")
    assert meta is not None
    subcmd, args, submeta = registry.resolve_subcommand(meta, ["20241205-001"])
    assert subcmd == "view"
    assert args == ["view", "20241205-001"]
    assert submeta is not None


def test_registry_inference_rule_requires_full_match() -> None:
    registry = CommandRegistry(_commands_dir())
    registry.load_commands()
    meta = registry.resolve("faq")
    assert meta is not None
    subcmd, args, submeta = registry.resolve_subcommand(meta, ["20241205-001-extra"])
    assert subcmd == "search"
    assert args == ["search", "20241205-001-extra"]
    assert submeta is not None


def test_registry_infer_non_id_fallback_search() -> None:
    registry = CommandRegistry(_commands_dir())
    registry.load_commands()
    meta = registry.resolve("faq")
    assert meta is not None
    subcmd, args, submeta = registry.resolve_subcommand(meta, ["登录"])
    assert subcmd == "search"
    assert args == ["search", "登录"]
    assert submeta is not None


def test_registry_infer_multi_word_fallback_search() -> None:
    registry = CommandRegistry(_commands_dir())
    registry.load_commands()
    meta = registry.resolve("faq")
    assert meta is not None
    subcmd, args, submeta = registry.resolve_subcommand(meta, ["数据", "导入"])
    assert subcmd == "search"
    assert args == ["search", "数据", "导入"]
    assert submeta is not None


# ---------------------------------------------------------------------------
# handler：args 格式为 [subcmd, *sub_args]
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

    await faq_handler.execute(["ls"], context)

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

    await faq_handler.execute(["ls"], context)

    output = sender.messages[-1][1]
    assert "没有保存的 FAQ" in output


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
    assert "del" in meta.subcommands
    assert meta.subcommands["del"].permission == "admin"
    assert meta.inference is not None
    assert meta.inference.default == "ls"


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


def test_legacy_faq_commands_are_not_registered() -> None:
    registry = CommandRegistry(_commands_dir())
    registry.load_commands()

    for name in ("lsfaq", "viewfaq", "searchfaq", "delfaq"):
        assert registry.resolve(name) is None


def test_dispatcher_admin_permission_allows_superadmin() -> None:
    dispatcher = CommandDispatcher(
        config=cast(
            Any,
            SimpleNamespace(
                is_superadmin=lambda sender_id: sender_id == 10002,
                is_admin=lambda _sender_id: False,
            ),
        ),
        sender=cast(Any, _DummySender()),
        ai=cast(Any, SimpleNamespace()),
        faq_storage=cast(Any, SimpleNamespace()),
        onebot=cast(Any, SimpleNamespace()),
        security=cast(Any, SimpleNamespace(rate_limiter=None)),
    )

    assert dispatcher._check_command_permission_raw("admin", 10002) == (True, "管理员")
    assert dispatcher._check_command_permission_raw("admin", 10003) == (False, "管理员")


# ---------------------------------------------------------------------------
# CommandContext.check_permission
# ---------------------------------------------------------------------------


def test_context_check_permission_public() -> None:
    sender = _DummySender()
    context = _build_context(sender)
    assert context.check_permission("public") is True


def test_context_check_permission_admin_as_admin() -> None:
    sender = _DummySender()
    context = _build_context(sender, is_admin=True)
    assert context.check_permission("admin") is True


def test_context_check_permission_admin_as_normal() -> None:
    sender = _DummySender()
    context = _build_context(sender, is_admin=False)
    assert context.check_permission("admin") is False


def test_context_check_permission_superadmin_as_super() -> None:
    sender = _DummySender()
    context = _build_context(sender, is_superadmin=True)
    assert context.check_permission("superadmin") is True


def test_context_check_permission_superadmin_as_admin() -> None:
    sender = _DummySender()
    context = _build_context(sender, is_admin=True, is_superadmin=False)
    assert context.check_permission("superadmin") is False
