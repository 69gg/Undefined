from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from Undefined.skills.agents.runner import run_agent_with_tools

logger = logging.getLogger(__name__)


def _normalize_positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _build_user_content(args: dict[str, Any]) -> str:
    prompt = str(args.get("prompt", "")).strip()
    count = _normalize_positive_int(args.get("count"))
    time_range = str(args.get("time_range", "") or "").strip()
    focus = str(args.get("focus", "") or "").strip()

    if not prompt:
        if time_range:
            prompt = f"请总结过去 {time_range} 内的聊天消息"
        elif count is not None:
            prompt = f"请总结最近 {count} 条聊天消息"

    instructions: list[str] = []
    if time_range:
        instructions.append(f"必须调用 fetch_messages，并使用 time_range={time_range}")
    elif count is not None:
        instructions.append(f"必须调用 fetch_messages，并使用 count={count}")
    else:
        instructions.append("必须调用 fetch_messages，并使用默认的 count=50")

    if focus:
        instructions.append(f"总结时重点关注：{focus}")

    instructions.append("输出尽量精炼，控制在 2 到 3 个短段落内")
    instructions.append("不要使用 emoji、markdown、项目符号或标题")

    if not prompt:
        return ""

    return f"{prompt}\n\n执行要求：\n" + "\n".join(
        f"{index}. {item}" for index, item in enumerate(instructions, start=1)
    )


async def execute(args: dict[str, Any], context: dict[str, Any]) -> str:
    """执行 summary_agent。"""
    user_prompt = _build_user_content(args)
    return await run_agent_with_tools(
        agent_name="summary_agent",
        user_content=user_prompt,
        empty_user_content_message="请提供您的总结需求",
        default_prompt=(
            "你是一个消息总结助手。"
            "必须严格按照用户给定的 count/time_range/focus 约束调用 fetch_messages，"
            "不要擅自扩大范围。"
            "输出要简短、朴素、信息密度高。"
        ),
        context=context,
        agent_dir=Path(__file__).parent,
        logger=logger,
        max_iterations=10,
        tool_error_prefix="错误",
    )
