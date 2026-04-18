from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from Undefined.skills.agents.runner import run_agent_with_tools

logger = logging.getLogger(__name__)


async def execute(args: dict[str, Any], context: dict[str, Any]) -> str:
    """执行 summary_agent。"""
    user_prompt = str(args.get("prompt", "")).strip()
    return await run_agent_with_tools(
        agent_name="summary_agent",
        user_content=user_prompt,
        empty_user_content_message="请提供您的总结需求",
        default_prompt="你是一个消息总结助手。使用 fetch_messages 工具获取聊天记录,然后进行智能总结。",
        context=context,
        agent_dir=Path(__file__).parent,
        logger=logger,
        max_iterations=10,
        tool_error_prefix="错误",
    )
