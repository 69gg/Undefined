from typing import Any


async def execute(args: dict[str, Any], context: dict[str, Any]) -> str:
    cognitive_service = context.get("cognitive_service")
    if not cognitive_service or not cognitive_service.enabled:
        return "认知记忆系统未启用"
    try:
        profile = await cognitive_service.get_profile(
            entity_type=args["entity_type"],
            entity_id=args["entity_id"],
        )
    except ValueError as exc:
        return f"侧写查询参数无效: {exc}"
    return profile if profile else "暂无该实体的侧写信息"
