"""B 站内容展示用的共享格式化助手。

这里只放纯函数：数字缩写、时长、时间戳、以及按长度切分文本。发送层
（``bilibili.sender`` / ``bilibili.opus_sender``）与 ``utils/sender.py``
共用同一套语义，避免各写一份。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

# QQ / OneBot 单条文本的保守上限；与 ``utils.sender.MAX_MESSAGE_LENGTH`` 保持一致。
# 这里单独定义一份，避免 ``bilibili`` 包反向依赖发送器实现。
MAX_TEXT_LENGTH = 4000

# B 站展示时间统一使用北京时间（API 通过 timezone_offset=-480 对齐）
BEIJING_TIMEZONE = timezone(timedelta(hours=8))


def format_count(value: int) -> str:
    """把计数格式化为中文缩写（1.2万 / 1.5亿）。"""
    if value < 0:
        value = 0
    if value >= 100_000_000:
        return f"{value / 100_000_000:.1f}亿"
    if value >= 10_000:
        return f"{value / 10_000:.1f}万"
    return str(value)


def format_duration(seconds: int) -> str:
    """把秒数格式化为 mm:ss 或 h:mm:ss。"""
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def format_progress(progress_ms: int) -> str:
    """把弹幕时间戳（毫秒）格式化为 mm:ss。"""
    return format_duration(max(0, int(progress_ms)) // 1000)


def format_timestamp(timestamp: int) -> str:
    """把 UNIX 秒级时间戳格式化为北京时间 ``YYYY-MM-DD HH:MM``。"""
    if timestamp <= 0:
        return ""
    try:
        moment = datetime.fromtimestamp(int(timestamp), tz=BEIJING_TIMEZONE)
    except (OverflowError, OSError, ValueError):
        return ""
    return moment.strftime("%Y-%m-%d %H:%M")


def split_text_chunks(text: str, limit: int = MAX_TEXT_LENGTH) -> list[str]:
    """按长度分片，优先在换行后切分并保留原始文本。

    与 ``utils.sender._split_text_chunks`` 同语义：任何字符都不会丢失，
    无换行的超长段落会被硬切。
    """
    if not text:
        return []
    size = max(1, int(limit))
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            newline = text.rfind("\n", start, end)
            if newline >= start:
                end = newline + 1
        chunks.append(text[start:end])
        start = end
    return chunks
