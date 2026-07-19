from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from Undefined.services.command import CommandDispatcher
from Undefined.services.commands.registry import CommandRegistry
from Undefined.utils import io as async_io


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


class _RouteSender:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str]] = []

    async def send_private_message(
        self,
        user_id: int,
        message: str,
    ) -> None:
        self.messages.append((user_id, message))


async def _write_command(
    base_dir: Path,
    name: str,
    *,
    allow_in_private: bool,
    permission: str = "public",
    handler_statement: str = (
        "await context.sender.send_group_message(context.group_id, 'OK')"
    ),
) -> None:
    command_dir = base_dir / name
    await async_io.ensure_dir(command_dir)
    await async_io.write_text(
        command_dir / "config.json",
        json.dumps(
            {
                "name": name,
                "description": "test",
                "usage": f"/{name}",
                "example": f"/{name}",
                "permission": permission,
                "allow_in_private": allow_in_private,
                "rate_limit": {"user": 0, "admin": 0, "superadmin": 0},
                "show_in_help": True,
                "order": 1,
                "aliases": [],
            },
            ensure_ascii=False,
            indent=2,
        ),
    )
    await async_io.write_text(
        command_dir / "handler.py",
        "from Undefined.services.commands.context import CommandContext\n"
        "async def execute(args: list[str], context: CommandContext) -> None:\n"
        f"    {handler_statement}\n",
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
    await _write_command(commands_dir, "closedcmd", allow_in_private=False)
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
    await _write_command(commands_dir, "opencmd", allow_in_private=True)
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


@pytest.mark.asyncio
async def test_private_command_uses_explicit_route_sender(tmp_path: Path) -> None:
    commands_dir = tmp_path / "commands"
    await _write_command(commands_dir, "routecmd", allow_in_private=True)
    registry = CommandRegistry(commands_dir)
    registry.load_commands()

    sender = _DummySender()
    route_sender = _RouteSender()
    dispatcher = _build_dispatcher_with_registry(registry=registry, sender=sender)

    await dispatcher.dispatch_private(
        user_id=123,
        sender_id=123,
        command={"name": "routecmd", "args": []},
        command_sender=route_sender,
    )

    assert route_sender.messages == [(123, "OK")]
    assert sender.private_messages == []


@pytest.mark.asyncio
async def test_private_command_denial_uses_explicit_route_sender(
    tmp_path: Path,
) -> None:
    commands_dir = tmp_path / "commands"
    await _write_command(
        commands_dir,
        "admincmd",
        allow_in_private=True,
        permission="admin",
    )
    registry = CommandRegistry(commands_dir)
    registry.load_commands()

    sender = _DummySender()
    route_sender = _RouteSender()
    dispatcher = _build_dispatcher_with_registry(registry=registry, sender=sender)
    config = cast(Any, dispatcher.config)
    config.is_admin = lambda _sid: False
    config.is_superadmin = lambda _sid: False

    await dispatcher.dispatch_private(
        user_id=123,
        sender_id=123,
        command={"name": "admincmd", "args": []},
        command_sender=route_sender,
    )

    assert len(route_sender.messages) == 1
    assert "权限不足" in route_sender.messages[0][1]
    assert sender.private_messages == []


@pytest.mark.asyncio
async def test_unknown_private_command_uses_explicit_route_sender(
    tmp_path: Path,
) -> None:
    commands_dir = await async_io.ensure_dir(tmp_path / "commands")
    registry = CommandRegistry(commands_dir)
    registry.load_commands()

    sender = _DummySender()
    route_sender = _RouteSender()
    dispatcher = _build_dispatcher_with_registry(registry=registry, sender=sender)

    await dispatcher.dispatch_private(
        user_id=123,
        sender_id=123,
        command={"name": "missingcmd", "args": []},
        command_sender=route_sender,
    )

    assert len(route_sender.messages) == 1
    assert "未知命令" in route_sender.messages[0][1]
    assert sender.private_messages == []


@pytest.mark.asyncio
async def test_failing_private_command_uses_explicit_route_sender(
    tmp_path: Path,
) -> None:
    commands_dir = tmp_path / "commands"
    await _write_command(
        commands_dir,
        "failcmd",
        allow_in_private=True,
        handler_statement="raise RuntimeError('boom')",
    )
    registry = CommandRegistry(commands_dir)
    registry.load_commands()

    sender = _DummySender()
    route_sender = _RouteSender()
    dispatcher = _build_dispatcher_with_registry(registry=registry, sender=sender)

    await dispatcher.dispatch_private(
        user_id=123,
        sender_id=123,
        command={"name": "failcmd", "args": []},
        command_sender=route_sender,
    )

    assert len(route_sender.messages) == 1
    assert "命令执行失败" in route_sender.messages[0][1]
    assert sender.private_messages == []
