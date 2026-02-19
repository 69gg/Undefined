"""群成员统计相关通用函数。"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any


_LEVEL_DIGIT_PATTERN = re.compile(r"(\d+)")


def clamp_int(value: Any, default: int, min_value: int, max_value: int) -> int:
    """将任意值转换为整数并限制到指定区间。"""
    try:
        result = int(value)
    except (TypeError, ValueError):
        return default
    if result < min_value:
        return min_value
    if result > max_value:
        return max_value
    return result


def parse_unix_timestamp(raw_value: Any) -> int:
    """安全解析 Unix 时间戳，失败返回 0。"""
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return 0
    return value if value > 0 else 0


def parse_member_level(raw_value: Any) -> int | None:
    """解析群等级字段并提取数值等级。"""
    if raw_value is None:
        return None
    if isinstance(raw_value, bool):
        return None
    if isinstance(raw_value, (int, float)):
        value = int(raw_value)
        return value if value >= 0 else None

    text = str(raw_value).strip()
    if not text:
        return None

    if text.isdigit():
        return int(text)

    match = _LEVEL_DIGIT_PATTERN.search(text)
    if match:
        return int(match.group(1))

    return None


def member_display_name(member: dict[str, Any]) -> str:
    """返回群成员展示名（优先群昵称）。"""
    card = str(member.get("card") or "").strip()
    nickname = str(member.get("nickname") or "").strip()
    user_id = str(member.get("user_id") or "未知")
    return card or nickname or user_id


def role_to_cn(role: Any) -> str:
    """将 OneBot 角色值转换为中文。"""
    role_text = str(role or "member")
    mapping = {
        "owner": "群主",
        "admin": "管理员",
        "member": "成员",
    }
    return mapping.get(role_text, role_text)


def format_timestamp(ts: int) -> str:
    """格式化时间戳。"""
    if ts <= 0:
        return "无"
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, OSError, OverflowError):
        return "无"


def datetime_to_ts(dt: datetime | None) -> int | None:
    """将 datetime 转成秒级时间戳。"""
    if dt is None:
        return None
    try:
        return int(dt.timestamp())
    except (ValueError, OSError, OverflowError):
        return None
