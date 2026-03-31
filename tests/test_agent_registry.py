from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from Undefined.skills.agents import AgentRegistry


@pytest.mark.asyncio
async def test_agent_registry_executes_without_registry_timeout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    agent_dir = tmp_path / "demo_agent"
    agent_dir.mkdir()
    (agent_dir / "config.json").write_text(
        json.dumps(
            {
                "type": "function",
                "function": {
                    "name": "demo_agent",
                    "description": "demo",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ),
        encoding="utf-8",
    )
    (agent_dir / "handler.py").write_text(
        "async def execute(args, context):\n    return 'ok'\n",
        encoding="utf-8",
    )

    registry = AgentRegistry(tmp_path)
    original_wait_for = asyncio.wait_for
    seen: dict[str, float] = {}

    async def _wait_for(awaitable, timeout):  # type: ignore[no-untyped-def]
        seen["timeout"] = timeout
        return await original_wait_for(awaitable, timeout)

    monkeypatch.setattr("Undefined.skills.registry.asyncio.wait_for", _wait_for)

    result = await registry.execute_agent("demo_agent", {}, {})

    assert result == "ok"
    assert registry.timeout_seconds == 0.0
    assert "timeout" not in seen
