from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from Undefined.arxiv.parser import normalize_arxiv_id
from Undefined.skills.agents.runner import run_agent_with_tools

logger = logging.getLogger(__name__)


async def execute(args: dict[str, Any], context: dict[str, Any]) -> str:
    """执行 arxiv_analysis_agent。"""

    raw_paper_id = str(args.get("paper_id", "")).strip()
    user_prompt = str(args.get("prompt", "")).strip()

    if not raw_paper_id:
        return "请提供 arXiv 论文 ID 或 URL"

    paper_id = normalize_arxiv_id(raw_paper_id)
    if paper_id is None:
        return f"无法解析 arXiv 标识：{raw_paper_id}"

    context["arxiv_paper_id"] = paper_id

    context_messages = [
        {
            "role": "system",
            "content": f"当前任务：深度分析 arXiv 论文 {paper_id}",
        }
    ]

    user_content = user_prompt if user_prompt else f"请深度分析论文 arXiv:{paper_id}"

    return await run_agent_with_tools(
        agent_name="arxiv_analysis_agent",
        user_content=user_content,
        context_messages=context_messages,
        empty_user_content_message="请提供 arXiv 论文 ID 或 URL",
        default_prompt="你是一个学术论文深度分析助手。",
        context=context,
        agent_dir=Path(__file__).parent,
        logger=logger,
        max_iterations=15,
        tool_error_prefix="错误",
    )
