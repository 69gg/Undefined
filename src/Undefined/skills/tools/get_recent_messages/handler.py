from typing import Any, Dict


def _resolve_chat_id(chat_id: str, msg_type: str, history_manager: Any) -> str:
    """将群名/用户名转换为对应的 ID

    参数:
        chat_id: 群名、用户名或群号/用户ID
        msg_type: "group" 或 "private"
        history_manager: 历史记录管理器实例

    返回:
        解析后的群号或用户ID
    """
    if chat_id.isdigit():
        return chat_id

    if not history_manager:
        return chat_id

    try:
        if msg_type == "group":
            for group_id, messages in history_manager._message_history.items():
                if messages and messages[0].get("chat_name") == chat_id:
                    return str(group_id)
        elif msg_type == "private":
            for user_id, messages in history_manager._private_message_history.items():
                if messages and messages[0].get("chat_name") == chat_id:
                    return str(user_id)
    except Exception:
        pass

    return chat_id


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    chat_id = args.get("chat_id")
    msg_type = args.get("type")
    start = args.get("start", 0)
    end = args.get("end", 10)

    if not chat_id or not msg_type:
        return "chat_id 和 type 参数不能为空"

    if start is None or not isinstance(start, int) or start < 0:
        start = 0
    if end is None or not isinstance(end, int) or end < 0:
        end = 10

    get_recent_messages_callback = context.get("get_recent_messages_callback")
    history_manager = context.get("history_manager")

    resolved_chat_id = _resolve_chat_id(chat_id, msg_type, history_manager)

    messages = []
    if history_manager:
        messages = history_manager.get_recent(resolved_chat_id, msg_type, start, end)
    elif get_recent_messages_callback:
        messages = await get_recent_messages_callback(
            resolved_chat_id, msg_type, start, end
        )
    else:
        return "获取消息回调未设置"

    if messages is not None:
        formatted = []
        for msg in messages:
            msg_type_val = msg.get("type", "group")
            sender_name = msg.get("display_name", "未知用户")
            sender_id = msg.get("user_id", "")
            chat_name = msg.get("chat_name", "未知群聊")
            timestamp = msg.get("timestamp", "")
            text = msg.get("message", "")

            if msg_type_val == "group":
                # 确保群名以"群"结尾
                location = chat_name if chat_name.endswith("群") else f"{chat_name}群"
            else:
                location = "私聊"

            # 格式：XML 标准化
            formatted.append(f"""<message sender="{sender_name}" sender_id="{sender_id}" location="{location}" time="{timestamp}">
<content>{text}</content>
</message>""")

        return "\n---\n".join(formatted) if formatted else "没有找到最近的消息"
    else:
        return "获取消息失败"
