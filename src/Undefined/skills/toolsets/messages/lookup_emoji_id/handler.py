from __future__ import annotations

from typing import Any, Dict

from Undefined.utils.qq_emoji import (
    get_external_map_paths,
    resolve_emoji_id_by_alias,
    search_emoji_aliases,
)


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    emoji_raw = args.get("emoji")
    if not isinstance(emoji_raw, str):
        return "查询失败：emoji 必须是字符串"

    emoji = emoji_raw.strip()
    if not emoji:
        return "查询失败：emoji 不能为空"

    resolved = resolve_emoji_id_by_alias(emoji)
    if resolved is not None:
        return (
            f"emoji '{emoji}' 对应 emoji_id={resolved}\n"
            f"可直接调用 messages.react_message_emoji，传 emoji_id={resolved}"
        )

    suggestions = search_emoji_aliases(emoji, limit=10)
    if suggestions:
        rows = "\n".join(f"- {alias}: {emoji_id}" for alias, emoji_id in suggestions)
        return (
            f"未找到 emoji '{emoji}' 的精确映射，以下是候选：\n"
            f"{rows}\n"
            "你可以直接使用候选中的 emoji_id。"
        )

    paths = ", ".join(get_external_map_paths())
    return (
        f"未找到 emoji '{emoji}' 的映射。\n"
        f"你可以直接传 emoji_id，或在映射文件中补充别名：{paths}"
    )
