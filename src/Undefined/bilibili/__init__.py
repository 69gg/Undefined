"""Bilibili 视频提取模块

提供 B 站视频标识符解析、视频下载和发送功能，以及图文（opus）解析。
"""

from Undefined.bilibili.opus_parser import (
    extract_opus_from_json_message,
    extract_opus_ids_with_shortlinks,
)
from Undefined.bilibili.parser import (
    extract_bilibili_ids,
    extract_from_json_message,
    normalize_to_bvid,
)

__all__ = [
    "extract_bilibili_ids",
    "extract_from_json_message",
    "extract_opus_from_json_message",
    "extract_opus_ids_with_shortlinks",
    "normalize_to_bvid",
]
