from typing import Any, Dict
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

FIELD_MAPPING = {
    "nickname": "QQ昵称",
    "card": "群昵称",
    "user_id": "QQ号",
    "join_time": "加群时间",
    "last_sent_time": "最后发言时间",
    "level": "等级",
    "role": "角色",
    "unfriendly": "是否不友好",
    "title": "头衔",
    "title_expire_time": "头衔过期时间",
    "shut_up_timestamp": "禁言截止时间",
}


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    """获取群聊成员的详细信息

    参数:
        args: 工具参数，包含 group_id、user_id、fields、limit、no_cache
        context: 工具上下文，包含 onebot_client 等回调函数

    返回:
        群成员详细信息描述
    """
    group_id = args.get("group_id")
    user_id = args.get("user_id")
    fields = args.get("fields")
    limit = args.get("limit")
    no_cache = args.get("no_cache", False)

    if group_id is None:
        return "请提供群号（group_id参数）"
    if user_id is None:
        return "请提供要查询的群成员QQ号（user_id参数）"

    try:
        group_id = int(group_id)
        user_id = int(user_id)
    except (ValueError, TypeError):
        return "参数类型错误：group_id 和 user_id 必须是整数"

    onebot_client = context.get("onebot_client")
    if not onebot_client:
        return "获取群成员信息功能不可用（OneBot 客户端未设置）"

    try:
        member_info = await onebot_client.get_group_member_info(
            group_id, user_id, no_cache
        )

        if not member_info:
            return f"未找到群 {group_id} 中 QQ {user_id} 的成员信息，可能该用户已退群或群号不正确"

        result_parts = []
        nickname = member_info.get("nickname", "")
        card = member_info.get("card", "")

        result_parts.append(f"【群成员信息】群号: {group_id}")

        display_name = card if card else nickname
        if display_name:
            result_parts.append(f"昵称: {display_name}")

        if fields:
            for field in fields:
                if field in FIELD_MAPPING:
                    value = member_info.get(field)
                    if value is not None:
                        if field in [
                            "join_time",
                            "last_sent_time",
                            "title_expire_time",
                            "shut_up_timestamp",
                        ]:
                            try:
                                if isinstance(value, (int, float)):
                                    dt = datetime.fromtimestamp(value)
                                    value = dt.strftime("%Y-%m-%d %H:%M:%S")
                            except (ValueError, TypeError, OSError):
                                pass
                        elif field == "role":
                            role_map = {
                                "owner": "群主",
                                "admin": "管理员",
                                "member": "成员",
                            }
                            value = role_map.get(str(value), str(value))
                        elif field == "unfriendly":
                            value = "是" if value else "否"
                        result_parts.append(f"{FIELD_MAPPING[field]}: {value}")
        else:
            for field, display_name_field in FIELD_MAPPING.items():
                value = member_info.get(field)
                if value is not None:
                    if field in [
                        "join_time",
                        "last_sent_time",
                        "title_expire_time",
                        "shut_up_timestamp",
                    ]:
                        try:
                            if isinstance(value, (int, float)):
                                dt = datetime.fromtimestamp(value)
                                value = dt.strftime("%Y-%m-%d %H:%M:%S")
                        except (ValueError, TypeError, OSError):
                            pass
                    elif field == "role":
                        role_map = {
                            "owner": "群主",
                            "admin": "管理员",
                            "member": "成员",
                        }
                        value = role_map.get(str(value), str(value))
                    elif field == "unfriendly":
                        value = "是" if value else "否"
                    result_parts.append(f"{display_name_field}: {value}")

        if limit and len(result_parts) > limit:
            result_parts = result_parts[:limit]

        result_str = "\n".join(result_parts)
        return f"{result_str}\n✅ 信息获取成功"

    except Exception as e:
        logger.exception(f"获取群成员信息失败: {e}")
        error_msg = str(e)

        if "retcode=100" in error_msg:
            return "获取失败：群号或QQ号不存在"
        elif "retcode=140" in error_msg:
            return "获取失败：无法获取非好友的群成员信息"
        elif "retcode=150" in error_msg:
            return "获取失败：群成员信息获取频率过高"
        else:
            return f"获取失败：{error_msg}"
