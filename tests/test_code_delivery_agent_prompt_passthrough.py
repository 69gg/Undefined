from __future__ import annotations

from typing import Any

import pytest

from Undefined.skills.agents.code_delivery_agent import handler as code_delivery_handler


@pytest.mark.asyncio
async def test_code_delivery_agent_keeps_prompt_raw_and_separates_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def _fake_run_agent_with_retry(**kwargs: Any) -> str:
        captured.update(kwargs)
        return "delivery"

    monkeypatch.setattr(
        code_delivery_handler,
        "_run_agent_with_retry",
        _fake_run_agent_with_retry,
    )

    context: dict[str, Any] = {"config": None}
    result = await code_delivery_handler.execute(
        {
            "prompt": "修复这个项目的启动脚本",
            "source_type": "git",
            "git_url": "https://example.com/repo.git",
            "git_ref": "main",
            "target_type": "group",
            "target_id": 123456,
        },
        context,
    )

    assert result == "delivery"
    assert captured["user_content"] == "修复这个项目的启动脚本"
    assert captured["context_messages"] == [
        {"role": "system", "content": "当前初始化来源：git"},
        {
            "role": "system",
            "content": "当前 Git 仓库：https://example.com/repo.git @ main",
        },
    ]
    assert context["target_type"] == "group"
    assert context["target_id"] == 123456
    assert context["init_args"] == {
        "source_type": "git",
        "git_url": "https://example.com/repo.git",
        "git_ref": "main",
    }
