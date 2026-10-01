"""禁漫（JM / 18comic）车号解析。

触发形态有两种：``JM`` 前缀加数字（``JM1114751`` / ``jm 1114751``），
以及禁漫链接（``https://18comic.vip/album/1114751``、``?id=1114751``）。
两种形态最终都归一化成纯数字车号，交给 :func:`jmcpy.texts.normalize_book_id`
解析，避免自己维护一份路径规则。
"""

from __future__ import annotations

import html
import json
import logging
import re
from typing import Any
from urllib.parse import urlsplit

from jmcpy.errors import JmcpyError
from jmcpy.texts import normalize_book_id

logger = logging.getLogger(__name__)

#: 车号位数范围：5 位（早期短号）到 8 位（当前号段）
_MIN_BOOK_ID = 10_000
_MAX_BOOK_ID = 99_999_999

#: ``jm`` + 数字；前缀前不能是字母数字（避免 ``xxjm123``），数字后不能跟数字（避免截断长数字）
#: 前缀前不能是字母数字，也不能是 URL/路径/文件名的分隔符
#: （``t.me/jm1234567``、``video_jm1234567.mp4`` 都不算车号）
_JM_TOKEN_REGEX = re.compile(
    r"(?<![0-9A-Za-z._/\\-])jm\s*[:：#\-]?\s*(\d{5,8})(?!\d)", re.I
)
_URL_REGEX = re.compile(r"https?://[^\s<>()\"']+", re.I)
#: 链接归属：主机名包含这些关键词时按禁漫链接处理
_JM_HOST_KEYWORDS = ("18comic", "jmcomic")
#: 链接末尾常被中文标点或引号包裹
_URL_WRAPPERS = ".,;:!?)]}>\"'”’"


def _strip_wrapper_chars(value: str) -> str:
    return html.unescape(value).strip().rstrip(_URL_WRAPPERS)


def _is_jm_host(host: str) -> bool:
    return any(keyword in host for keyword in _JM_HOST_KEYWORDS)


def normalize_jm_id(value: int | str) -> str | None:
    """把车号、``JM<数字>`` 或禁漫链接归一化成纯数字字符串。

    位数不在 5–8 位范围内、或链接不在禁漫域名下时返回 ``None``
    （普通数字串与非禁漫链接都不会被误判成车号）。
    """
    if isinstance(value, str) and "://" in value:
        if not _is_jm_host(urlsplit(value).hostname or ""):
            return None
    try:
        digits = normalize_book_id(value)
    except (JmcpyError, ValueError):
        return None
    if not digits.isdigit():
        return None
    if not _MIN_BOOK_ID <= int(digits) <= _MAX_BOOK_ID:
        return None
    return str(int(digits))


def _append_candidate(
    candidate: str,
    *,
    results: list[str],
    seen: set[str],
) -> None:
    normalized = normalize_jm_id(candidate)
    if normalized is None or normalized in seen:
        return
    seen.add(normalized)
    results.append(normalized)


def extract_jm_ids(text: str) -> list[str]:
    """从纯文本中提取禁漫车号（按出现顺序去重）。"""
    results: list[str] = []
    seen: set[str] = set()
    if not text:
        return results

    for match in _URL_REGEX.finditer(text):
        candidate = _strip_wrapper_chars(match.group(0))
        if not _is_jm_host(urlsplit(candidate).hostname or ""):
            continue
        _append_candidate(candidate, results=results, seen=seen)

    for match in _JM_TOKEN_REGEX.finditer(text):
        _append_candidate(match.group(1), results=results, seen=seen)

    return results


def _collect_json_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        strings: list[str] = []
        for item in value:
            strings.extend(_collect_json_strings(item))
        return strings
    if isinstance(value, dict):
        strings = []
        for item in value.values():
            strings.extend(_collect_json_strings(item))
        return strings
    return []


def extract_from_json_message(segments: list[dict[str, Any]]) -> list[str]:
    """从 QQ JSON 分享卡片中提取禁漫车号。"""
    results: list[str] = []
    seen: set[str] = set()

    for segment in segments:
        if segment.get("type") != "json":
            continue

        raw_data = segment.get("data", {}).get("data", "")
        if not raw_data:
            continue

        try:
            payload = json.loads(html.unescape(str(raw_data)))
        except (TypeError, json.JSONDecodeError):
            logger.debug("[JM] JSON 消息解析失败，跳过", exc_info=True)
            continue

        for item in _collect_json_strings(payload):
            for book_id in extract_jm_ids(item):
                if book_id in seen:
                    continue
                seen.add(book_id)
                results.append(book_id)

    return results
