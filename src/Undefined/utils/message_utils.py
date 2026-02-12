"""消息处理工具函数"""

import logging
from datetime import datetime
from typing import Any, Dict, TYPE_CHECKING
from collections import Counter

from Undefined.onebot import parse_message_time

if TYPE_CHECKING:
    from Undefined.onebot import OneBotClient

logger = logging.getLogger(__name__)


async def fetch_group_messages(
    onebot_client: "OneBotClient",
    group_id: int,
    max_count: int,
    start_dt: datetime | None = None,
) -> list[Dict[str, Any]]:
    """分批获取群消息历史，支持提前终止

    参数:
        onebot_client: OneBot 客户端实例
        group_id: 群号
        max_count: 最多获取的消息数量
        start_dt: 开始时间，如果提供则在消息早于此时间时停止获取

    返回:
        消息列表
    """
    all_messages: list[Dict[str, Any]] = []
    message_seq: int | None = None
    batch_size = 500

    try:
        while len(all_messages) < max_count:
            # 计算本次需要获取的数量
            remaining = max_count - len(all_messages)
            count = min(batch_size, remaining)

            # 获取一批消息
            messages = await onebot_client.get_group_msg_history(
                group_id, message_seq, count
            )

            if not messages:
                break

            # 检查是否需要提前终止
            if start_dt:
                filtered_messages = []
                for msg in messages:
                    msg_time = parse_message_time(msg)
                    if msg_time >= start_dt:
                        filtered_messages.append(msg)
                    else:
                        # 消息已早于开始时间，停止获取
                        all_messages.extend(filtered_messages)
                        return all_messages
                messages = filtered_messages

            all_messages.extend(messages)

            # 如果返回的消息数少于请求数，说明已经没有更多消息
            if len(messages) < count:
                break

            # 更新 message_seq 为最早消息的 seq
            if messages:
                last_msg = messages[-1]
                message_seq = last_msg.get("message_seq")
                if message_seq is None:
                    break

    except Exception as e:
        logger.error(f"获取群消息历史失败: {e}")

    return all_messages


def filter_user_messages(
    messages: list[Dict[str, Any]],
    user_id: int,
    start_dt: datetime | None,
    end_dt: datetime | None,
) -> list[Dict[str, Any]]:
    """筛选特定用户在时间范围内的消息

    参数:
        messages: 消息列表
        user_id: 用户QQ号
        start_dt: 开始时间
        end_dt: 结束时间

    返回:
        筛选后的消息列表
    """
    filtered: list[Dict[str, Any]] = []

    for msg in messages:
        # 检查发送者
        sender = msg.get("sender", {})
        msg_user_id = sender.get("user_id", 0)
        if msg_user_id != user_id:
            continue

        # 检查时间范围
        msg_time = parse_message_time(msg)
        if start_dt and msg_time < start_dt:
            continue
        if end_dt and msg_time > end_dt:
            continue

        filtered.append(msg)

    return filtered


def count_message_types(messages: list[Dict[str, Any]]) -> Dict[str, int]:
    """统计消息类型分布

    参数:
        messages: 消息列表

    返回:
        类型统计字典，格式：{"文本消息": 10, "图片消息": 5, ...}
    """
    type_counter: Counter[str] = Counter()

    for msg in messages:
        message_content = msg.get("message", [])
        if isinstance(message_content, str):
            type_counter["文本消息"] += 1
            continue

        if not isinstance(message_content, list):
            continue

        # 统计消息段类型
        has_text = False
        has_image = False
        has_face = False
        has_reply = False
        has_other = False

        for segment in message_content:
            seg_type = segment.get("type", "")
            if seg_type == "text":
                has_text = True
            elif seg_type == "image":
                has_image = True
            elif seg_type == "face":
                has_face = True
            elif seg_type == "reply":
                has_reply = True
            else:
                has_other = True

        # 优先级：回复 > 图片 > 表情 > 其他 > 文本
        if has_reply:
            type_counter["回复消息"] += 1
        elif has_image:
            type_counter["图片消息"] += 1
        elif has_face:
            type_counter["表情消息"] += 1
        elif has_other:
            type_counter["其他消息"] += 1
        elif has_text:
            type_counter["文本消息"] += 1
        else:
            type_counter["空消息"] += 1

    return dict(type_counter)


