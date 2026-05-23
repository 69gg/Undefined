from __future__ import annotations

from typing import Any

from Undefined.services.message_summary_fetch import fetch_session_messages


async def execute(args: dict[str, Any], context: dict[str, Any]) -> str:
    """拉取当前会话的聊天消息。"""
    history_manager = context.get("history_manager")
    if not history_manager:
        return "历史记录管理器未配置"

    group_id = int(context.get("group_id", 0) or 0)
    user_id = int(context.get("user_id", 0) or 0)
    time_range_str = str(args.get("time_range", "")).strip()
    raw_count = args.get("count")

    count: int | None
    if raw_count is None:
        count = None
    else:
        try:
            count = int(raw_count)
        except (TypeError, ValueError):
            count = None

    result = fetch_session_messages(
        history_manager,
        group_id=group_id,
        user_id=user_id,
        count=count,
        time_range=time_range_str or None,
        runtime_config=context.get("runtime_config"),
    )
    if not result:
        return "当前会话暂无消息记录"
    return result
