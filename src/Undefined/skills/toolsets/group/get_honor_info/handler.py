from typing import Any, Dict
import logging

logger = logging.getLogger(__name__)


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    """获取群荣誉信息"""
    ai_client = context.get("ai_client")
    group_id = args.get("group_id") or context.get("group_id")
    if not group_id:
        # 向后兼容
        ai_client = context.get("ai_client")
        group_id = ai_client.current_group_id if ai_client else None
    honor_type = args.get("type", "all")

    if group_id is None:
        return "请提供群号（group_id 参数），或者在群聊中调用"

    try:
        group_id = int(group_id)
    except (ValueError, TypeError):
        return "参数类型错误：group_id 必须是整数"

    onebot_client = context.get("onebot_client")
    if not onebot_client:
        return "获取群荣誉信息功能不可用（OneBot 客户端未设置）"

    try:
        # 尝试调用 _get_group_honor_info (通常是非标准 API)
        # 这里我们假定 OneBotClient 有一个通用的 _call_api 方法或者具体的接口
        # 如果 OneBotClient 没有这个方法，我们可以通过 _call_api 直接调用
        if hasattr(onebot_client, "_call_api"):
            result = await onebot_client._call_api(
                "get_group_honor_info", {"group_id": group_id, "type": honor_type}
            )
            data = result.get("data", {})
        else:
            return "当前客户端版本不支持获取群荣誉信息"

        if not data:
            return f"未能获取到群 {group_id} 的荣誉信息"

        result_parts = [f"【群荣誉信息】群号: {group_id}"]

        honor_map = {
            "talkative": "龙王",
            "performer": "群聊之星",
            "legend": "群聊之火",
            "strong_newbie": "冒泡之焰",
            "emotion": "快乐之源",
        }

        # 处理龙王 (电流/历史)
        talkative = data.get("talkative")
        if talkative:
            user_id = talkative.get("user_id")
            nickname = talkative.get("nickname", "")
            days = talkative.get("day_count", 0)
            result_parts.append(f"👑 龙王: {nickname} ({user_id}) - 已蝉联 {days} 天")

        # 处理其他荣誉列表
        for key, name in honor_map.items():
            if key == "talkative":
                continue
            honor_list = data.get(key + "_list", [])
            if honor_list:
                result_parts.append(f"\n✨ {name}:")
                for item in honor_list:
                    uid = item.get("user_id")
                    nick = item.get("nickname", "")
                    desc = item.get("description", "")
                    result_parts.append(
                        f"  - {nick} ({uid}) {f'[{desc}]' if desc else ''}"
                    )

        if len(result_parts) == 1:
            return f"群 {group_id} 目前没有任何荣誉信息"

        return "\n".join(result_parts)

    except Exception as e:
        logger.exception(f"获取群荣誉失败: {e}")
        return f"获取失败：{str(e)} (可能当前 OneBot 实现不支持该接口)"
