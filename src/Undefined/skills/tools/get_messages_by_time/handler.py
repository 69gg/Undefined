from typing import Any, Dict
from datetime import datetime


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
        # 使用生成器表达式简化查找逻辑
        if msg_type == "group":
            histories = history_manager._message_history.items()
        elif msg_type == "private":
            histories = history_manager._private_message_history.items()
        else:
            return chat_id

        # 查找第一个匹配的 ID
        for id_val, messages in histories:
            if messages and messages[0].get("chat_name") == chat_id:
                return str(id_val)

    except Exception:
        # 忽略任何查找过程中的错误，回退到返回原始 chat_id
        pass

    return chat_id


def _filter_messages(
    messages: list[Dict[str, Any]], start_dt: datetime, end_dt: datetime
) -> list[Dict[str, Any]]:
    """根据时间范围过滤消息

    参数:
        messages: 原始消息列表
        start_dt: 开始时间
        end_dt: 结束时间

    返回:
        过滤后的消息列表
    """
    filtered = []
    for msg in messages:
        timestamp = msg.get("timestamp", "")
        if not timestamp:
            continue
        try:
            msg_dt = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
            if start_dt <= msg_dt <= end_dt:
                filtered.append(msg)
        except ValueError:
            continue
    return filtered


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    chat_id = args.get("chat_id")
    msg_type = args.get("type")
    start_time = args.get("start_time", "")
    end_time = args.get("end_time", "")

    if not chat_id or not msg_type:
        return "chat_id 和 type 参数不能为空"
    if not start_time or not end_time:
        return "start_time 和 end_time 参数不能为空"

    try:
        start_dt = datetime.strptime(start_time, "%Y-%m-%d %H:%M:%S")
        end_dt = datetime.strptime(end_time, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return "时间格式错误，请使用格式：YYYY-MM-DD HH:MM:SS"

    if start_dt > end_dt:
        return "开始时间不能晚于结束时间"

    get_recent_messages_callback = context.get("get_recent_messages_callback")
    history_manager = context.get("history_manager")

    resolved_chat_id = _resolve_chat_id(chat_id, msg_type, history_manager)

    if get_recent_messages_callback:
        messages = await get_recent_messages_callback(
            resolved_chat_id, msg_type, 0, 10000
        )

        # 使用提取的函数进行过滤
        filtered_messages = _filter_messages(messages, start_dt, end_dt)

        formatted = []
        for msg in filtered_messages:
            msg_type_val = msg.get("type", "group")
            sender_name = msg.get("display_name", "未知用户")
            sender_id = msg.get("user_id", "")
            chat_name = msg.get("chat_name", "未知群聊")
            timestamp_str = msg.get("timestamp", "")
            text = msg.get("message", "")

            if msg_type_val == "group":
                # 确保群名以"群"结尾
                location = chat_name if chat_name.endswith("群") else f"{chat_name}群"
            else:
                location = "私聊"

            # 格式：XML 标准化
            formatted.append(f"""<message sender="{sender_name}" sender_id="{sender_id}" location="{location}" time="{timestamp_str}">
<content>{text}</content>
</message>""")

        if formatted:
            return f"找到 {len(formatted)} 条消息：\n" + "\n---\n".join(formatted)
        else:
            return f"在 {start_time} 到 {end_time} 之间没有找到消息"
    else:
        return "获取消息回调未设置"
