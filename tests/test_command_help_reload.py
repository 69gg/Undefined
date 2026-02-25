from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from Undefined.services.command import CommandDispatcher
from Undefined.services.commands.context import CommandContext
from Undefined.services.commands.registry import CommandRegistry
from Undefined.skills.commands.help.handler import execute as help_execute


class _DummySender:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str, bool]] = []

    async def send_group_message(
        self, group_id: int, message: str, mark_sent: bool = False
    ) -> None:
        self.messages.append((group_id, message, mark_sent))


def _build_context(registry: CommandRegistry, sender: _DummySender) -> CommandContext:
    stub = cast(Any, SimpleNamespace())
    return CommandContext(
        group_id=10001,
        sender_id=10002,
        config=stub,
        sender=cast(Any, sender),
        ai=stub,
        faq_storage=stub,
        onebot=stub,
        security=stub,
        queue_manager=None,
        rate_limiter=None,
        dispatcher=stub,
        registry=registry,
    )


def _write_command(
    base_dir: Path,
    command_dir_name: str,
    *,
    command_name: str,
    description: str = "测试命令",
    usage: str = "/echo",
    example: str = "/echo demo",
    aliases: list[str] | None = None,
    handler_text: str = "v1",
    doc_text: str | None = None,
    allow_in_private: bool = False,
) -> Path:
    command_dir = base_dir / command_dir_name
    command_dir.mkdir(parents=True, exist_ok=True)

    with open(command_dir / "config.json", "w", encoding="utf-8") as f:
        json.dump(
            {
                "name": command_name,
                "description": description,
                "usage": usage,
                "example": example,
                "permission": "public",
                "allow_in_private": allow_in_private,
                "rate_limit": {"user": 0, "admin": 0, "superadmin": 0},
                "show_in_help": True,
                "order": 10,
                "aliases": aliases or [],
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    _write_handler(command_dir / "handler.py", handler_text)

    if doc_text is not None:
        with open(command_dir / "README.md", "w", encoding="utf-8") as f:
            f.write(doc_text)

    return command_dir


def _write_handler(handler_path: Path, message_text: str) -> None:
    with open(handler_path, "w", encoding="utf-8") as f:
        f.write(
            "from __future__ import annotations\n\n"
            "from Undefined.services.commands.context import CommandContext\n\n"
            "async def execute(args: list[str], context: CommandContext) -> None:\n"
            f'    await context.sender.send_group_message(context.group_id, "{message_text}")\n'
        )


@pytest.mark.asyncio
async def test_command_registry_hot_reload_handler_update(tmp_path: Path) -> None:
    commands_dir = tmp_path / "commands"
    commands_dir.mkdir(parents=True)
    command_dir = _write_command(
        commands_dir,
        "echo",
        command_name="echo",
        usage="/echo",
        example="/echo hello",
        handler_text="v1",
    )

    registry = CommandRegistry(commands_dir)
    registry.load_commands()

    sender = _DummySender()
    context = _build_context(registry, sender)

    meta = registry.resolve("echo")
    assert meta is not None
    await registry.execute(meta, [], context)
    assert sender.messages[-1][1] == "v1"

    await asyncio.sleep(0.25)
    _write_handler(command_dir / "handler.py", "v2")

    assert registry.maybe_reload() is True
    sender.messages.clear()

    updated_meta = registry.resolve("echo")
    assert updated_meta is not None
    await registry.execute(updated_meta, [], context)
    assert sender.messages[-1][1] == "v2"


@pytest.mark.asyncio
async def test_help_command_detail_includes_template_and_readme(tmp_path: Path) -> None:
    commands_dir = tmp_path / "commands"
    commands_dir.mkdir(parents=True)
    _write_command(
        commands_dir,
        "foo",
        command_name="foo",
        description="Foo 命令描述",
        usage="/foo <name>",
        example="/foo alice",
        aliases=["f"],
        handler_text="ok",
        doc_text="# Foo 文档\n\n这是 Foo 的详细说明。",
    )

    registry = CommandRegistry(commands_dir)
    registry.load_commands()
    sender = _DummySender()
    context = _build_context(registry, sender)

    await help_execute(["foo"], context)
    output = sender.messages[-1][1]
    assert "命令详情：/foo" in output
    assert "描述：Foo 命令描述" in output
    assert "用法：/foo <name>" in output
    assert "示例：/foo alice" in output
    assert "作用域：仅群聊" in output
    assert "别名：/f" in output
    assert "说明文档：" in output
    assert "这是 Foo 的详细说明。" in output


@pytest.mark.asyncio
async def test_help_list_filters_private_only_commands_in_private_scope(
    tmp_path: Path,
) -> None:
    commands_dir = tmp_path / "commands"
    commands_dir.mkdir(parents=True)
    _write_command(
        commands_dir,
        "open",
        command_name="open",
        usage="/open",
        allow_in_private=True,
        handler_text="ok",
    )
    _write_command(
        commands_dir,
        "grouponly",
        command_name="grouponly",
        usage="/grouponly",
        allow_in_private=False,
        handler_text="ok",
    )

    registry = CommandRegistry(commands_dir)
    registry.load_commands()
    sender = _DummySender()
    stub = cast(Any, SimpleNamespace())
    private_context = CommandContext(
        group_id=0,
        sender_id=10002,
        config=stub,
        sender=cast(Any, sender),
        ai=stub,
        faq_storage=stub,
        onebot=stub,
        security=stub,
        queue_manager=None,
        rate_limiter=None,
        dispatcher=stub,
        registry=registry,
    )

    await help_execute([], private_context)
    output = sender.messages[-1][1]
    assert "当前会话：私聊" in output
    assert "/open（群聊/私聊）" in output
    assert "/grouponly" not in output


@pytest.mark.asyncio
async def test_help_detail_hides_group_only_command_in_private_scope(
    tmp_path: Path,
) -> None:
    commands_dir = tmp_path / "commands"
    commands_dir.mkdir(parents=True)
    _write_command(
        commands_dir,
        "grouponly",
        command_name="grouponly",
        usage="/grouponly",
        allow_in_private=False,
        handler_text="ok",
    )

    registry = CommandRegistry(commands_dir)
    registry.load_commands()
    sender = _DummySender()
    stub = cast(Any, SimpleNamespace())
    private_context = CommandContext(
        group_id=0,
        sender_id=10002,
        config=stub,
        sender=cast(Any, sender),
        ai=stub,
        faq_storage=stub,
        onebot=stub,
        security=stub,
        queue_manager=None,
        rate_limiter=None,
        dispatcher=stub,
        registry=registry,
    )

    await help_execute(["grouponly"], private_context)
    output = sender.messages[-1][1]
    assert "未找到命令" in output


@pytest.mark.asyncio
async def test_dispatch_rejects_help_flag_with_new_help_style() -> None:
    sender = _DummySender()
    config = cast(Any, SimpleNamespace())
    security = cast(Any, SimpleNamespace(rate_limiter=None))
    dispatcher = CommandDispatcher(
        config=config,
        sender=cast(Any, sender),
        ai=cast(Any, SimpleNamespace()),
        faq_storage=cast(Any, SimpleNamespace()),
        onebot=cast(Any, SimpleNamespace()),
        security=security,
    )

    await dispatcher.dispatch(12345, 67890, {"name": "stats", "args": ["--help"]})

    assert sender.messages
    assert "参数 --help 已弃用" in sender.messages[-1][1]
    assert "/help stats" in sender.messages[-1][1]
