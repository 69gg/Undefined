from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from Undefined.services.command import CommandDispatcher
from Undefined.services.commands.registry import CommandRegistry


class _DummySender:
    def __init__(self) -> None:
        self.private_messages: list[tuple[int, str]] = []

    async def send_private_message(self, user_id: int, message: str) -> None:
        self.private_messages.append((user_id, message))

    async def send_group_message(
        self,
        group_id: int,
        message: str,
        mark_sent: bool = False,
    ) -> None:
        _ = group_id, mark_sent
        raise AssertionError(
            "group message should not be used in private dispatch tests"
        )


def _write_command(
    base_dir: Path,
    name: str,
    *,
    allow_in_private: bool,
) -> None:
    command_dir = base_dir / name
    command_dir.mkdir(parents=True, exist_ok=True)
    (command_dir / "config.json").write_text(
        json.dumps(
            {
                "name": name,
                "description": "test",
                "usage": f"/{name}",
                "example": f"/{name}",
                "permission": "public",
                "allow_in_private": allow_in_private,
                "rate_limit": {"user": 0, "admin": 0, "superadmin": 0},
                "show_in_help": True,
                "order": 1,
                "aliases": [],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (command_dir / "handler.py").write_text(
        "from Undefined.services.commands.context import CommandContext\n"
        "async def execute(args: list[str], context: CommandContext) -> None:\n"
        "    await context.sender.send_group_message(context.group_id, 'OK')\n",
        encoding="utf-8",
    )


def _build_dispatcher_with_registry(
    *,
    registry: CommandRegistry,
    sender: _DummySender,
) -> CommandDispatcher:
    rate_limiter = SimpleNamespace(
        check_command=lambda _sid, _cmd, _limit: (True, 0),
        record_command=lambda _sid, _cmd, _limit: None,
    )
    config = SimpleNamespace(
        is_superadmin=lambda _sid: True,
        is_admin=lambda _sid: True,
    )
    security = SimpleNamespace(rate_limiter=rate_limiter)
    dispatcher = CommandDispatcher(
        config=cast(Any, config),
        sender=cast(Any, sender),
        ai=cast(Any, SimpleNamespace()),
        faq_storage=cast(Any, SimpleNamespace()),
        onebot=cast(Any, SimpleNamespace()),
        security=cast(Any, security),
        queue_manager=None,
        rate_limiter=None,
    )
    dispatcher.command_registry = registry
    return dispatcher


@pytest.mark.asyncio
async def test_private_command_rejects_when_not_opened(tmp_path: Path) -> None:
    commands_dir = tmp_path / "commands"
    _write_command(commands_dir, "closedcmd", allow_in_private=False)
    registry = CommandRegistry(commands_dir)
    registry.load_commands()

    sender = _DummySender()
    dispatcher = _build_dispatcher_with_registry(registry=registry, sender=sender)

    await dispatcher.dispatch_private(
        user_id=123,
        sender_id=123,
        command={"name": "closedcmd", "args": []},
    )

    assert sender.private_messages
    assert "不支持私聊使用" in sender.private_messages[-1][1]


@pytest.mark.asyncio
async def test_private_command_executes_when_opened(tmp_path: Path) -> None:
    commands_dir = tmp_path / "commands"
    _write_command(commands_dir, "opencmd", allow_in_private=True)
    registry = CommandRegistry(commands_dir)
    registry.load_commands()

    sender = _DummySender()
    dispatcher = _build_dispatcher_with_registry(registry=registry, sender=sender)

    await dispatcher.dispatch_private(
        user_id=123,
        sender_id=123,
        command={"name": "opencmd", "args": []},
    )

    assert sender.private_messages
    assert sender.private_messages[-1][1] == "OK"
