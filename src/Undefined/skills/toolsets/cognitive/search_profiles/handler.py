from typing import Any


async def execute(args: dict[str, Any], context: dict[str, Any]) -> str:
    cognitive_service = context.get("cognitive_service")
    if not cognitive_service or not cognitive_service.enabled:
        return "认知记忆系统未启用"
    results = await cognitive_service.search_profiles(
        query=args["query"],
        entity_type=args.get("entity_type"),
        top_k=args.get("top_k", 8),
    )
    if not results:
        return "未找到匹配的侧写"
    lines = []
    for r in results:
        meta = r.get("metadata", {})
        lines.append(
            f"- [{meta.get('entity_type', '')}:{meta.get('entity_id', '')}] {meta.get('name', '')} — {r['document'][:100]}"
        )
    return f"找到 {len(results)} 条匹配侧写：\n" + "\n".join(lines)
