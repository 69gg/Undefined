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
