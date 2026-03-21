from __future__ import annotations

from typing import Any

import pytest

from Undefined.skills.agents.entertainment_agent import handler as entertainment_handler
from Undefined.skills.agents.file_analysis_agent import handler as file_handler
from Undefined.skills.agents.info_agent import handler as info_handler
from Undefined.skills.agents.naga_code_analysis_agent import (
    handler as naga_code_handler,
)
from Undefined.skills.agents.web_agent import handler as web_handler


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("handler_module", "agent_name"),
    [
        (web_handler, "web_agent"),
        (info_handler, "info_agent"),
        (entertainment_handler, "entertainment_agent"),
        (naga_code_handler, "naga_code_analysis_agent"),
    ],
)
async def test_simple_agents_pass_prompt_through_verbatim(
    monkeypatch: pytest.MonkeyPatch,
    handler_module: Any,
    agent_name: str,
) -> None:
    captured: dict[str, Any] = {}

    async def _fake_run_agent_with_tools(**kwargs: Any) -> str:
        captured.update(kwargs)
        return "raw answer"

    monkeypatch.setattr(handler_module, "run_agent_with_tools", _fake_run_agent_with_tools)

    result = await handler_module.execute({"prompt": "  keep my original prompt  "}, {})

    assert result == "raw answer"
    assert captured["agent_name"] == agent_name
    assert captured["user_content"] == "keep my original prompt"
    assert "context_messages" not in captured or captured["context_messages"] is None


@pytest.mark.asyncio
async def test_file_analysis_agent_keeps_prompt_raw_and_moves_file_to_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def _fake_run_agent_with_tools(**kwargs: Any) -> str:
        captured.update(kwargs)
        return "analysis"

    monkeypatch.setattr(file_handler, "run_agent_with_tools", _fake_run_agent_with_tools)

    context: dict[str, Any] = {}
    result = await file_handler.execute(
        {"file_source": "https://example.com/demo.pdf", "prompt": "提取结论"},
        context,
    )

    assert result == "analysis"
    assert captured["user_content"] == "提取结论"
    assert captured["context_messages"] == [
        {
            "role": "system",
            "content": "当前任务附带文件源：https://example.com/demo.pdf",
        }
    ]
    assert context["file_source"] == "https://example.com/demo.pdf"


@pytest.mark.asyncio
async def test_file_analysis_agent_uses_generic_prompt_when_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def _fake_run_agent_with_tools(**kwargs: Any) -> str:
        captured.update(kwargs)
        return "analysis"

    monkeypatch.setattr(file_handler, "run_agent_with_tools", _fake_run_agent_with_tools)

    result = await file_handler.execute({"file_source": "file-123"}, {})

    assert result == "analysis"
    assert captured["user_content"] == "请分析这个文件。"
    assert captured["context_messages"] == [
        {"role": "system", "content": "当前任务附带文件源：file-123"}
    ]
