from __future__ import annotations

import pytest

from Undefined.skills.agents.naga_code_analysis_agent.tools.read_naga_intro import (
    handler as read_naga_intro_handler,
)


@pytest.mark.asyncio
async def test_read_naga_intro_mentions_current_naga_layout() -> None:
    result = await read_naga_intro_handler.execute({}, {})

    assert "eb71318" in result
    assert "README 标识版本 5.1.0" in result
    assert "api_format" in result
    assert "anthropic" in result
    assert "apiserver/routes/" in result
    assert "agentserver/dogtag/" in result
    assert "OpenClaw" in result
    assert "mcpserver/mcp_manager.py" in result
    assert "skills/*/SKILL.md" in result
    assert "guide_engine/" in result
