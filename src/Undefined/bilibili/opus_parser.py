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


def _extend_unique(target: list[str], seen: set[str], candidates: list[str]) -> None:
    for opus_id in candidates:
        if opus_id not in seen:
            seen.add(opus_id)
            target.append(opus_id)


async def extract_opus_ids_with_shortlinks(
    text: str, *, limit: int | None = None
) -> list[str]:
    """从纯文本中提取图文 ID，并解析 b23.tv 短链后二次提取（去重、保序）。

    ``limit`` 给出发送预算时，解析短链的数量会按剩余名额收敛，避免一条消息
    里塞了多个短链时把用不到的短链都请求一遍。
    """
    max_items = None if limit is None else max(0, int(limit))
    if max_items == 0:
        return []

    opus_ids: list[str] = []
    seen: set[str] = set()

    _extend_unique(opus_ids, seen, _extract_opus_ids_from_text(text))
    if max_items is not None and len(opus_ids) >= max_items:
        return opus_ids

    for match in SHORT_URL_PATTERN.finditer(text):
        real_url = await resolve_short_url(match.group(0))
        if not real_url:
            continue
        _extend_unique(opus_ids, seen, _extract_opus_ids_from_text(real_url))
        if max_items is not None and len(opus_ids) >= max_items:
            break

    return opus_ids[:max_items] if max_items is not None else opus_ids


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
            _extend_unique(
                opus_ids,
                seen,
                await extract_opus_ids_with_shortlinks(url),
            )

    return opus_ids
