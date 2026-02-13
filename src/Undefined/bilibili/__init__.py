"""Bilibili 视频提取模块

提供 B 站视频标识符解析、视频下载和发送功能。
"""

from Undefined.bilibili.parser import (
    extract_bilibili_ids,
    extract_from_json_message,
    normalize_to_bvid,
)

__all__ = [
    "extract_bilibili_ids",
    "extract_from_json_message",
    "normalize_to_bvid",
]
