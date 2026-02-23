from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from Undefined.services.command import CommandDispatcher
from Undefined.services.commands.context import CommandContext
from Undefined.services.commands.registry import CommandRegistry
from Undefined.skills.commands.copyright.handler import execute as copyright_execute
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


@pytest.mark.asyncio
async def test_copyright_command_outputs_required_metadata() -> None:
    sender = _DummySender()
    context = _build_context(CommandRegistry(Path("/tmp/not-used")), sender)

    await copyright_execute([], context)

    assert sender.messages
    output = sender.messages[-1][1]
    assert "风险提示与免责声明" in output
    assert "作者：Null<1708213363@qq.com>" in output
    assert "开源链接：github.com/69gg/Undefined" in output
    assert "PyPI 包：Undefined-bot" in output
    assert "开源 LICENSE：MIT" in output


def test_copyright_aliases_resolve() -> None:
    dispatcher = CommandDispatcher(
        config=cast(Any, SimpleNamespace()),
        sender=cast(Any, _DummySender()),
        ai=cast(Any, SimpleNamespace()),
        faq_storage=cast(Any, SimpleNamespace()),
        onebot=cast(Any, SimpleNamespace()),
        security=cast(Any, SimpleNamespace(rate_limiter=None)),
    )

    assert dispatcher.command_registry.resolve("copyright") is not None
    license_meta = dispatcher.command_registry.resolve("license")
    assert license_meta is not None
    assert license_meta.name == "copyright"


@pytest.mark.asyncio
async def test_help_list_contains_copyright_hint(tmp_path: Path) -> None:
    commands_dir = tmp_path / "commands"
    commands_dir.mkdir(parents=True)
    command_dir = commands_dir / "help"
    command_dir.mkdir(parents=True)
    (command_dir / "config.json").write_text(
        (
            "{\n"
            '  "name": "help",\n'
            '  "description": "帮助",\n'
            '  "usage": "/help",\n'
            '  "example": "/help",\n'
            '  "permission": "public",\n'
            '  "rate_limit": {"user": 0, "admin": 0, "superadmin": 0},\n'
            '  "show_in_help": true,\n'
            '  "order": 10,\n'
            '  "aliases": [],\n'
            '  "help_footer": ["版权与免责声明：/copyright"]\n'
            "}\n"
        ),
        encoding="utf-8",
    )
    (command_dir / "handler.py").write_text(
        (
            "from __future__ import annotations\n\n"
            "from Undefined.services.commands.context import CommandContext\n\n"
            "async def execute(args: list[str], context: CommandContext) -> None:\n"
            "    _ = args\n"
            "    await context.sender.send_group_message(context.group_id, 'ok')\n"
        ),
        encoding="utf-8",
    )

    registry = CommandRegistry(commands_dir)
    registry.load_commands()
    sender = _DummySender()
    context = _build_context(registry, sender)

    await help_execute([], context)

    assert sender.messages
    output = sender.messages[-1][1]
    assert "版权与免责声明：/copyright" in output
