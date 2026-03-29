from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from Undefined.skills.agents.runner import run_agent_with_tools

logger = logging.getLogger(__name__)


async def execute(args: dict[str, Any], context: dict[str, Any]) -> str:
    """执行 file_analysis_agent。"""

    file_source = str(args.get("file_source", "")).strip()
    user_prompt = str(args.get("prompt", "")).strip()

    if not file_source:
        return "请提供文件 URL 或 file_id"

    context["file_source"] = file_source
    context_messages = [
        {
            "role": "system",
            "content": f"当前任务附带文件源：{file_source}",
        }
    ]
    user_content = user_prompt if user_prompt else "请分析这个文件。"

    return await run_agent_with_tools(
        agent_name="file_analysis_agent",
        user_content=user_content,
        context_messages=context_messages,
        empty_user_content_message="请提供文件 URL 或 file_id",
        default_prompt="你是一个专业的文件分析助手...",
        context=context,
        agent_dir=Path(__file__).parent,
        logger=logger,
        max_iterations=30,
        tool_error_prefix="错误",
    )
