from typing import Any


async def execute(args: dict[str, Any], context: dict[str, Any]) -> str:
    cognitive_service = context.get("cognitive_service")
    if not cognitive_service or not cognitive_service.enabled:
        return "认知记忆系统未启用"
    results = await cognitive_service.search_events(
        query=args["query"],
        target_user_id=args.get("target_user_id"),
        target_group_id=args.get("target_group_id"),
        top_k=args.get("top_k"),
        time_from=args.get("time_from"),
        time_to=args.get("time_to"),
    )
    if not results:
        return "未找到相关事件记忆"
    lines = [
        f"- [{r['metadata'].get('timestamp_local', '')}] {r['document']}"
        for r in results
    ]
    return f"找到 {len(results)} 条相关事件：\n" + "\n".join(lines)
