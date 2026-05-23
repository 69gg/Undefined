from __future__ import annotations

import logging
import re

from Undefined.services.commands.context import CommandContext

logger = logging.getLogger(__name__)

_TIME_RANGE_RE = re.compile(r"^\d+[hHdDwW]$")
_DEFAULT_COUNT = 50


def _parse_args(args: list[str]) -> tuple[int | None, str | None, str]:
    """Parse command arguments into (count, time_range, custom_prompt).

    Returns:
        Tuple of (count, time_range, custom_prompt).
        count and time_range are mutually exclusive; at most one is non-None.
    """
    if not args:
        return _DEFAULT_COUNT, None, ""

    first = args[0]
    rest = " ".join(args[1:]).strip()

    if first.isdigit():
        count = max(1, int(first))
        return count, None, rest

    if _TIME_RANGE_RE.match(first):
        return None, first, rest

    return _DEFAULT_COUNT, None, " ".join(args).strip()


def _build_prompt(count: int | None, time_range: str | None, custom_prompt: str) -> str:
    """Build the natural language instruction for message summary."""
    if time_range:
        scope = f"过去 {time_range} 内的聊天消息"
    elif count:
        scope = f"最近 {count} 条聊天消息"
    else:
        scope = f"最近 {_DEFAULT_COUNT} 条聊天消息"

    parts = [f"请总结{scope}。"]
    if custom_prompt:
        parts.append(f"重点关注：{custom_prompt}。")
    parts.append("只能依据下方原始聊天记录总结，不得编造或推测未出现的信息。")
    return "".join(parts)


def _is_private(context: CommandContext) -> bool:
    return context.scope == "private"


async def _send(context: CommandContext, text: str) -> None:
    if _is_private(context):
        user_id = int(context.user_id or context.sender_id)
        await context.sender.send_private_message(user_id, text)
    else:
        await context.sender.send_group_message(context.group_id, text)


async def execute(args: list[str], context: CommandContext) -> None:
    """处理 /summary 命令。"""
    if context.history_manager is None:
        await _send(context, "❌ 历史记录管理器未配置")
        return

    count, time_range, custom_prompt = _parse_args(args)
    instruction = _build_prompt(count, time_range, custom_prompt)

    ai = context.ai
    if ai is None or not hasattr(ai, "summarize_command_session"):
        await _send(context, "❌ 消息总结服务未配置")
        return

    group_id = int(context.group_id or 0)
    user_id = int(context.user_id or context.sender_id)

    try:
        result = await ai.summarize_command_session(
            context.history_manager,
            group_id=group_id,
            user_id=user_id,
            count=count,
            time_range=time_range,
            instruction=instruction,
        )
    except Exception:
        logger.exception("[/summary] 执行总结失败")
        await _send(context, "❌ 消息总结失败，请稍后重试")
        return

    if not result or not result.strip():
        await _send(context, "📭 未能生成总结内容")
        return

    await _send(context, result)
