"""Douyin share-page client."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Mapping
from urllib.parse import urlsplit

import httpx

from Undefined.douyin.models import DouyinVideoInfo
from Undefined.douyin.parser import canonical_share_url, normalize_aweme_id
from Undefined.skills.http_config import build_httpx_client_kwargs, get_request_timeout

logger = logging.getLogger(__name__)

_TTID_REGISTER_URL = "https://ttid.bytedance.com/ttid/union/register/"
_DEFAULT_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 13; Pixel 7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Mobile Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}
_ROUTER_DATA_PATTERN = re.compile(
    r"window\._ROUTER_DATA\s*=\s*(\{.*?\})\s*</script>",
    re.DOTALL,
)
_TTID_LOCK = asyncio.Lock()
_TTID_CACHE: str | None = None


class DouyinParseError(RuntimeError):
    """Raised when a Douyin share page cannot be parsed."""


def _text(value: Any) -> str:
    return str(value or "").strip()


def _int_ms_to_seconds(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    if parsed > 10_000:
        return max(0, parsed // 1000)
    return max(0, parsed)


def _find_first_key(value: Any, key: str) -> Any:
    if isinstance(value, Mapping):
        if key in value:
            return value[key]
        for child in value.values():
            found = _find_first_key(child, key)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_first_key(child, key)
            if found is not None:
                return found
    return None


def _iter_dicts(value: Any) -> list[Mapping[str, Any]]:
    found: list[Mapping[str, Any]] = []
    if isinstance(value, Mapping):
        found.append(value)
        for child in value.values():
            found.extend(_iter_dicts(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_iter_dicts(child))
    return found


def _select_aweme_detail(router_data: Mapping[str, Any]) -> Mapping[str, Any]:
    candidates: list[Mapping[str, Any]] = []
    for item in _iter_dicts(router_data):
        aweme_detail = item.get("aweme_detail")
        if isinstance(aweme_detail, Mapping):
            candidates.append(aweme_detail)
        aweme = item.get("aweme")
        if isinstance(aweme, Mapping):
            candidates.append(aweme)
        if "video" in item and ("aweme_id" in item or "desc" in item):
            candidates.append(item)

    for candidate in candidates:
        video = candidate.get("video")
        if isinstance(video, Mapping):
            play_addr = video.get("play_addr")
            if isinstance(play_addr, Mapping):
                return candidate
    reason = _format_filter_reason(router_data)
    if reason:
        raise DouyinParseError(f"share 页缺少 aweme_detail.video.play_addr: {reason}")
    raise DouyinParseError("share 页缺少 aweme_detail.video.play_addr")


def _format_filter_reason(router_data: Mapping[str, Any]) -> str:
    for item in _iter_dicts(router_data):
        filter_list = item.get("filter_list")
        if not isinstance(filter_list, list):
            continue
        messages: list[str] = []
        for entry in filter_list:
            if not isinstance(entry, Mapping):
                continue
            reason = _text(entry.get("filter_reason"))
            detail = _text(entry.get("detail_msg")) or _text(entry.get("notice"))
            aweme_id = _text(entry.get("aweme_id"))
            parts = [part for part in (aweme_id, reason, detail) if part]
            if parts:
                messages.append(" / ".join(parts))
        if messages:
            return "; ".join(messages)
    return ""


def _first_string(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        for item in value:
            text = _first_string(item)
            if text:
                return text
    return ""


def _extract_play_token(play_addr: Mapping[str, Any]) -> str:
    uri = _text(play_addr.get("uri"))
    if uri:
        return uri
    token = _text(play_addr.get("video_id"))
    if token:
        return token
    url_key = play_addr.get("url_key")
    if isinstance(url_key, str) and url_key.strip():
        parts = url_key.split("_")
        if len(parts) >= 2:
            return parts[-2] if parts[-1] in {"h264", "h265"} else parts[-1]
        return url_key.strip()
    url = _first_string(play_addr.get("url_list"))
    if url:
        match = re.search(r"video_id=([^&]+)", url)
        if match:
            return match.group(1)
    raise DouyinParseError("share 页缺少可用的 video token")


def parse_router_data(html_text: str) -> Mapping[str, Any]:
    """Parse ``window._ROUTER_DATA`` from a Douyin share page."""

    match = _ROUTER_DATA_PATTERN.search(html_text)
    if not match:
        raise DouyinParseError("share 页缺少 window._ROUTER_DATA")
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise DouyinParseError("window._ROUTER_DATA 不是合法 JSON") from exc
    if not isinstance(payload, Mapping):
        raise DouyinParseError("window._ROUTER_DATA 不是 JSON 对象")
    return payload


def parse_video_info(
    router_data: Mapping[str, Any],
    *,
    fallback_aweme_id: str,
    share_url: str,
) -> DouyinVideoInfo:
    """Extract video metadata and play token from router data."""

    aweme = _select_aweme_detail(router_data)
    video = aweme.get("video")
    video_data = video if isinstance(video, Mapping) else {}
    play_addr = video_data.get("play_addr")
    if not isinstance(play_addr, Mapping):
        raise DouyinParseError("share 页缺少 video.play_addr")

    author = aweme.get("author")
    author_data = author if isinstance(author, Mapping) else {}
    cover = video_data.get("cover") or video_data.get("origin_cover")
    cover_data = cover if isinstance(cover, Mapping) else {}

    aweme_id = _text(aweme.get("aweme_id")) or fallback_aweme_id
    title = (
        _text(aweme.get("preview_title"))
        or _text(aweme.get("share_title"))
        or _text(aweme.get("desc"))
        or f"抖音视频 {aweme_id}"
    )
    desc = _text(aweme.get("desc"))
    author_name = (
        _text(author_data.get("nickname"))
        or _text(author_data.get("unique_id"))
        or _text(author_data.get("short_id"))
        or "未知作者"
    )
    cover_url = _first_string(cover_data.get("url_list"))
    duration = _int_ms_to_seconds(video_data.get("duration") or aweme.get("duration"))

    return DouyinVideoInfo(
        aweme_id=aweme_id,
        title=title,
        author_name=author_name,
        desc=desc,
        cover_url=cover_url,
        duration=duration,
        share_url=share_url,
        play_token=_extract_play_token(play_addr),
    )


def _extract_ttid(payload: Any) -> str:
    if isinstance(payload, Mapping):
        for key in ("ttid", "client_ttid", "device_id", "install_id"):
            value = _text(payload.get(key))
            if value:
                return value
        data = payload.get("data")
        found = _extract_ttid(data)
        if found:
            return found
        for child in payload.values():
            found = _extract_ttid(child)
            if found:
                return found
    if isinstance(payload, list):
        for child in payload:
            found = _extract_ttid(child)
            if found:
                return found
    return ""


async def get_anonymous_ttid(*, config: Any | None = None) -> str:
    """Fetch and cache an anonymous Bytedance ttid."""

    global _TTID_CACHE
    if _TTID_CACHE:
        return _TTID_CACHE

    async with _TTID_LOCK:
        if _TTID_CACHE:
            return _TTID_CACHE
        timeout_seconds = max(get_request_timeout(15.0), 5.0)
        client_kwargs = build_httpx_client_kwargs(
            _TTID_REGISTER_URL,
            proxy_scope="douyin",
            timeout=timeout_seconds,
            follow_redirects=True,
            headers={
                "User-Agent": _DEFAULT_HEADERS["User-Agent"],
                "Accept": "application/json, text/plain, */*",
            },
            config=config,
        )
        async with httpx.AsyncClient(**client_kwargs) as client:
            response = await client.post(_TTID_REGISTER_URL, json={})
            response.raise_for_status()
        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise DouyinParseError("ttid 注册接口返回不是 JSON") from exc
        ttid = _extract_ttid(payload)
        if not ttid:
            raise DouyinParseError("ttid 注册接口缺少 ttid")
        _TTID_CACHE = ttid
        return ttid


def invalidate_anonymous_ttid() -> None:
    """Clear cached anonymous ttid so the next request registers a fresh value."""

    global _TTID_CACHE
    _TTID_CACHE = None


async def resolve_share_url(identifier: str, *, config: Any | None = None) -> str:
    """Resolve any Douyin identifier to the SSR share-page URL."""

    canonical = canonical_share_url(identifier)
    if canonical is None:
        raise DouyinParseError(f"无法解析抖音视频标识: {identifier}")

    aweme_id = normalize_aweme_id(canonical)
    if aweme_id and "iesdouyin.com/share/video/" in canonical:
        return canonical

    timeout_seconds = max(get_request_timeout(30.0), 5.0)
    client_kwargs = build_httpx_client_kwargs(
        canonical,
        proxy_scope="douyin",
        timeout=timeout_seconds,
        follow_redirects=True,
        headers=_DEFAULT_HEADERS,
        config=config,
    )
    async with httpx.AsyncClient(**client_kwargs) as client:
        response = await client.get(canonical)
        response.raise_for_status()
    final_url = str(response.url)
    final_aweme_id = normalize_aweme_id(final_url)
    if final_aweme_id:
        return f"https://www.iesdouyin.com/share/video/{final_aweme_id}/"
    return final_url


def _is_ttid_auth_error(exc: Exception) -> bool:
    return isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in {
        401,
        403,
    }


async def _fetch_share_page(
    share_url: str,
    *,
    ttid: str,
    config: Any | None,
) -> str:
    timeout_seconds = max(get_request_timeout(30.0), 5.0)
    host = urlsplit(share_url).netloc
    headers = {
        **_DEFAULT_HEADERS,
        "Referer": "https://www.douyin.com/",
        "Host": host,
    }
    if ttid:
        headers["Cookie"] = f"ttwid={ttid}; ttid={ttid}"
    client_kwargs = build_httpx_client_kwargs(
        share_url,
        proxy_scope="douyin",
        timeout=timeout_seconds,
        follow_redirects=True,
        headers=headers,
        config=config,
    )
    async with httpx.AsyncClient(**client_kwargs) as client:
        response = await client.get(share_url)
        response.raise_for_status()
        return response.text


async def get_video_info(
    identifier: str, *, config: Any | None = None
) -> DouyinVideoInfo:
    """Fetch and parse Douyin video metadata from the SSR share page."""

    share_url = await resolve_share_url(identifier, config=config)
    fallback_aweme_id = (
        normalize_aweme_id(share_url) or normalize_aweme_id(identifier) or ""
    )
    ttid = ""
    try:
        ttid = await get_anonymous_ttid(config=config)
    except Exception as exc:
        logger.warning("[Douyin] 获取匿名 ttid 失败，将尝试直接请求 share 页: %s", exc)

    try:
        html_text = await _fetch_share_page(share_url, ttid=ttid, config=config)
    except Exception as exc:
        if not ttid or not _is_ttid_auth_error(exc):
            raise
        logger.warning("[Douyin] 匿名 ttid 可能已失效，刷新后重试: %s", exc)
        invalidate_anonymous_ttid()
        try:
            ttid = await get_anonymous_ttid(config=config)
        except Exception as refresh_exc:
            logger.warning(
                "[Douyin] 刷新匿名 ttid 失败，将尝试直接请求 share 页: %s",
                refresh_exc,
            )
            ttid = ""
        html_text = await _fetch_share_page(share_url, ttid=ttid, config=config)

    router_data = parse_router_data(html_text)
    info = parse_video_info(
        router_data,
        fallback_aweme_id=fallback_aweme_id,
        share_url=share_url,
    )
    logger.info(
        "[Douyin] 解析视频信息完成: aweme_id=%s title=%s", info.aweme_id, info.title
    )
    return info
