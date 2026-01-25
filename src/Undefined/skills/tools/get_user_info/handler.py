from typing import Any, Dict
import logging

logger = logging.getLogger(__name__)

FIELD_MAPPING = {
    "nickname": "昵称",
    "user_id": "QQ号",
    "sex": "性别",
    "age": "年龄",
    "level": "等级",
    "login_days": "登录天数",
    "qid": "QID",
    "vote_count": "点赞数",
}


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    """获取 QQ 用户详细信息"""
    user_id = args.get("user_id")

    if user_id is None:
        return "请提供 QQ 号（user_id 参数）"

    try:
        user_id = int(user_id)
    except (ValueError, TypeError):
        return "参数类型错误：user_id 必须是整数"

    onebot_client = context.get("onebot_client")
    if not onebot_client:
        return "获取用户信息功能不可用（OneBot 客户端未设置）"

    try:
        # 使用 get_stranger_info 获取详细信息
        user_info = await onebot_client.get_stranger_info(user_id)

        if not user_info:
            return f"无法获取 QQ {user_id} 的信息，该用户可能不存在"

        result_parts = ["【QQ用户信息】"]

        # 添加头像 URL (常用 API)
        result_parts.append(
            f"头像: http://q.qlogo.cn/headimg_dl?dst_uin={user_id}&spec=640"
        )

        # 处理性别
        sex = user_info.get("sex")
        if sex == "male":
            user_info["sex"] = "男"
        elif sex == "female":
            user_info["sex"] = "女"
        elif sex == "unknown":
            user_info["sex"] = "未知"

        for field, display_name in FIELD_MAPPING.items():
            value = user_info.get(field)
            if value is not None and value != "":
                result_parts.append(f"{display_name}: {value}")

        # 如果有其他字段（取决于 OneBot 实现，如 NapCat/Go-CQHttp 可能有更多）
        # 我们可以尝试输出一些常见的额外字段
        extra_fields = {
            "remark": "备注",
            "signature": "签名",
            "birthday": "生日",
            "location": "地区",
            "area": "地区",
            "level": "等级",
        }
        for field, display_name in extra_fields.items():
            if field in FIELD_MAPPING:
                continue
            value = user_info.get(field)
            if value is not None and value != "":
                result_parts.append(f"{display_name}: {value}")

        result_str = "\n".join(result_parts)
        return f"{result_str}\n✅ 信息获取成功"

    except Exception as e:
        logger.exception(f"获取用户信息失败: {e}")
        return f"获取失败：{str(e)}"
