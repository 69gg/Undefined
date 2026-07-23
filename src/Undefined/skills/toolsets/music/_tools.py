"""User-facing implementations for the lxmusic2api music toolset."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Protocol, cast

from Undefined.skills.toolsets.music._client import (
    MusicToolError,
    quote_path_segment,
    request_data,
    runtime_config,
    stream_data,
)


class AttachmentRecord(Protocol):
    uid: str
    display_name: str
    mime_type: str | None


class AttachmentRegistry(Protocol):
    async def register_bytes(
        self,
        scope_key: str,
        content: bytes,
        *,
        kind: str,
        display_name: str,
        source_kind: str,
        source_ref: str = "",
        mime_type: str | None = None,
        segment_data: Mapping[str, str] | None = None,
    ) -> AttachmentRecord: ...

    async def register_remote_url(
        self,
        scope_key: str,
        url: str,
        *,
        kind: str,
        display_name: str | None = None,
        source_kind: str = "remote_url",
        source_ref: str = "",
        segment_data: Mapping[str, str] | None = None,
    ) -> AttachmentRecord: ...


_SOURCE_VALUES = frozenset({"all", "kw", "kg", "tx", "wy", "mg"})
_PROVIDER_VALUES = frozenset({"kw", "kg", "tx", "wy", "mg"})
_QUALITY_VALUES = frozenset({"flac24bit", "flac", "wav", "ape", "320k", "192k", "128k"})
_QUALITY_SUFFIXES: dict[str, str] = {
    "flac24bit": ".flac",
    "flac": ".flac",
    "wav": ".wav",
    "ape": ".ape",
    "320k": ".mp3",
    "192k": ".mp3",
    "128k": ".mp3",
}
_MIME_SUFFIXES: dict[str, str] = {
    "audio/aac": ".aac",
    "audio/flac": ".flac",
    "audio/mp4": ".m4a",
    "audio/mpeg": ".mp3",
    "audio/ogg": ".ogg",
    "audio/opus": ".opus",
    "audio/wav": ".wav",
    "audio/x-ape": ".ape",
    "audio/x-flac": ".flac",
    "audio/x-wav": ".wav",
}
_UNSAFE_FILE_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _error(exc: MusicToolError) -> str:
    return f"音乐服务调用失败：{exc}"


def _text(args: Mapping[str, Any], key: str, default: str = "") -> str:
    return str(args.get(key, default) or "").strip()


def _positive_int(
    args: Mapping[str, Any], key: str, default: int, *, maximum: int
) -> int:
    raw_value = args.get(key, default)
    try:
        value = int(cast(Any, raw_value))
    except (TypeError, ValueError):
        value = default
    return min(max(value, 1), maximum)


def _source(args: Mapping[str, Any], *, allow_all: bool) -> str:
    default = "all" if allow_all else "wy"
    source = _text(args, "source", default).lower()
    allowed = _SOURCE_VALUES if allow_all else _PROVIDER_VALUES
    if source not in allowed:
        values = "、".join(sorted(allowed))
        raise MusicToolError(f"source 必须是 {values} 之一")
    return source


def _track(args: Mapping[str, Any]) -> dict[str, object]:
    raw_track = args.get("track")
    if not isinstance(raw_track, dict):
        raise MusicToolError("track 必须是搜索、歌单或排行榜返回的完整 Track 对象")
    return {str(key): value for key, value in raw_track.items()}


def _track_label(track: Mapping[str, object]) -> str:
    name = str(track.get("name", "") or "").strip() or "music"
    singer = str(track.get("singer", "") or "").strip()
    return f"{name} - {singer}" if singer else name


def _boolean(args: Mapping[str, Any], key: str, default: bool = False) -> bool:
    value = args.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return bool(value)


def _attachment_context(
    context: dict[str, Any],
) -> tuple[AttachmentRegistry, str]:
    registry_value = context.get("attachment_registry")
    scope_getter_value = context.get("get_scope_from_context")
    if registry_value is None:
        raise MusicToolError("附件系统未初始化")
    if not callable(scope_getter_value):
        raise MusicToolError("无法确定当前附件作用域")
    scope_getter = cast(Callable[[dict[str, Any]], object], scope_getter_value)
    scope_key = str(scope_getter(context) or "").strip()
    if not scope_key:
        raise MusicToolError("无法确定当前附件作用域")
    return cast(AttachmentRegistry, registry_value), scope_key


def _audio_file_name(
    track: Mapping[str, object], content_type: str, requested_quality: str
) -> str:
    label = _UNSAFE_FILE_CHARS.sub("_", _track_label(track)).strip(" .")
    if not label:
        label = "music"
    label = label[:120].rstrip(" .") or "music"
    suffix = _MIME_SUFFIXES.get(content_type.lower())
    if suffix is None:
        suffix = _QUALITY_SUFFIXES.get(requested_quality, ".audio")
    return f"{label}{suffix}"


def _resolve_body(
    args: Mapping[str, Any], track: dict[str, object]
) -> dict[str, object]:
    body: dict[str, object] = {
        "track": track,
        "strictQuality": _boolean(args, "strict_quality"),
    }
    quality = _text(args, "quality")
    if quality:
        if quality not in _QUALITY_VALUES:
            raise MusicToolError("quality 不是支持的音质值")
        body["quality"] = quality
    return body


async def execute_search_songs(args: dict[str, Any], context: dict[str, Any]) -> str:
    try:
        query = _text(args, "query")
        if not query:
            raise MusicToolError("query 不能为空")
        data = await request_data(
            context,
            "GET",
            "/search/tracks",
            params={
                "q": query,
                "source": _source(args, allow_all=True),
                "page": _positive_int(args, "page", 1, maximum=100000),
                "limit": _positive_int(args, "limit", 20, maximum=100),
            },
        )
        return _json(data)
    except MusicToolError as exc:
        return _error(exc)


async def execute_search_playlists(
    args: dict[str, Any], context: dict[str, Any]
) -> str:
    try:
        query = _text(args, "query")
        if not query:
            raise MusicToolError("query 不能为空")
        data = await request_data(
            context,
            "GET",
            "/search/playlists",
            params={
                "q": query,
                "source": _source(args, allow_all=True),
                "page": _positive_int(args, "page", 1, maximum=100000),
                "limit": _positive_int(args, "limit", 20, maximum=100),
            },
        )
        return _json(data)
    except MusicToolError as exc:
        return _error(exc)


async def execute_get_hot_search(args: dict[str, Any], context: dict[str, Any]) -> str:
    try:
        data = await request_data(
            context,
            "GET",
            "/search/hot",
            params={"source": _source(args, allow_all=True)},
        )
        return _json(data)
    except MusicToolError as exc:
        return _error(exc)


async def execute_browse_playlists(
    args: dict[str, Any], context: dict[str, Any]
) -> str:
    try:
        action = _text(args, "action").lower()
        source = _source(args, allow_all=False)
        encoded_source = quote_path_segment(source)
        if action == "tags":
            data = await request_data(
                context, "GET", f"/playlists/{encoded_source}/tags"
            )
        elif action == "list":
            data = await request_data(
                context,
                "GET",
                f"/playlists/{encoded_source}",
                params={
                    "tagId": _text(args, "tag_id"),
                    "sortId": _text(args, "sort_id"),
                    "page": _positive_int(args, "page", 1, maximum=100000),
                },
            )
        elif action == "detail":
            playlist_id = quote_path_segment(_text(args, "playlist_id"))
            data = await request_data(
                context,
                "GET",
                f"/playlists/{encoded_source}/{playlist_id}",
                params={"page": _positive_int(args, "page", 1, maximum=100000)},
            )
        else:
            raise MusicToolError("action 必须是 tags、list 或 detail")
        return _json(data)
    except MusicToolError as exc:
        return _error(exc)


async def execute_browse_rankings(args: dict[str, Any], context: dict[str, Any]) -> str:
    try:
        action = _text(args, "action").lower()
        source = quote_path_segment(_source(args, allow_all=False))
        if action == "list":
            data = await request_data(context, "GET", f"/leaderboards/{source}")
        elif action == "detail":
            ranking_id = quote_path_segment(_text(args, "ranking_id"))
            data = await request_data(
                context,
                "GET",
                f"/leaderboards/{source}/{ranking_id}",
                params={"page": _positive_int(args, "page", 1, maximum=100000)},
            )
        else:
            raise MusicToolError("action 必须是 list 或 detail")
        return _json(data)
    except MusicToolError as exc:
        return _error(exc)


async def execute_get_lyrics(args: dict[str, Any], context: dict[str, Any]) -> str:
    try:
        data = await request_data(
            context, "POST", "/tracks/lyrics", json_body={"track": _track(args)}
        )
        return _json(data)
    except MusicToolError as exc:
        return _error(exc)


async def execute_get_cover(args: dict[str, Any], context: dict[str, Any]) -> str:
    try:
        track = _track(args)
        data = await request_data(
            context, "POST", "/tracks/cover", json_body={"track": track}
        )
        if not isinstance(data, dict):
            raise MusicToolError("封面响应格式无效")
        url = str(data.get("url", "") or "").strip()
        if not url:
            raise MusicToolError("该歌曲没有可用封面")
        delivery = _text(args, "delivery", "attachment").lower()
        if delivery == "url":
            return _json(data)
        if delivery != "attachment":
            raise MusicToolError("delivery 必须是 attachment 或 url")

        registry, scope_key = _attachment_context(context)
        record = await registry.register_remote_url(
            scope_key,
            url,
            kind="image",
            display_name=f"{_track_label(track)} cover",
            source_kind="lxmusic2api_cover",
            source_ref=url,
            segment_data={
                "track_id": str(track.get("id", "") or ""),
                "source": str(track.get("source", "") or ""),
            },
        )
        mime_type = str(record.mime_type or "").lower()
        if mime_type and not mime_type.startswith("image/"):
            raise MusicToolError(f"封面地址返回了非图片内容：{mime_type}")
        return _json(
            {
                "attachment": f'<attachment uid="{record.uid}"/>',
                "uid": record.uid,
                "url": url,
            }
        )
    except MusicToolError as exc:
        return _error(exc)
    except (OSError, ValueError) as exc:
        return f"封面附件注册失败：{exc}"
    except Exception:
        return "封面附件注册失败：附件服务暂时不可用"


async def execute_get_comments(args: dict[str, Any], context: dict[str, Any]) -> str:
    try:
        track = _track(args)
        mode = _text(args, "mode", "latest").lower()
        page = _positive_int(args, "page", 1, maximum=100000)
        limit = _positive_int(args, "limit", 20, maximum=100)
        if mode in {"latest", "hot"}:
            data = await request_data(
                context,
                "POST",
                "/tracks/comments",
                json_body={
                    "track": track,
                    "kind": mode,
                    "page": page,
                    "limit": limit,
                },
            )
        elif mode == "replies":
            comment_id = quote_path_segment(_text(args, "comment_id"))
            data = await request_data(
                context,
                "POST",
                f"/tracks/comments/{comment_id}/replies",
                json_body={"track": track, "page": page, "limit": limit},
            )
        else:
            raise MusicToolError("mode 必须是 latest、hot 或 replies")
        return _json(data)
    except MusicToolError as exc:
        return _error(exc)


async def execute_find_song_matches(
    args: dict[str, Any], context: dict[str, Any]
) -> str:
    try:
        data = await request_data(
            context, "POST", "/tracks/matches", json_body={"track": _track(args)}
        )
        return _json(data)
    except MusicToolError as exc:
        return _error(exc)


async def execute_get_audio(args: dict[str, Any], context: dict[str, Any]) -> str:
    try:
        track = _track(args)
        body = _resolve_body(args, track)
        delivery = _text(args, "delivery", "attachment").lower()
        if delivery == "url":
            data = await request_data(
                context, "POST", "/tracks/resolve", json_body=body
            )
            return _json(data)
        if delivery != "attachment":
            raise MusicToolError("delivery 必须是 attachment 或 url")

        registry, scope_key = _attachment_context(context)
        config = runtime_config(context)
        max_bytes = max(int(config.attachment_remote_download_max_size_mb), 0)
        payload = await stream_data(
            context,
            "/tracks/stream",
            json_body=body,
            max_bytes=max_bytes * 1024 * 1024,
        )
        quality = _text(args, "quality")
        display_name = _audio_file_name(track, payload.content_type, quality)
        source = str(track.get("source", "") or "")
        track_id = str(track.get("id", "") or "")
        record = await registry.register_bytes(
            scope_key,
            payload.content,
            kind="audio",
            display_name=display_name,
            source_kind="lxmusic2api_audio",
            source_ref=f"lxmusic2api:{source}:{track_id}",
            mime_type=payload.content_type or None,
            segment_data={
                "track_id": track_id,
                "source": source,
                "requested_quality": quality or "default",
            },
        )
        return _json(
            {
                "attachment": f'<attachment uid="{record.uid}"/>',
                "uid": record.uid,
                "displayName": Path(record.display_name).name,
                "contentType": payload.content_type or record.mime_type,
                "bytes": len(payload.content),
            }
        )
    except MusicToolError as exc:
        return _error(exc)
    except (OSError, ValueError) as exc:
        return f"音频附件注册失败：{exc}"
    except Exception:
        return "音频附件注册失败：附件服务暂时不可用"
