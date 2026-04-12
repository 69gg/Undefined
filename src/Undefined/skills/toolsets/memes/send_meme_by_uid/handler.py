from __future__ import annotations

from typing import Any


async def execute(args: dict[str, Any], context: dict[str, Any]) -> str:
    meme_service = context.get("meme_service")
    if meme_service is None or not getattr(meme_service, "enabled", False):
        return "表情包库未启用"

    uid = str(args.get("uid", "") or "").strip()
    if not uid:
        return "uid 不能为空"

    tool_context = dict(context)
    if "target_type" in args:
        tool_context["target_type"] = args.get("target_type")
    if "target_id" in args:
        tool_context["target_id"] = args.get("target_id")
    result = await meme_service.send_meme_by_uid(uid, tool_context)
    return str(result)
