"""ToolManager 上下文依赖注入测试。"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest

from Undefined.ai.tooling import ToolManager
from Undefined.utils.message_targets import (
    parse_delivery_address,
    resolve_delivery_address,
)
from Undefined.utils.xml import format_message_xml


class _DummySender:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str, bool]] = []

    async def send_group_message(
        self, group_id: int, message: str, mark_sent: bool = False
    ) -> None:
        self.messages.append((group_id, message, mark_sent))


def _tool_manager() -> ToolManager:
    tool_registry = SimpleNamespace()
    agent_registry = SimpleNamespace(get_agents_schema=lambda: [])
    return ToolManager(cast(Any, tool_registry), cast(Any, agent_registry))


@pytest.mark.parametrize(
    ("mode", "should_send"),
    [
        ("none", False),
        ("agent", False),
        ("tools", True),
        ("clean", True),
        ("all", True),
    ],
)
@pytest.mark.asyncio
async def test_virtual_tool_search_follows_tool_easter_egg_modes(
    mode: str, should_send: bool
) -> None:
    sender = _DummySender()
    context = {
        "runtime_config": SimpleNamespace(easter_egg_agent_call_message_mode=mode),
        "sender": sender,
        "group_id": 123456,
    }

    await _tool_manager().announce_virtual_tool_call("tool_search", context)

    expected = (
        [(123456, "tool_search，我调用你了，我要调用你了！", False)]
        if should_send
        else []
    )
    assert sender.messages == expected


@pytest.mark.asyncio
async def test_virtual_tool_search_clean_mode_respects_silent_context() -> None:
    sender = _DummySender()
    context = {
        "runtime_config": SimpleNamespace(easter_egg_agent_call_message_mode="clean"),
        "sender": sender,
        "group_id": 123456,
        "easter_egg_silent": True,
    }

    await _tool_manager().announce_virtual_tool_call("tool_search", context)

    assert sender.messages == []


@pytest.mark.asyncio
async def test_tool_manager_injects_delivery_address_callables() -> None:
    captured_context: dict[str, Any] = {}

    async def execute_tool(
        _name: str,
        _args: dict[str, Any],
        context: dict[str, Any],
    ) -> str:
        captured_context.update(context)
        return "ok"

    tool_registry = SimpleNamespace(execute_tool=execute_tool)
    agent_registry = SimpleNamespace(get_agents_schema=lambda: [])
    manager = ToolManager(
        cast(Any, tool_registry),
        cast(Any, agent_registry),
    )

    result = await manager.execute_tool(
        "messages.send_private_message",
        {},
        {"runtime_config": SimpleNamespace(easter_egg_agent_call_message_mode="none")},
    )

    assert result == "ok"
    assert captured_context["parse_delivery_address"] is parse_delivery_address
    assert captured_context["resolve_delivery_address"] is resolve_delivery_address
    assert captured_context["format_message_xml"] is format_message_xml
