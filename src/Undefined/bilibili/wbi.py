"""Bilibili WBI 签名工具。"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from http.cookies import CookieError, SimpleCookie
from typing import Any, Mapping
from urllib.parse import quote, urlencode, urlparse

import httpx

logger = logging.getLogger(__name__)

_BILIBILI_API_NAV = "https://api.bilibili.com/x/web-interface/nav"

_MIXIN_KEY_ENC_TAB: tuple[int, ...] = (
    46,
    47,
    18,
    2,
    53,
    8,
    23,
    32,
    15,
    50,
    10,
    31,
    58,
    3,
    45,
    35,
    27,
    43,
    5,
    49,
    33,
    9,
    42,
    19,
    29,
    28,
    14,
    39,
    12,
    38,
    41,
    13,
    37,
    48,
    7,
    16,
    24,
    55,
    40,
    61,
    26,
    17,
    0,
    1,
    60,
    51,
    30,
    4,
    22,
    25,
    54,
    21,
    56,
    59,
    6,
    63,
    57,
    62,
    11,
    36,
    20,
    34,
    44,
    52,
)

_WBI_CACHE_TTL_SECONDS = 3600
_cached_mixin_key: str | None = None
_cached_at: float = 0.0
_cache_lock = asyncio.Lock()


def parse_cookie_string(cookie: str = "") -> dict[str, str]:
    """将 Cookie 字符串解析为字典。"""
    raw = cookie.strip()
    if not raw:
        return {}

    if raw.lower().startswith("cookie:"):
        raw = raw[7:].strip()

    if "=" not in raw:
        return {"SESSDATA": raw}

    parsed: dict[str, str] = {}

    simple_cookie = SimpleCookie()
    try:
        simple_cookie.load(raw)
    except CookieError:
        simple_cookie = SimpleCookie()

    if simple_cookie:
        for key, morsel in simple_cookie.items():
            value = morsel.value.strip()
            if key and value:
                parsed[key] = value

    if parsed:
        return parsed

    for part in raw.split(";"):
        item = part.strip()
        if not item or "=" not in item:
            continue
        key, value = item.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key and value:
            parsed[key] = value

    if parsed:
        return parsed

    return {"SESSDATA": raw}


def _extract_key_from_url(url: str) -> str:
    path = urlparse(url).path
    name = path.rsplit("/", 1)[-1]
    return name.split(".", 1)[0]


def _compute_mixin_key(img_key: str, sub_key: str) -> str:
    merged = img_key + sub_key
    mixed = "".join(merged[i] for i in _MIXIN_KEY_ENC_TAB)
    return mixed[:32]


async def _refresh_mixin_key(client: httpx.AsyncClient) -> str:
    resp = await client.get(_BILIBILI_API_NAV)
    resp.raise_for_status()
    payload = resp.json()

    if not isinstance(payload, dict):
        raise ValueError("nav 接口返回格式异常")

    code = int(payload.get("code", -1))
    if code not in (0, -101):
        message = payload.get("message", "未知错误")
        raise ValueError(f"获取 wbi key 失败: {message} (code={code})")

    data = payload.get("data")
    if not isinstance(data, dict):
        raise ValueError("nav 接口 data 字段异常")

    wbi_img = data.get("wbi_img")
    if not isinstance(wbi_img, dict):
        raise ValueError("nav 接口 wbi_img 字段缺失")

    img_url = str(wbi_img.get("img_url", "")).strip()
    sub_url = str(wbi_img.get("sub_url", "")).strip()
    if not img_url or not sub_url:
        raise ValueError("nav 接口未返回有效的 img_url/sub_url")

    img_key = _extract_key_from_url(img_url)
    sub_key = _extract_key_from_url(sub_url)
    if not img_key or not sub_key:
        raise ValueError("无法提取有效的 img_key/sub_key")

    return _compute_mixin_key(img_key, sub_key)


async def get_mixin_key(
    client: httpx.AsyncClient,
    *,
    force_refresh: bool = False,
) -> str:
    """获取可复用的 mixin_key。"""
    global _cached_mixin_key, _cached_at

    now = time.time()
    if (
        not force_refresh
        and _cached_mixin_key
        and now - _cached_at < _WBI_CACHE_TTL_SECONDS
    ):
        return _cached_mixin_key

    async with _cache_lock:
        now = time.time()
        if (
            not force_refresh
            and _cached_mixin_key
            and now - _cached_at < _WBI_CACHE_TTL_SECONDS
        ):
            return _cached_mixin_key

        _cached_mixin_key = await _refresh_mixin_key(client)
        _cached_at = now
        return _cached_mixin_key


def sign_params(
    params: Mapping[str, Any],
    mixin_key: str,
    *,
    timestamp: int | None = None,
) -> dict[str, str]:
    """对 Query 参数执行 WBI 签名，返回包含 wts/w_rid 的参数。"""
    normalized: dict[str, str] = {}
    for key, value in params.items():
        if value is None:
            continue
        key_text = str(key).strip()
        if not key_text:
            continue
        value_text = str(value)
        for ch in "!'()*":
            value_text = value_text.replace(ch, "")
        normalized[key_text] = value_text

    normalized["wts"] = str(int(time.time()) if timestamp is None else timestamp)

    ordered = sorted(normalized.items(), key=lambda item: item[0])
    query = urlencode(ordered, safe="-_.~", quote_via=quote)
    w_rid = hashlib.md5((query + mixin_key).encode("utf-8")).hexdigest()
    normalized["w_rid"] = w_rid
    return normalized


async def build_signed_params(
    client: httpx.AsyncClient,
    params: Mapping[str, Any],
    *,
    force_refresh: bool = False,
) -> dict[str, str]:
    """构造带 WBI 签名的参数。"""
    mixin_key = await get_mixin_key(client, force_refresh=force_refresh)
    return sign_params(params, mixin_key)
