"""B 站图文（opus）标识符解析。

从消息文本 / 消息段中提取图文 ID。支持：

- ``https://www.bilibili.com/opus/<动态id>``（含 ``m.`` 子域与无协议头写法）
- ``https://t.bilibili.com/<动态id>``
- ``https://b23.tv/<短链>``（解析后二次提取）
- QQ 小程序 / news 分享卡片中的跳转链接

与 ``parser.extract_bilibili_ids`` 独立：图文 ID 与 BV 号互不干扰。
"""

from __future__ import annotations

from collections.abc import Collection
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


_DIRECT_URL_PATTERNS = (OPUS_URL_PATTERN, DYNAMIC_ID_URL_PATTERN)


def _collect_direct_ids(text: str) -> list[tuple[int, str]]:
    """收集直链图文 ID，返回 ``(位置, ID)`` 并按出现顺序排列。

    两条正则分两趟扫会打乱顺序（``t.bilibili.com/9`` 写在
    ``bilibili.com/opus/8`` 前面也会先返回 8），因此按位置统一排序。
    """
    matches: list[tuple[int, str]] = []
    for pattern in _DIRECT_URL_PATTERNS:
        for match in pattern.finditer(text):
            matches.append((match.start(), match.group(1)))
    matches.sort(key=lambda item: item[0])
    return matches


def _extract_opus_ids_from_text(text: str) -> list[str]:
    """从纯文本中提取图文 ID（不做短链解析，同步操作）。"""
    opus_ids: list[str] = []
    seen: set[str] = set()
    for _position, opus_id in _collect_direct_ids(text):
        if opus_id in seen:
            continue
        seen.add(opus_id)
        opus_ids.append(opus_id)
    return opus_ids


def _append_unique(target: list[str], seen: set[str], opus_id: str) -> bool:
    if not opus_id or opus_id in seen:
        return False
    seen.add(opus_id)
    target.append(opus_id)
    return True


def _remaining(max_items: int | None, collected: int) -> int | None:
    """把总预算换算成剩余名额；``None`` 表示不限。"""
    return None if max_items is None else max(0, max_items - collected)


async def extract_opus_ids_with_shortlinks(
    text: str, *, limit: int | None = None
) -> list[str]:
    """从纯文本中提取图文 ID，并解析 b23.tv 短链后二次提取（去重、保序）。

    ``limit`` 给出发送预算时，直链与短链按在文本中的出现顺序统一排队，
    先出现的先占名额；名额用完后剩余短链不再请求（每个短链一次 HEAD 请求，
    超时配置最长 480 秒）。
    """
    max_items = None if limit is None else max(0, int(limit))
    if max_items == 0:
        return []

    # 直链与短链按位置合并成一个序列，保证「先出现的先返回」
    entries: list[tuple[int, str, bool]] = [
        (position, opus_id, True) for position, opus_id in _collect_direct_ids(text)
    ]
    entries.extend(
        (match.start(), match.group(0), False)
        for match in SHORT_URL_PATTERN.finditer(text)
    )
    entries.sort(key=lambda item: item[0])

    opus_ids: list[str] = []
    seen: set[str] = set()
    for _position, payload, is_direct in entries:
        if is_direct:
            _append_unique(opus_ids, seen, payload)
        else:
            if max_items is not None and len(opus_ids) >= max_items:
                # 预算已满：后面的短链不必再解析
                break
            real_url = await resolve_short_url(payload)
            if real_url:
                for resolved_id in _extract_opus_ids_from_text(real_url):
                    _append_unique(opus_ids, seen, resolved_id)
        if max_items is not None and len(opus_ids) >= max_items:
            break

    return opus_ids[:max_items] if max_items is not None else opus_ids


async def extract_opus_from_json_message(
    segments: list[dict[str, Any]],
    *,
    limit: int | None = None,
    exclude: Collection[str] = (),
) -> list[str]:
    """从 QQ 消息段中检测 JSON 小程序消息，提取 B 站图文 ID。

    ``limit`` 给出剩余发送预算：名额用完后不再解析后续卡片的短链。
    ``exclude`` 是已知 ID（例如正文里已经命中的），它们不占用预算，
    避免重复卡片把名额吃光后漏掉真正的新图文。
    """
    max_items = None if limit is None else max(0, int(limit))
    if max_items == 0:
        return []

    opus_ids: list[str] = []
    seen: set[str] = set(exclude)

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
            if max_items is not None and len(opus_ids) >= max_items:
                break
            resolved = await extract_opus_ids_with_shortlinks(
                url, limit=_remaining(max_items, len(opus_ids))
            )
            for opus_id in resolved:
                _append_unique(opus_ids, seen, opus_id)
        if max_items is not None and len(opus_ids) >= max_items:
            break

    return opus_ids[:max_items] if max_items is not None else opus_ids
