"""B 站同步 API 客户端。"""

from __future__ import annotations

from typing import Any

import httpx

from Undefined.bilibili.errors import ApiResponseError
from Undefined.bilibili.models import VideoInfo, VideoStats
from Undefined.bilibili.wbi import build_signed_params_sync, parse_cookie_string

_BILIBILI_API_VIEW = "https://api.bilibili.com/x/web-interface/view"
_BILIBILI_API_VIEW_WBI = "https://api.bilibili.com/x/web-interface/wbi/view"
_BILIBILI_API_PLAYURL = "https://api.bilibili.com/x/player/playurl"
_BILIBILI_API_PLAYURL_WBI = "https://api.bilibili.com/x/player/wbi/playurl"

DEFAULT_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.bilibili.com",
}


def _api_message(data: dict[str, Any]) -> str:
    return str(data.get("message") or data.get("msg") or "未知错误")


def _int_field(data: dict[str, Any], key: str, default: int = 0) -> int:
    raw = data.get(key, default)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


class BilibiliApiClient:
    """基于 httpx.Client 的 B 站同步接口客户端。

    下载流程运行在 `asyncio.to_thread` 中，因此这里保持同步实现，避免在
    线程内再嵌套事件循环。
    """

    def __init__(self, *, cookie: str = "", timeout: float = 30.0) -> None:
        self._client = httpx.Client(
            headers=DEFAULT_HEADERS,
            cookies=parse_cookie_string(cookie),
            timeout=timeout,
            follow_redirects=True,
        )

    @property
    def http_client(self) -> httpx.Client:
        """底层同步 HTTP 客户端。"""
        return self._client

    def close(self) -> None:
        """关闭底层连接池。"""
        self._client.close()

    def __enter__(self) -> BilibiliApiClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _request_json(self, endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
        response = self._client.get(endpoint, params=params)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ApiResponseError("B 站 API 返回不是 JSON 对象")
        return payload

    def request_with_wbi_fallback(
        self,
        *,
        endpoint: str,
        params: dict[str, Any],
        signed_endpoint: str | None = None,
    ) -> dict[str, Any]:
        """按普通请求、WBI 签名、刷新 WBI key 后签名的顺序请求。"""
        wbi_endpoint = signed_endpoint or endpoint
        payload = self._request_json(endpoint, params)
        if int(payload.get("code", -1)) == 0:
            return payload

        try:
            signed_params = build_signed_params_sync(self._client, params)
        except Exception:
            return payload

        signed_payload = self._request_json(wbi_endpoint, signed_params)
        if int(signed_payload.get("code", -1)) == 0:
            return signed_payload

        try:
            refreshed_params = build_signed_params_sync(
                self._client,
                params,
                force_refresh=True,
            )
        except Exception:
            return signed_payload

        if refreshed_params == signed_params:
            return signed_payload
        return self._request_json(wbi_endpoint, refreshed_params)

    def get_video_info(self, bvid: str) -> VideoInfo:
        """获取视频基本信息。"""
        payload = self.request_with_wbi_fallback(
            endpoint=_BILIBILI_API_VIEW,
            signed_endpoint=_BILIBILI_API_VIEW_WBI,
            params={"bvid": bvid},
        )
        if int(payload.get("code", -1)) != 0:
            raise ApiResponseError(f"获取视频信息失败: {_api_message(payload)}")

        data = payload.get("data")
        if not isinstance(data, dict):
            raise ApiResponseError("视频信息响应缺少 data")

        pages = data.get("pages")
        if not isinstance(pages, list) or not pages:
            raise ApiResponseError("视频信息响应缺少分 P 信息")

        page0 = pages[0]
        if not isinstance(page0, dict) or "cid" not in page0:
            raise ApiResponseError("视频信息响应缺少 cid")

        owner = data.get("owner")
        owner_name = ""
        if isinstance(owner, dict):
            owner_name = str(owner.get("name", ""))

        stat = data.get("stat")
        stats = VideoStats()
        if isinstance(stat, dict):
            stats = VideoStats(
                view=_int_field(stat, "view"),
                danmaku=_int_field(stat, "danmaku"),
                reply=_int_field(stat, "reply"),
                favorite=_int_field(stat, "favorite"),
                coin=_int_field(stat, "coin"),
                share=_int_field(stat, "share"),
                like=_int_field(stat, "like"),
            )

        return VideoInfo(
            bvid=bvid,
            aid=_int_field(data, "aid"),
            title=str(data.get("title", "")),
            duration=int(data.get("duration", 0)),
            cover_url=str(data.get("pic", "")),
            up_name=owner_name,
            desc=str(data.get("desc", "")),
            cid=int(page0["cid"]),
            page_duration=_int_field(page0, "duration"),
            stats=stats,
        )

    def get_playurl(self, bvid: str, cid: int) -> dict[str, Any]:
        """获取 DASH 播放流信息。"""
        payload = self.request_with_wbi_fallback(
            endpoint=_BILIBILI_API_PLAYURL,
            signed_endpoint=_BILIBILI_API_PLAYURL_WBI,
            params={
                "bvid": bvid,
                "cid": cid,
                "fnval": 16,
                "fourk": 1,
            },
        )
        if int(payload.get("code", -1)) != 0:
            raise ApiResponseError(f"获取播放流失败: {_api_message(payload)}")

        data = payload.get("data")
        if not isinstance(data, dict):
            raise ApiResponseError("播放流响应缺少 data")
        return data
