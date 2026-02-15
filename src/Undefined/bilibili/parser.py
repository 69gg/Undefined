"""B 站标识符解析

从消息文本/消息段中提取 B 站视频 BV 号。
支持 BV 号、AV 号、完整 URL、b23.tv 短链、QQ 小程序 JSON。
"""

from __future__ import annotations

import html
import json
import logging
import re
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ---------- 正则 ----------

BV_PATTERN = re.compile(r"BV1[1-9A-HJ-NP-Za-km-z]{9}")
AV_PATTERN = re.compile(r"av(\d+)", re.IGNORECASE)
URL_PATTERN = re.compile(
    r"(?:https?://)?(?:www\.|m\.)?bilibili\.com/video/(BV1[1-9A-HJ-NP-Za-km-z]{9}|av\d+)",
    re.IGNORECASE,
)
SHORT_URL_PATTERN = re.compile(r"(?:https?://)?b23\.tv/([A-Za-z0-9]+)")

# ---------- AV → BV 转换 ----------

_AV2BV_TABLE = "fZodR9XQDSUm21yCkr6zBqiveYah8bt4xsWpHnJE7jL5VG3guMTKNPAwcF"
_AV2BV_TR = {c: i for i, c in enumerate(_AV2BV_TABLE)}
_AV2BV_S = [11, 10, 3, 8, 4, 6]
_AV2BV_XOR = 177451812
_AV2BV_ADD = 8728348608


def av_to_bv(avid: int) -> str:
    """将 AV 号转换为 BV 号。"""
    avid = (avid ^ _AV2BV_XOR) + _AV2BV_ADD
    bv = list("BV1  4 1 7  ")
    for i, pos in enumerate(_AV2BV_S):
        bv[pos] = _AV2BV_TABLE[avid // 58**i % 58]
    return "".join(bv)


# ---------- 短链解析 ----------


async def resolve_short_url(short_url: str) -> str | None:
    """解析 b23.tv 短链，返回真实 URL。"""
    if not short_url.startswith("http"):
        short_url = f"https://{short_url}"
    try:
        async with httpx.AsyncClient(follow_redirects=False, timeout=480) as client:
            resp = await client.head(short_url)
            location: str | None = resp.headers.get("Location") or resp.headers.get(
                "location"
            )
            if location:
                return str(location)
    except Exception as exc:
        logger.warning("[Bilibili] 解析短链失败 %s: %s", short_url, exc)
    return None


# ---------- 标准化 ----------


async def normalize_to_bvid(identifier: str) -> str | None:
    """将各种格式的 B 站视频标识统一转换为 BV 号。"""
    identifier = identifier.strip()

    # 直接是 BV 号
    m = BV_PATTERN.search(identifier)
    if m:
        return m.group(0)

    # b23.tv 短链
    m = SHORT_URL_PATTERN.search(identifier)
    if m:
        real_url = await resolve_short_url(m.group(0))
        if real_url:
            bv = BV_PATTERN.search(real_url)
            if bv:
                return bv.group(0)
            # 短链可能跳转到 av 号 URL
            av = AV_PATTERN.search(real_url)
            if av:
                return av_to_bv(int(av.group(1)))
        return None

    # 完整 URL
    m = URL_PATTERN.search(identifier)
    if m:
        vid = m.group(1)
        if vid.upper().startswith("BV"):
            return vid
        if vid.lower().startswith("av"):
            return av_to_bv(int(vid[2:]))
        return None

    # AV 号
    m = AV_PATTERN.fullmatch(identifier)
    if m:
        return av_to_bv(int(m.group(1)))

    return None


def _extract_bvids_from_text(text: str) -> list[str]:
    """从纯文本中提取所有 BV 号（不做短链解析，同步操作）。"""
    bvids: list[str] = []
    seen: set[str] = set()

    # 从完整 URL 提取
    for m in URL_PATTERN.finditer(text):
        vid = m.group(1)
        if vid.upper().startswith("BV"):
            bvid = vid
        elif vid.lower().startswith("av"):
            bvid = av_to_bv(int(vid[2:]))
        else:
            continue
        if bvid not in seen:
            seen.add(bvid)
            bvids.append(bvid)

    # 从裸 BV 号提取
    for m in BV_PATTERN.finditer(text):
        bvid = m.group(0)
        if bvid not in seen:
            seen.add(bvid)
            bvids.append(bvid)

    # 从裸 AV 号提取（仅独立出现的）
    for m in re.finditer(r"\bav(\d+)\b", text, re.IGNORECASE):
        bvid = av_to_bv(int(m.group(1)))
        if bvid not in seen:
            seen.add(bvid)
            bvids.append(bvid)

    return bvids


async def extract_bilibili_ids(text: str) -> list[str]:
    """从纯文本中提取所有 B 站视频 BV 号（包括短链解析，去重）。"""
    bvids: list[str] = []
    seen: set[str] = set()

    # 先处理同步可提取的
    for bvid in _extract_bvids_from_text(text):
        if bvid not in seen:
            seen.add(bvid)
            bvids.append(bvid)

    # 处理 b23.tv 短链
    for m in SHORT_URL_PATTERN.finditer(text):
        short_url = m.group(0)
        real_url = await resolve_short_url(short_url)
        if real_url:
            for bvid in _extract_bvids_from_text(real_url):
                if bvid not in seen:
                    seen.add(bvid)
                    bvids.append(bvid)

    return bvids


async def extract_from_json_message(segments: list[dict[str, Any]]) -> list[str]:
    """从 QQ 消息段中检测 JSON 小程序消息，提取 B 站视频 BV 号。"""
    bvids: list[str] = []
    seen: set[str] = set()

    for seg in segments:
        if seg.get("type") != "json":
            continue

        raw_data = seg.get("data", {}).get("data", "")
        if not raw_data:
            continue

        # 反转义 HTML 实体
        raw_data = html.unescape(raw_data)

        try:
            json_data = json.loads(raw_data)
        except (json.JSONDecodeError, TypeError):
            continue

        # 提取可能包含 B 站链接的字段
        urls_to_check: list[str] = []

        meta = json_data.get("meta", {})
        # detail_1 结构（QQ 小程序卡片）
        detail_1 = meta.get("detail_1", {})
        if detail_1:
            qqdocurl = detail_1.get("qqdocurl", "")
            if qqdocurl:
                urls_to_check.append(qqdocurl)

        # news 结构
        news = meta.get("news", {})
        if news:
            jump_url = news.get("jumpUrl", "")
            if jump_url:
                urls_to_check.append(jump_url)

        # 遍历所有找到的 URL
        for url in urls_to_check:
            resolved_bvids = await extract_bilibili_ids(url)
            for bvid in resolved_bvids:
                if bvid not in seen:
                    seen.add(bvid)
                    bvids.append(bvid)

    return bvids
