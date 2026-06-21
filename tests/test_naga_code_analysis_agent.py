from __future__ import annotations

import json
from pathlib import Path

import pytest

from Undefined.skills.agents.naga_code_analysis_agent.tools.read_naga_intro import (
    handler as read_naga_intro_handler,
)


AGENT_DIR = (
    Path(__file__).resolve().parent.parent
    / "src"
    / "Undefined"
    / "skills"
    / "agents"
    / "naga_code_analysis_agent"
)


def test_prompt_and_intro_define_naga_only_scope() -> None:
    prompt = (AGENT_DIR / "prompt.md").read_text("utf-8")
    intro = (AGENT_DIR / "intro.md").read_text("utf-8")

    assert "`read_naga_intro` 提供 NagaAgent 当前结构索引" in prompt
    assert "如果问题越界，简明说明原因并建议正确 agent" in prompt
    assert "不回答 Undefined 自身源码问题" in prompt
    assert "不承担代码编写、修改、执行验证或打包交付" in prompt
    assert "仅用于回答 **NagaAgent 项目**" in intro
    assert "Undefined 自身源码问题，交给 `undefined_self_code_agent`" in intro
    assert "用户上传/外部文件解析，交给 `file_analysis_agent`" in intro
    assert "代码编写、修改、执行验证和打包交付，交给 `code_delivery_agent`" in intro


def test_config_description_defines_naga_only_scope() -> None:
    cfg = json.loads((AGENT_DIR / "config.json").read_text("utf-8"))
    description = cfg["function"]["description"]

    assert "仅用于 NagaAgent 项目" in description
    assert "不负责 Undefined 自身源码" in description
    assert "用户上传文件" in description
    assert "代码交付任务" in description


@pytest.mark.asyncio
async def test_read_naga_intro_mentions_current_naga_layout() -> None:
    result = await read_naga_intro_handler.execute({}, {})

    assert "README 标识版本 5.1.0" in result
    assert "api_format" in result
    assert "anthropic" in result
    assert "apiserver/routes/" in result
    assert "agentserver/dogtag/" in result
    assert "OpenClaw" in result
    assert "mcpserver/mcp_manager.py" in result
    assert "skills/*/SKILL.md" in result
    assert "guide_engine/" in result
    assert "frontend/electron/modules/backend.ts" in result
    assert "build.py" in result
    assert "docs/build-windows.md" in result
