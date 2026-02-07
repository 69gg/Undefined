from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from Undefined.skills.agents.runner import run_agent_with_tools

logger = logging.getLogger(__name__)


async def execute(args: dict[str, Any], context: dict[str, Any]) -> str:
    """执行 info_agent。"""

    user_prompt = str(args.get("prompt", "")).strip()
    user_content = f"用户需求：{user_prompt}" if user_prompt else ""
    return await run_agent_with_tools(
        agent_name="info_agent",
        user_content=user_content,
        empty_user_content_message="请提供您的查询需求",
        default_prompt="你是一个信息查询助手...",
        context=context,
        agent_dir=Path(__file__).parent,
        logger=logger,
        max_iterations=20,
        tool_error_prefix="错误",
    )
