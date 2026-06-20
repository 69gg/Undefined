from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from aiohttp import web

from Undefined.api import RuntimeAPIContext, RuntimeAPIServer
from Undefined.services.commands.registry import CommandRegistry


def _write_command(
    commands_dir: Path,
    directory: str,
    config: dict[str, Any],
) -> None:
    command_dir = commands_dir / directory
    command_dir.mkdir(parents=True)
    (command_dir / "config.json").write_text(
        json.dumps(config, ensure_ascii=False),
        encoding="utf-8",
    )
    (command_dir / "handler.py").write_text(
        "from Undefined.services.commands.context import CommandContext\n\n"
        "async def execute(args: list[str], context: CommandContext) -> None:\n"
        "    _ = args, context\n",
        encoding="utf-8",
    )


def _config() -> Any:
    config = cast(
        Any,
        SimpleNamespace(
            api=SimpleNamespace(
                enabled=True,
                host="127.0.0.1",
                port=8788,
                auth_key="changeme",
                openapi_enabled=True,
            ),
            superadmin_qq=10001,
            bot_qq=20002,
            admin_qqs=[10001],
        ),
    )
    config.is_superadmin = lambda user_id: int(user_id) == 10001
    config.is_admin = lambda user_id: int(user_id) in {10001}
    return config


def _context(registry: CommandRegistry) -> RuntimeAPIContext:
    dispatcher = SimpleNamespace(
        command_registry=registry,
        sender=SimpleNamespace(),
        ai=SimpleNamespace(),
        faq_storage=SimpleNamespace(),
        onebot=SimpleNamespace(),
        security=SimpleNamespace(),
        queue_manager=SimpleNamespace(snapshot=lambda: {}),
        rate_limiter=None,
    )
    return RuntimeAPIContext(
        config_getter=_config,
        onebot=SimpleNamespace(connection_status=lambda: {}),
        ai=SimpleNamespace(memory_storage=SimpleNamespace(count=lambda: 0)),
        command_dispatcher=dispatcher,
        queue_manager=SimpleNamespace(snapshot=lambda: {}),
        history_manager=SimpleNamespace(),
    )


@pytest.mark.asyncio
async def test_commands_api_exposes_changelog_alias_subcommands() -> None:
    commands_dir = Path("src/Undefined/skills/commands")
    registry = CommandRegistry(commands_dir)
    registry.load_commands()
    server = RuntimeAPIServer(_context(registry), host="127.0.0.1", port=8788)

    response = await server._command_detail_handler(
        cast(
            web.Request,
            cast(
                Any,
                SimpleNamespace(
                    query={"scope": "webui"},
                    match_info={"command_name": "cl"},
                ),
            ),
        )
    )
    payload = json.loads(response.text or "{}")
    command = payload["command"]

    assert command["name"] == "changelog"
    assert command["aliases"] == ["cl"]
    subcommands = {item["name"]: item for item in command["subcommands"]}
    assert set(subcommands) == {"latest", "list", "show"}
    assert subcommands["list"]["usage"] == "/changelog list [数量]"
    assert subcommands["show"]["usage"] == "/changelog show <版本号>"
    assert subcommands["latest"]["usage"] == "/changelog latest"


@pytest.mark.asyncio
async def test_commands_api_lists_webui_available_commands_and_subcommands(
    tmp_path: Path,
) -> None:
    commands_dir = tmp_path / "commands"
    commands_dir.mkdir()
    _write_command(
        commands_dir,
        "public_cmd",
        {
            "name": "faq",
            "description": "FAQ 管理",
            "usage": "/faq [ls|view|del]",
            "example": "/faq ls",
            "permission": "public",
            "allow_in_private": True,
            "aliases": ["f"],
            "order": 10,
            "subcommands": {
                "ls": {"description": "列出 FAQ"},
                "del": {
                    "description": "删除 FAQ",
                    "permission": "admin",
                    "args": "<ID>",
                },
            },
        },
    )
    _write_command(
        commands_dir,
        "group_only",
        {
            "name": "bugfix",
            "description": "群聊修复报告",
            "usage": "/bugfix <QQ号> <开始> <结束>",
            "permission": "admin",
            "allow_in_private": False,
            "order": 20,
        },
    )
    registry = CommandRegistry(commands_dir)
    registry.load_commands()
    server = RuntimeAPIServer(_context(registry), host="127.0.0.1", port=8788)

    response = await server._commands_list_handler(
        cast(web.Request, cast(Any, SimpleNamespace(query={"scope": "webui"})))
    )
    payload = json.loads(response.text or "{}")

    assert payload["scope"] == "webui"
    assert payload["execution_scope"] == "private"
    assert payload["sender_id"] == 10001
    assert [item["name"] for item in payload["commands"]] == ["faq"]
    command = payload["commands"][0]
    assert command["trigger"] == "/faq"
    assert command["aliases"] == ["f"]
    assert command["alias_triggers"] == ["/f"]
    assert command["available"] is True
    assert [item["name"] for item in command["subcommands"]] == ["del", "ls"]
    delete_subcommand = command["subcommands"][0]
    assert delete_subcommand["trigger"] == "/faq del"
    assert delete_subcommand["usage"] == "/faq del <ID>"
    assert delete_subcommand["available"] is True


@pytest.mark.asyncio
async def test_command_detail_accepts_alias_and_can_include_unavailable(
    tmp_path: Path,
) -> None:
    commands_dir = tmp_path / "commands"
    commands_dir.mkdir()
    _write_command(
        commands_dir,
        "faq",
        {
            "name": "faq",
            "description": "FAQ 管理",
            "usage": "/faq [ls]",
            "permission": "public",
            "allow_in_private": False,
            "aliases": ["f"],
            "show_in_help": True,
        },
    )
    registry = CommandRegistry(commands_dir)
    registry.load_commands()
    server = RuntimeAPIServer(_context(registry), host="127.0.0.1", port=8788)

    response = await server._command_detail_handler(
        cast(
            web.Request,
            cast(
                Any,
                SimpleNamespace(
                    query={"scope": "webui", "include_unavailable": "true"},
                    match_info={"command_name": "f"},
                ),
            ),
        )
    )
    payload = json.loads(response.text or "{}")

    assert payload["requested_name"] == "f"
    assert payload["command"]["name"] == "faq"
    assert payload["command"]["available"] is False
    assert payload["command"]["unavailable_reason"] == "private_not_allowed"
