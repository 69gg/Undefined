from typing import Any


def _source(meta: dict[str, Any]) -> str:
    group_id = meta.get("group_id", "")
    group_name = meta.get("group_name", "")
    sender_name = meta.get("sender_name", "")
    sender_id = meta.get("sender_id", "") or meta.get("user_id", "")
    request_type = meta.get("request_type", "")

    loc = group_name or (
        f"群{group_id}" if group_id else ("私聊" if request_type == "private" else "")
    )
    who = sender_name or (f"UID:{sender_id}" if sender_id else "")
    label = " · ".join(filter(None, [loc, who]))
    return f"[{label}] " if label else ""


async def execute(args: dict[str, Any], context: dict[str, Any]) -> str:
    cognitive_service = context.get("cognitive_service")
    if not cognitive_service or not cognitive_service.enabled:
        return "认知记忆系统未启用"
    results = await cognitive_service.search_events(
        query=args["query"],
        target_user_id=args.get("target_user_id"),
        target_group_id=args.get("target_group_id"),
        sender_id=args.get("sender_id"),
        request_type=args.get("request_type"),
        top_k=args.get("top_k"),
        time_from=args.get("time_from"),
        time_to=args.get("time_to"),
    )
    if not results:
        return "未找到相关事件记忆"
    lines = [
        f"- [{r['metadata'].get('timestamp_local', '')}] {_source(r['metadata'])}{r['document']}"
        for r in results
    ]
    return f"找到 {len(results)} 条相关事件：\n" + "\n".join(lines)