def analyze_activity_pattern(messages: list[Dict[str, Any]]) -> Dict[str, Any]:
    """分析消息活跃度模式

    参数:
        messages: 消息列表

    返回:
        活跃度统计字典
    """
    if not messages:
        return {}

    # 按小时统计
    hour_counter: Counter[int] = Counter()
    # 按星期统计
    weekday_counter: Counter[int] = Counter()
    # 按日期统计
    date_counter: Counter[str] = Counter()

    first_time: datetime | None = None
    last_time: datetime | None = None

    for msg in messages:
        msg_time = parse_message_time(msg)
        hour_counter[msg_time.hour] += 1
        weekday_counter[msg_time.weekday()] += 1
        date_counter[msg_time.strftime("%Y-%m-%d")] += 1

        if first_time is None or msg_time < first_time:
            first_time = msg_time
        if last_time is None or msg_time > last_time:
            last_time = msg_time

    # 找出最活跃时段
    most_active_hour = hour_counter.most_common(1)[0][0] if hour_counter else 0
    most_active_hour_str = f"{most_active_hour:02d}:00-{most_active_hour:02d}:59"

    # 找出最活跃星期
    weekday_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    most_active_weekday = weekday_counter.most_common(1)[0][0] if weekday_counter else 0
    most_active_weekday_str = weekday_names[most_active_weekday]

    # 计算平均每天消息数
    total_days = len(date_counter)
    avg_per_day = len(messages) / total_days if total_days > 0 else 0

    return {
        "avg_per_day": round(avg_per_day, 1),
        "most_active_hour": most_active_hour_str,
        "most_active_weekday": most_active_weekday_str,
        "first_time": first_time,
        "last_time": last_time,
    }


def count_messages_by_user(
    messages: list[Dict[str, Any]], user_ids: set[int]
) -> Dict[int, int]:
    """统计指定用户的消息数量

    参数:
        messages: 消息列表
        user_ids: 用户QQ号集合

    返回:
        用户消息数量字典，格式：{user_id: count}
    """
    counter: Dict[int, int] = {uid: 0 for uid in user_ids}

    for msg in messages:
        sender = msg.get("sender", {})
        msg_user_id = sender.get("user_id", 0)
        if msg_user_id in user_ids:
            counter[msg_user_id] += 1

    return counter


def format_messages(messages: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
    """格式化消息列表用于显示

    参数:
        messages: 消息列表

    返回:
        格式化后的消息列表
    """
    formatted: list[Dict[str, Any]] = []

    for msg in messages:
        sender = msg.get("sender", {})
        sender_name = sender.get("card") or sender.get("nickname", "未知")
        sender_id = sender.get("user_id", 0)
        msg_time = parse_message_time(msg)

        # 提取消息文本
        message_content = msg.get("message", [])
        text_parts: list[str] = []

        if isinstance(message_content, str):
            text_parts.append(message_content)
        elif isinstance(message_content, list):
            for segment in message_content:
                seg_type = segment.get("type", "")
                if seg_type == "text":
                    data = segment.get("data", {})
                    text_parts.append(data.get("text", ""))
                elif seg_type == "image":
                    text_parts.append("[图片]")
                elif seg_type == "face":
                    text_parts.append("[表情]")
                elif seg_type == "reply":
                    text_parts.append("[回复]")
                else:
                    text_parts.append(f"[{seg_type}]")

        content = "".join(text_parts).strip() or "(空消息)"

        formatted.append(
            {
                "sender": sender_name,
                "sender_id": sender_id,
                "time": msg_time.strftime("%Y-%m-%d %H:%M:%S"),
                "content": content,
            }
        )

    return formatted
