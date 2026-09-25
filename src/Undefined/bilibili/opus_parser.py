"""B 站图文（opus）标识符解析。

从消息文本 / 消息段中提取图文 ID。支持：

- ``https://www.bilibili.com/opus/<动态id>``（含 ``m.`` 子域与无协议头写法）
- ``https://t.bilibili.com/<动态id>``
- ``https://b23.tv/<短链>``（解析后二次提取）
- QQ 小程序 / news 分享卡片中的跳转链接

与 ``parser.extract_bilibili_ids`` 独立：图文 ID 与 BV 号互不干扰。
"""

from __future__ import annotations

import html
import json
import logging
import re
from typing import Any

from Undefined.bilibili.parser import (
    SHORT_URL_PATTERN,
    resolve_short_url,
)

logger = logging.getLogger(__name__)

# ---------- 正则 ----------

# 动态 ID 为纯数字，且带域名上下文，避免把普通数字误判成图文 ID
OPUS_URL_PATTERN = re.compile(
    r"(?:https?://)?(?:www\.|m\.)?bilibili\.com/opus/(\d+)",
    re.IGNORECASE,
)
DYNAMIC_ID_URL_PATTERN = re.compile(
    r"(?:https?://)?(?:www\.)?t\.bilibili\.com/(\d+)",
    re.IGNORECASE,
)


def _extract_opus_ids_from_text(text: str) -> list[str]:
    """从纯文本中提取图文 ID（不做短链解析，同步操作）。"""
    opus_ids: list[str] = []
    seen: set[str] = set()
    for pattern in (OPUS_URL_PATTERN, DYNAMIC_ID_URL_PATTERN):
        for match in pattern.finditer(text):
            opus_id = match.group(1)
            if opus_id in seen:
                continue
            seen.add(opus_id)
            opus_ids.append(opus_id)
    return opus_ids


async def extract_opus_ids_with_shortlinks(text: str) -> list[str]:
    """从纯文本中提取图文 ID，并解析 b23.tv 短链后二次提取（去重、保序）。"""
    opus_ids: list[str] = []
    seen: set[str] = set()

    for opus_id in _extract_opus_ids_from_text(text):
        if opus_id not in seen:
            seen.add(opus_id)
            opus_ids.append(opus_id)

    for match in SHORT_URL_PATTERN.finditer(text):
        real_url = await resolve_short_url(match.group(0))
        if not real_url:
            continue
        for opus_id in _extract_opus_ids_from_text(real_url):
            if opus_id not in seen:
                seen.add(opus_id)
                opus_ids.append(opus_id)

    return opus_ids


async def extract_opus_from_json_message(
    segments: list[dict[str, Any]],
) -> list[str]:
    """从 QQ 消息段中检测 JSON 小程序消息，提取 B 站图文 ID。"""
    opus_ids: list[str] = []
    seen: set[str] = set()

    for seg in segments:
        if seg.get("type") != "json":
            continue

        raw_data = seg.get("data", {}).get("data", "")
        if not isinstance(raw_data, str) or not raw_data:
            continue

        # 反转义 HTML 实体
        raw_data = html.unescape(raw_data)

        try:
            json_data = json.loads(raw_data)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(json_data, dict):
            continue

        urls_to_check: list[str] = []

        meta = json_data.get("meta")
        if isinstance(meta, dict):
            # detail_1 结构（QQ 小程序卡片）
            detail_1 = meta.get("detail_1")
            if isinstance(detail_1, dict):
                qqdocurl = detail_1.get("qqdocurl", "")
                if qqdocurl:
                    urls_to_check.append(str(qqdocurl))

            # news 结构
            news = meta.get("news")
            if isinstance(news, dict):
                jump_url = news.get("jumpUrl", "")
                if jump_url:
                    urls_to_check.append(str(jump_url))

        for url in urls_to_check:
            for opus_id in await extract_opus_ids_with_shortlinks(url):
                if opus_id not in seen:
                    seen.add(opus_id)
                    opus_ids.append(opus_id)

    return opus_ids
