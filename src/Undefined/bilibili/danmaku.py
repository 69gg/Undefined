"""Bilibili 弹幕获取与 protobuf wire 解析。"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
import logging
import math
from typing import Any

import httpx

from Undefined.bilibili.api_client import DEFAULT_HEADERS
from Undefined.bilibili.errors import ApiResponseError
from Undefined.bilibili.models import DanmakuItem, VideoInfo
from Undefined.bilibili.wbi import build_signed_params, parse_cookie_string

logger = logging.getLogger(__name__)

_DANMAKU_SEG_ENDPOINT = "https://api.bilibili.com/x/v2/dm/web/seg.so"
_DANMAKU_SEG_WBI_ENDPOINT = "https://api.bilibili.com/x/v2/dm/wbi/web/seg.so"
_SEGMENT_SECONDS = 6 * 60
_MAX_SEGMENTS = 300


@dataclass(slots=True, frozen=True)
class _ProtoField:
    number: int
    wire_type: int
    value: int | bytes


def _read_varint(data: bytes, offset: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while offset < len(data):
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if byte < 0x80:
            return value, offset
        shift += 7
        if shift >= 64:
            raise ValueError("protobuf varint 过长")
    raise ValueError("protobuf varint 未结束")


def _iter_fields(data: bytes) -> Iterator[_ProtoField]:
    offset = 0
    data_len = len(data)
    while offset < data_len:
        key, offset = _read_varint(data, offset)
        field_number = key >> 3
        wire_type = key & 0x07
        if field_number <= 0:
            raise ValueError("protobuf 字段编号非法")

        if wire_type == 0:
            value, offset = _read_varint(data, offset)
            yield _ProtoField(field_number, wire_type, value)
        elif wire_type == 1:
            end = offset + 8
            if end > data_len:
                raise ValueError("protobuf fixed64 越界")
            yield _ProtoField(field_number, wire_type, data[offset:end])
            offset = end
        elif wire_type == 2:
            size, offset = _read_varint(data, offset)
            end = offset + size
            if end > data_len:
                raise ValueError("protobuf length-delimited 越界")
            yield _ProtoField(field_number, wire_type, data[offset:end])
            offset = end
        elif wire_type == 5:
            end = offset + 4
            if end > data_len:
                raise ValueError("protobuf fixed32 越界")
            yield _ProtoField(field_number, wire_type, data[offset:end])
            offset = end
        else:
            raise ValueError(f"不支持的 protobuf wire type: {wire_type}")


def _as_int(value: int | bytes) -> int:
    return int(value) if isinstance(value, int) else 0


def _as_text(value: int | bytes) -> str:
    if not isinstance(value, bytes):
        return ""
    return value.decode("utf-8", errors="replace")


def _parse_danmaku_elem(data: bytes) -> DanmakuItem | None:
    dmid = ""
    dmid_numeric = 0
    progress_ms = 0
    mode = 0
    color = 0
    mid_hash = ""
    content = ""
    ctime = 0
    weight = 0
    pool = 0

    for field in _iter_fields(data):
        if field.number == 1 and field.wire_type == 0:
            dmid_numeric = _as_int(field.value)
        elif field.number == 2 and field.wire_type == 0:
            progress_ms = _as_int(field.value)
        elif field.number == 3 and field.wire_type == 0:
            mode = _as_int(field.value)
        elif field.number == 5 and field.wire_type == 0:
            color = _as_int(field.value)
        elif field.number == 6 and field.wire_type == 2:
            mid_hash = _as_text(field.value)
        elif field.number == 7 and field.wire_type == 2:
            content = _as_text(field.value).strip()
        elif field.number == 8 and field.wire_type == 0:
            ctime = _as_int(field.value)
        elif field.number == 9 and field.wire_type == 0:
            weight = _as_int(field.value)
        elif field.number == 11 and field.wire_type == 0:
            pool = _as_int(field.value)
        elif field.number == 12 and field.wire_type == 2:
            dmid = _as_text(field.value)

    if not content:
        return None
    if not dmid and dmid_numeric:
        dmid = str(dmid_numeric)
    return DanmakuItem(
        progress_ms=max(0, progress_ms),
        content=content,
        dmid=dmid,
        mode=mode,
        pool=pool,
        ctime=ctime,
        mid_hash=mid_hash,
        color=color,
        weight=weight,
    )


def parse_danmaku_segment(data: bytes) -> list[DanmakuItem]:
    """解析 DmSegMobileReply 二进制弹幕包。"""
    items: list[DanmakuItem] = []
    for field in _iter_fields(data):
        if (
            field.number != 1
            or field.wire_type != 2
            or not isinstance(field.value, bytes)
        ):
            continue
        item = _parse_danmaku_elem(field.value)
        if item is not None:
            items.append(item)
    return items


def _segment_count(info: VideoInfo) -> int:
    duration = info.page_duration or info.duration
    if duration <= 0:
        return 1
    return min(max(1, math.ceil(duration / _SEGMENT_SECONDS)), _MAX_SEGMENTS)


async def _fetch_segment(
    client: httpx.AsyncClient,
    *,
    endpoint: str,
    params: dict[str, Any],
) -> bytes:
    response = await client.get(endpoint, params=params)
    response.raise_for_status()
    return response.content


async def _fetch_segment_with_wbi_fallback(
    client: httpx.AsyncClient,
    *,
    params: dict[str, Any],
) -> bytes:
    try:
        return await _fetch_segment(
            client, endpoint=_DANMAKU_SEG_ENDPOINT, params=params
        )
    except httpx.HTTPError as exc:
        last_error: Exception = exc

    try:
        signed_params = await build_signed_params(client, params)
        return await _fetch_segment(
            client,
            endpoint=_DANMAKU_SEG_WBI_ENDPOINT,
            params=signed_params,
        )
    except Exception as exc:
        last_error = exc

    try:
        signed_params = await build_signed_params(client, params, force_refresh=True)
        return await _fetch_segment(
            client,
            endpoint=_DANMAKU_SEG_WBI_ENDPOINT,
            params=signed_params,
        )
    except Exception as exc:
        raise ApiResponseError(f"获取弹幕失败: {exc}") from last_error


async def fetch_danmaku(
    info: VideoInfo,
    *,
    cookie: str = "",
    max_count: int = 0,
    timeout: float = 30.0,
) -> list[DanmakuItem]:
    """获取当前视频首 P 的 protobuf 分段弹幕。"""
    if info.cid <= 0:
        return []

    headers = dict(DEFAULT_HEADERS)
    headers["Referer"] = info.url
    cookies = parse_cookie_string(cookie)
    items: list[DanmakuItem] = []

    async with httpx.AsyncClient(
        headers=headers,
        cookies=cookies,
        timeout=timeout,
        follow_redirects=True,
    ) as client:
        for segment_index in range(1, _segment_count(info) + 1):
            params: dict[str, Any] = {
                "type": 1,
                "oid": info.cid,
                "segment_index": segment_index,
            }
            if info.aid > 0:
                params["pid"] = info.aid

            try:
                content = await _fetch_segment_with_wbi_fallback(client, params=params)
                items.extend(parse_danmaku_segment(content))
            except Exception as exc:
                logger.warning(
                    "[Bilibili] 弹幕分段获取失败: bvid=%s cid=%s segment=%s err=%s",
                    info.bvid,
                    info.cid,
                    segment_index,
                    exc,
                )
                if not items:
                    raise
                break

            if max_count > 0 and len(items) >= max_count:
                break

    items.sort(key=lambda item: (item.progress_ms, item.ctime, item.dmid))
    if max_count > 0:
        return items[:max_count]
    return items
