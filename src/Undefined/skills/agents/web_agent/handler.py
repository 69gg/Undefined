from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from Undefined.skills.agents.runner import run_agent_with_tools

logger = logging.getLogger(__name__)


async def execute(args: dict[str, Any], context: dict[str, Any]) -> str:
    """执行 web_agent。"""

    user_prompt = str(args.get("prompt", "")).strip()
    agent_dir = Path(__file__).parent
    return await run_agent_with_tools(
        agent_name="web_agent",
        user_content=user_prompt,
        empty_user_content_message="请提供您的搜索需求",
        default_prompt="你是一个网络搜索助手...",
        context=context,
        agent_dir=agent_dir,
        logger=logger,
        max_iterations=20,
        tool_error_prefix="Error",
    )
