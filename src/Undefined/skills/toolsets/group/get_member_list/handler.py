from typing import Any, Dict
import logging

logger = logging.getLogger(__name__)


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    """获取群成员列表"""
    ai_client = context.get("ai_client")
    group_id = args.get("group_id") or context.get("group_id")
    if not group_id:
        # 向后兼容
        ai_client = context.get("ai_client")
        group_id = ai_client.current_group_id if ai_client else None
    count = args.get("count", 20)
    role_filter = args.get("role")

    if group_id is None:
        return "请提供群号（group_id 参数），或者在群聊中调用"

    try:
        group_id = int(group_id)
    except (ValueError, TypeError):
        return "参数类型错误：group_id 必须是整数"

    onebot_client = context.get("onebot_client")
    if not onebot_client:
        return "获取群成员列表功能不可用（OneBot 客户端未设置）"

    try:
        member_list = await onebot_client.get_group_member_list(group_id)

        if not member_list:
            return f"未能获取到群 {group_id} 的成员列表，可能群号不正确或机器人不在该群"

        # 筛选角色
        if role_filter:
            member_list = [m for m in member_list if m.get("role") == role_filter]

        total_found = len(member_list)
        # 限制数量
        member_list = member_list[:count]

        if not member_list:
            role_desc = {"owner": "群主", "admin": "管理员", "member": "普通成员"}.get(
                role_filter or "", role_filter
            )
            return f"群 {group_id} 中没有找到角色为 {role_desc} 的成员"

        result_parts = [f"【群成员列表】群号: {group_id} (匹配总数: {total_found})"]

        role_map = {
            "owner": "群主",
            "admin": "管理员",
            "member": "成员",
        }

        for i, member in enumerate(member_list, 1):
            user_id = member.get("user_id")
            nickname = member.get("nickname", "")
            card = member.get("card", "")
            role = member.get("role", "member")

            display_name = card if card else nickname
            role_zh = role_map.get(role, role)

            result_parts.append(f"{i}. {display_name} ({user_id}) [{role_zh}]")

        if total_found > count:
            result_parts.append(f"... 等共 {total_found} 位成员")

        return "\n".join(result_parts)

    except Exception as e:
        logger.exception(f"获取群成员列表失败: {e}")
        return f"获取失败：{str(e)}"
