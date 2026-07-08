"""Douyin video sending."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from Undefined.douyin.client import get_video_info
from Undefined.douyin.downloader import DEFAULT_RATIOS, cleanup_path, download_video
from Undefined.douyin.models import DouyinVideoInfo
from Undefined.utils.io import get_file_size

if TYPE_CHECKING:
    from Undefined.utils.sender import MessageSender

logger = logging.getLogger(__name__)

_BOT_NAME = "Undefined"
_DEFAULT_BOT_UIN = "10000"


def _format_duration(seconds: int) -> str:
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _node(
    content: str | list[dict[str, Any]], *, name: str = _BOT_NAME
) -> dict[str, Any]:
    return {
        "type": "node",
        "data": {
            "name": name,
            "uin": _DEFAULT_BOT_UIN,
            "content": content,
        },
    }


def _build_info_segments(
    info: DouyinVideoInfo, *, prefix: str = ""
) -> list[dict[str, Any]]:
    lines: list[str] = []
    if prefix:
        lines.append(prefix.rstrip())
    lines.extend(
        [
            f"「{info.title}」",
            f"作者: {info.author_name or '未知'}",
            f"时长: {_format_duration(info.duration)}",
        ]
    )
    if info.desc and info.desc != info.title:
        lines.extend(["---", info.desc])
    lines.extend(["---", info.share_url])

    segments: list[dict[str, Any]] = []
    if info.cover_url:
        segments.append({"type": "image", "data": {"file": info.cover_url}})
    segments.append({"type": "text", "data": {"text": "\n".join(lines)}})
    return segments


def _build_forward_nodes(
    info: DouyinVideoInfo,
    *,
    video_path: Path | None,
    video_status: str,
    info_prefix: str = "",
) -> list[dict[str, Any]]:
    info_node = _node(_build_info_segments(info, prefix=info_prefix), name="视频信息")
    if video_path is not None:
        video_content: str | list[dict[str, Any]] = [
            {"type": "video", "data": {"file": f"file://{video_path.resolve()}"}}
        ]
    else:
        video_content = video_status
    return [info_node, _node(video_content, name="视频")]


def _build_history_message(
    info: DouyinVideoInfo,
    *,
    ratio: str | None,
    file_size_mb: float | None,
    video_status: str,
) -> str:
    lines = [
        f"[Douyin] 「{info.title}」",
        f"作者: {info.author_name}",
        f"时长: {_format_duration(info.duration)}",
    ]
    if ratio and file_size_mb is not None:
        lines.append(f"清晰度: {ratio} | 大小: {file_size_mb:.1f}MB")
    lines.append(f"视频: {video_status}")
    if info.desc and info.desc != info.title:
        lines.append(f"简介: {info.desc}")
    lines.append(info.share_url)
    return "\n".join(lines)


def format_douyin_video_info(info: DouyinVideoInfo) -> str:
    """Format Douyin metadata for tool results."""
    lines = [
        f"「{info.title}」",
        f"ID: {info.aweme_id}",
        f"作者: {info.author_name or '未知'}",
        f"时长: {_format_duration(info.duration)}",
    ]
    if info.desc and info.desc != info.title:
        lines.extend(["---", info.desc])
    if info.cover_url:
        lines.append(f"封面: {info.cover_url}")
    lines.append(info.share_url)
    return "\n".join(lines)


def _build_uid_message(
    info: DouyinVideoInfo,
    *,
    uid: str,
    ratio: str | None,
    file_size_mb: float | None,
    file_name: str,
) -> str:
    lines = [
        f"已获取抖音视频：{info.title}",
        f"ID: {info.aweme_id}",
        f'视频: <attachment uid="{uid}"/>',
    ]
    if ratio and file_size_mb is not None:
        lines.append(f"清晰度: {ratio} | 大小: {file_size_mb:.1f}MB")
    if file_name:
        lines.append(f"文件名: {file_name}")
    lines.append(info.share_url)
    return "\n".join(lines)


async def _send_forward(
    sender: "MessageSender",
    target_type: Literal["group", "private"],
    target_id: int,
    nodes: list[dict[str, Any]],
    *,
    history_message: str,
) -> None:
    if target_type == "group":
        await sender.send_group_forward_message(
            target_id, nodes, history_message=history_message
        )
    else:
        await sender.send_private_forward_message(
            target_id, nodes, history_message=history_message
        )


async def send_douyin_video(
    video_id: str,
    sender: "MessageSender",
    target_type: Literal["group", "private"],
    target_id: int,
    *,
    max_duration: int = 0,
    max_file_size: int = 0,
    prefer_ratios: tuple[str, ...] = DEFAULT_RATIOS,
    config: Any | None = None,
) -> str:
    """Download and send a Douyin video merged-forward message."""

    video_path: Path | None = None
    video_info: DouyinVideoInfo | None = None
    ratio: str | None = None
    file_size_mb: float | None = None
    video_status = "未发送视频"
    info_prefix = ""

    try:
        video_path, video_info, ratio, size_bytes = await download_video(
            video_id,
            max_duration=max_duration,
            max_file_size=max_file_size,
            prefer_ratios=prefer_ratios,
            config=config,
        )
        if video_path is None:
            if max_duration > 0 and video_info.duration > max_duration:
                video_status = f"视频时长 {_format_duration(video_info.duration)} 超过限制，仅发送信息"
            elif size_bytes is not None:
                video_status = (
                    f"视频文件 {size_bytes / 1024 / 1024:.1f}MB 超过限制，仅发送信息"
                )
            else:
                video_status = "视频未下载，仅发送信息"
            info_prefix = f"({video_status})"
        else:
            file_size_mb = await get_file_size(video_path) / 1024 / 1024
            video_status = f"已附加视频 ({ratio or '未知清晰度'}, {file_size_mb:.1f}MB)"

        nodes = _build_forward_nodes(
            video_info,
            video_path=video_path,
            video_status=video_status,
            info_prefix=info_prefix,
        )
        await _send_forward(
            sender,
            target_type,
            target_id,
            nodes,
            history_message=_build_history_message(
                video_info,
                ratio=ratio if video_path is not None else None,
                file_size_mb=file_size_mb if video_path is not None else None,
                video_status=video_status,
            ),
        )
        return f"已发送抖音合并转发「{video_info.title}」"
    except Exception as exc:
        logger.exception("[Douyin] 处理视频失败: %s", video_id)
        if video_info is None:
            try:
                video_info = await get_video_info(video_id, config=config)
            except Exception:
                return f"抖音视频处理失败：无法获取视频信息: {exc}"
        failure_status = f"视频处理失败: {exc}"
        nodes = _build_forward_nodes(
            video_info,
            video_path=None,
            video_status=failure_status,
            info_prefix=f"({failure_status})",
        )
        await _send_forward(
            sender,
            target_type,
            target_id,
            nodes,
            history_message=_build_history_message(
                video_info,
                ratio=None,
                file_size_mb=None,
                video_status=failure_status,
            ),
        )
        return f"处理失败，已发送抖音信息合并转发: {exc}"
    finally:
        if video_path is not None:
            cleanup_path(video_path)


async def fetch_douyin_video_attachment(
    video_id: str,
    *,
    attachment_registry: Any,
    scope_key: str,
    max_duration: int = 0,
    max_file_size: int = 0,
    prefer_ratios: tuple[str, ...] = DEFAULT_RATIOS,
    config: Any | None = None,
) -> str:
    """Download a Douyin video and register it as an attachment UID."""

    if attachment_registry is None:
        return "缺少必要的运行时组件（attachment_registry）"
    if not str(scope_key or "").strip():
        return "无法确定附件作用域，不能注册抖音视频"

    video_path: Path | None = None
    video_info: DouyinVideoInfo | None = None
    try:
        video_path, video_info, ratio, size_bytes = await download_video(
            video_id,
            max_duration=max_duration,
            max_file_size=max_file_size,
            prefer_ratios=prefer_ratios,
            config=config,
        )
        if video_path is None:
            if max_duration > 0 and video_info.duration > max_duration:
                return f"视频时长 {_format_duration(video_info.duration)} 超过限制，未下载视频文件"
            if size_bytes is not None:
                return f"视频文件 {size_bytes / 1024 / 1024:.1f}MB 超过限制，未注册附件"
            return "未下载到抖音视频文件"

        file_size_mb = await get_file_size(video_path) / 1024 / 1024
        record = await attachment_registry.register_local_file(
            scope_key,
            video_path,
            kind="file",
            display_name=video_path.name,
            source_kind="douyin_video",
            source_ref=video_info.share_url,
            segment_data={
                "aweme_id": video_info.aweme_id,
                "url": video_info.share_url,
                "title": video_info.title,
                "ratio": ratio or "",
            },
        )
        return _build_uid_message(
            video_info,
            uid=str(record.uid),
            ratio=ratio,
            file_size_mb=file_size_mb,
            file_name=video_path.name,
        )
    except Exception as exc:
        logger.exception("[Douyin] UID 模式处理视频失败: %s", video_id)
        if video_info is None:
            try:
                video_info = await get_video_info(video_id, config=config)
            except Exception:
                return f"抖音视频处理失败：无法获取视频信息: {exc}"
        return f"抖音视频处理失败：{exc}"
    finally:
        if video_path is not None:
            cleanup_path(video_path)
