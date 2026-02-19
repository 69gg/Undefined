"""获取最近消息的工具处理器。"""

from typing import Any, Dict


def _find_group_id_by_name(chat_id: str, history_manager: Any) -> str | None:
    """通过群名查找群号。

    Args:
        chat_id: 群名
        history_manager: 历史记录管理器实例

    Returns:
        找到的群号，未找到时返回 None
    """
    message_history = getattr(history_manager, "_message_history", {})
    for group_id, messages in message_history.items():
        if messages and messages[0].get("chat_name") == chat_id:
            return str(group_id)
    return None


def _find_user_id_by_name(chat_id: str, history_manager: Any) -> str | None:
    """通过用户名查找用户 ID。

    Args:
        chat_id: 用户名
        history_manager: 历史记录管理器实例

    Returns:
        找到的用户 ID，未找到时返回 None
    """
    private_history = getattr(history_manager, "_private_message_history", {})
    for user_id, messages in private_history.items():
        if messages and messages[0].get("chat_name") == chat_id:
            return str(user_id)
    return None


def _resolve_chat_id(chat_id: str, msg_type: str, history_manager: Any) -> str:
    """将群名/用户名转换为对应的 ID。

    Args:
        chat_id: 群名、用户名或群号/用户ID
        msg_type: "group" 或 "private"
        history_manager: 历史记录管理器实例

    Returns:
        解析后的群号或用户ID
    """
    # 如果已经是数字 ID，直接返回
    if chat_id.isdigit():
        return chat_id

    # 如果没有历史记录管理器，返回原始值
    if not history_manager:
        return chat_id

    try:
        # 根据消息类型查找对应的 ID
        if msg_type == "group":
            resolved_id = _find_group_id_by_name(chat_id, history_manager)
        elif msg_type == "private":
            resolved_id = _find_user_id_by_name(chat_id, history_manager)
        else:
            resolved_id = None

        # 如果找到了 ID，返回它；否则返回原始值
        return resolved_id if resolved_id else chat_id
    except Exception:
        return chat_id


def _format_message_location(msg_type_val: str, chat_name: str) -> str:
    """格式化消息地点。

    Args:
        msg_type_val: 消息类型（"group" 或 "private"）
        chat_name: 群名

    Returns:
        格式化后的地点字符串
    """
    if msg_type_val == "group":
        # 确保群名以"群"结尾
        return chat_name if chat_name.endswith("群") else f"{chat_name}群"
    return "私聊"


def _format_message_xml(msg: dict[str, Any]) -> str:
    """将消息格式化为 XML 格式。

    Args:
        msg: 消息字典

    Returns:
        格式化后的 XML 字符串
    """
    msg_type_val = msg.get("type", "group")
    sender_name = msg.get("display_name", "未知用户")
    sender_id = msg.get("user_id", "")
    chat_name = msg.get("chat_name", "未知群聊")
    timestamp = msg.get("timestamp", "")
    text = msg.get("message", "")

    location = _format_message_location(msg_type_val, chat_name)

    return f"""<message sender="{sender_name}" sender_id="{sender_id}" location="{location}" time="{timestamp}">
<content>{text}</content>
</message>"""


def _validate_range_param(value: Any, default: int) -> int:
    """验证并规范化范围参数。

    Args:
        value: 参数值
        default: 默认值

    Returns:
        验证后的整数值
    """
    if value is None or not isinstance(value, int) or value < 0:
        return default
    return int(value)


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    """获取最近的消息。

    Args:
        args: 参数字典，包含 chat_id、type、start、end
        context: 上下文字典

    Returns:
        格式化后的消息列表
    """
    chat_id = args.get("chat_id")
    msg_type = args.get("type")

    # 验证必需参数
    if not chat_id or not msg_type:
        return "chat_id 和 type 参数不能为空"

    # 验证范围参数
    start = _validate_range_param(args.get("start"), 0)
    end = _validate_range_param(args.get("end"), 10)

    # 获取回调和管理器
    get_recent_messages_callback = context.get("get_recent_messages_callback")
    history_manager = context.get("history_manager")

    # 解析 chat_id
    resolved_chat_id = _resolve_chat_id(chat_id, msg_type, history_manager)

    # 获取消息
    messages = []
    if get_recent_messages_callback:
        messages = await get_recent_messages_callback(
            resolved_chat_id, msg_type, start, end
        )
    elif history_manager:
        messages = history_manager.get_recent(resolved_chat_id, msg_type, start, end)
    else:
        return "获取消息回调未设置"

    # 格式化消息
    if messages is not None:
        formatted = [_format_message_xml(msg) for msg in messages]
        return "\n---\n".join(formatted) if formatted else "没有找到最近的消息"

    return "获取消息失败"
