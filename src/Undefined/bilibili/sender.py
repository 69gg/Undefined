"""B 站视频发送。"""

from __future__ import annotations

from collections.abc import Iterable
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from Undefined.bilibili.danmaku import fetch_danmaku
from Undefined.bilibili.downloader import (
    QUALITY_MAP,
    cleanup_file,
    download_video,
    get_video_info,
)
from Undefined.bilibili.models import DanmakuItem
from Undefined.bilibili.parser import normalize_to_bvid

if TYPE_CHECKING:
    from Undefined.bilibili.downloader import VideoInfo
    from Undefined.onebot import OneBotClient
    from Undefined.utils.sender import MessageSender

logger = logging.getLogger(__name__)

_BOT_NAME = "Undefined"
_DEFAULT_BOT_UIN = "10000"


def _format_count(value: int) -> str:
    if value < 0:
        value = 0
    if value >= 100_000_000:
        return f"{value / 100_000_000:.1f}亿"
    if value >= 10_000:
        return f"{value / 10_000:.1f}万"
    return str(value)


def _format_duration(seconds: int) -> str:
    seconds = max(0, seconds)
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _format_progress(progress_ms: int) -> str:
    seconds = max(0, progress_ms) // 1000
    return _format_duration(seconds)


def _chunked(items: list[DanmakuItem], size: int) -> Iterable[list[DanmakuItem]]:
    size = max(1, size)
    for index in range(0, len(items), size):
        yield items[index : index + size]


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
    info: "VideoInfo", *, prefix: str = ""
) -> list[dict[str, Any]]:
    stats = info.stats
    lines: list[str] = []
    if prefix:
        lines.append(prefix.rstrip())
    lines.extend(
        [
            f"「{info.title}」",
            f"UP主: {info.up_name or '未知'}",
            f"时长: {_format_duration(info.duration)}",
            (
                "数据: "
                f"播放 {_format_count(stats.view)} | "
                f"点赞 {_format_count(stats.like)} | "
                f"投币 {_format_count(stats.coin)} | "
                f"收藏 {_format_count(stats.favorite)} | "
                f"弹幕 {_format_count(stats.danmaku)} | "
                f"评论 {_format_count(stats.reply)} | "
                f"分享 {_format_count(stats.share)}"
            ),
        ]
    )
    desc = info.desc.strip()
    if desc:
        lines.extend(["---", desc])
    lines.extend(["---", info.url])

    segments: list[dict[str, Any]] = []
    if info.cover_url:
        segments.append({"type": "image", "data": {"file": info.cover_url}})
    segments.append({"type": "text", "data": {"text": "\n".join(lines)}})
    return segments


def _build_video_history_message(
    info: "VideoInfo",
    *,
    quality_name: str | None,
    file_size_mb: float | None,
    video_status: str,
    danmaku_count: int,
) -> str:
    stats = info.stats
    lines = [
        f"[Bilibili] 「{info.title}」",
        f"UP主: {info.up_name}",
        f"时长: {_format_duration(info.duration)}",
        (
            "数据: "
            f"播放 {_format_count(stats.view)} | "
            f"点赞 {_format_count(stats.like)} | "
            f"投币 {_format_count(stats.coin)} | "
            f"收藏 {_format_count(stats.favorite)} | "
            f"弹幕 {_format_count(stats.danmaku)} | "
            f"评论 {_format_count(stats.reply)} | "
            f"分享 {_format_count(stats.share)}"
        ),
    ]
    if quality_name and file_size_mb is not None:
        lines.append(f"清晰度: {quality_name} | 大小: {file_size_mb:.1f}MB")
    lines.append(f"视频: {video_status}")
    lines.append(f"弹幕: {danmaku_count} 条")
    desc = info.desc.strip()
    if desc:
        lines.append(f"简介: {desc}")
    lines.append(info.url)
    return "\n".join(lines)


def _build_danmaku_text(item: DanmakuItem) -> str:
    return f"[{_format_progress(item.progress_ms)}] {item.content}"


def _build_danmaku_groups(
    danmaku: list[DanmakuItem],
    *,
    batch_size: int,
) -> list[dict[str, Any]]:
    if not danmaku:
        return [_node("未获取到弹幕")]

    groups: list[dict[str, Any]] = []
    for group_index, batch in enumerate(_chunked(danmaku, batch_size), start=1):
        start = (group_index - 1) * batch_size + 1
        end = start + len(batch) - 1
        inner_nodes = [
            _node(_build_danmaku_text(item), name=_format_progress(item.progress_ms))
            for item in batch
        ]
        groups.append(
            _node(
                inner_nodes,
                name=f"弹幕 {start}-{end}",
            )
        )
    return groups


def _build_forward_nodes(
    info: "VideoInfo",
    *,
    video_path: Path | None,
    video_status: str,
    info_prefix: str = "",
    danmaku: list[DanmakuItem] | None,
    danmaku_error: str | None,
    batch_size: int,
) -> list[dict[str, Any]]:
    info_node = _node(_build_info_segments(info, prefix=info_prefix), name="视频信息")

    if video_path is not None:
        video_content: str | list[dict[str, Any]] = [
            {
                "type": "video",
                "data": {"file": f"file://{video_path.resolve()}"},
            }
        ]
    else:
        video_content = video_status
    video_node = _node(video_content, name="视频")

    danmaku_content: str | list[dict[str, Any]]
    if danmaku_error:
        danmaku_content = f"弹幕获取失败: {danmaku_error}"
    else:
        danmaku_items = danmaku or []
        danmaku_content = _build_danmaku_groups(danmaku_items, batch_size=batch_size)
    danmaku_node = _node(danmaku_content, name="弹幕")
    return [info_node, video_node, danmaku_node]


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
            target_id,
            nodes,
            history_message=history_message,
        )
    else:
        await sender.send_private_forward_message(
            target_id,
            nodes,
            history_message=history_message,
        )


async def _fetch_danmaku_best_effort(
    info: "VideoInfo",
    *,
    cookie: str,
    enabled: bool,
    max_count: int,
) -> tuple[list[DanmakuItem], str | None]:
    if not enabled:
        return [], None
    try:
        return await fetch_danmaku(info, cookie=cookie, max_count=max_count), None
    except Exception as exc:
        logger.warning("[Bilibili] 弹幕获取失败: bvid=%s err=%s", info.bvid, exc)
        return [], str(exc)


async def send_bilibili_video(
    video_id: str,
    sender: MessageSender,
    onebot: OneBotClient,
    target_type: Literal["group", "private"],
    target_id: int,
    cookie: str = "",
    prefer_quality: int = 80,
    max_duration: int = 0,
    max_file_size: int = 0,
    oversize_strategy: str = "downgrade",
    sessdata: str = "",
    danmaku_enabled: bool = True,
    danmaku_batch_size: int = 100,
    danmaku_max_count: int = 0,
) -> str:
    """下载并发送 B 站视频合并转发。"""
    _ = onebot
    bvid = await normalize_to_bvid(video_id)
    if not bvid:
        return f"无法解析视频标识: {video_id}"

    if not cookie and sessdata:
        cookie = sessdata

    video_path: Path | None = None
    video_info: VideoInfo | None = None
    actual_qn = 0
    file_size_mb: float | None = None
    quality_name: str | None = None
    video_status = "未发送视频"
    info_prefix = ""

    try:
        video_path, video_info, actual_qn = await download_video(
            bvid=bvid,
            cookie=cookie,
            prefer_quality=prefer_quality,
            max_duration=max_duration,
        )

        if video_path is None:
            video_status = (
                f"视频时长 {_format_duration(video_info.duration)} 超过限制，仅发送信息"
            )
            info_prefix = f"({video_status})"
        else:
            file_size_mb = video_path.stat().st_size / 1024 / 1024
            max_size = max_file_size if max_file_size > 0 else float("inf")

            if file_size_mb > max_size:
                if oversize_strategy == "downgrade" and actual_qn > 32:
                    cleanup_file(video_path)
                    video_path = None
                    lower_qn = _get_lower_quality(actual_qn)
                    logger.info(
                        "[Bilibili] 文件 %.1fMB 超限 %dMB，降级到 qn=%d 重试",
                        file_size_mb,
                        max_file_size,
                        lower_qn,
                    )
                    video_path, video_info, actual_qn = await download_video(
                        bvid=bvid,
                        cookie=cookie,
                        prefer_quality=lower_qn,
                        max_duration=max_duration,
                    )
                    if video_path is not None:
                        file_size_mb = video_path.stat().st_size / 1024 / 1024

                if video_path is not None and file_size_mb is not None:
                    if file_size_mb > max_size:
                        cleanup_file(video_path)
                        video_path = None
                        video_status = (
                            f"视频文件 {file_size_mb:.1f}MB 超过限制，仅发送信息"
                        )
                        info_prefix = f"({video_status})"
                elif video_path is None:
                    video_status = "降级后仍超限，仅发送信息"
                    info_prefix = f"({video_status})"

            if video_path is not None:
                quality_name = QUALITY_MAP.get(actual_qn, str(actual_qn))
                video_status = f"已附加视频 ({quality_name}, {file_size_mb:.1f}MB)"

        danmaku, danmaku_error = await _fetch_danmaku_best_effort(
            video_info,
            cookie=cookie,
            enabled=danmaku_enabled,
            max_count=danmaku_max_count,
        )
        quality_name = QUALITY_MAP.get(actual_qn, str(actual_qn)) if actual_qn else None
        nodes = _build_forward_nodes(
            video_info,
            video_path=video_path,
            video_status=video_status,
            info_prefix=info_prefix,
            danmaku=danmaku,
            danmaku_error=danmaku_error,
            batch_size=danmaku_batch_size,
        )
        await _send_forward(
            sender,
            target_type,
            target_id,
            nodes,
            history_message=_build_video_history_message(
                video_info,
                quality_name=quality_name if video_path is not None else None,
                file_size_mb=file_size_mb if video_path is not None else None,
                video_status=video_status,
                danmaku_count=len(danmaku),
            ),
        )
        return f"已发送 Bilibili 合并转发「{video_info.title}」"

    except Exception as exc:
        logger.exception("[Bilibili] 处理视频失败: %s", bvid)
        try:
            if video_info is None:
                video_info = await get_video_info(bvid, cookie=cookie)
            if video_info is None:
                return f"视频处理失败：无法获取视频信息: {exc}"
            danmaku, danmaku_error = await _fetch_danmaku_best_effort(
                video_info,
                cookie=cookie,
                enabled=danmaku_enabled,
                max_count=danmaku_max_count,
            )
            failure_status = f"视频处理失败: {exc}"
            nodes = _build_forward_nodes(
                video_info,
                video_path=None,
                video_status=failure_status,
                info_prefix=f"({failure_status})",
                danmaku=danmaku,
                danmaku_error=danmaku_error,
                batch_size=danmaku_batch_size,
            )
            await _send_forward(
                sender,
                target_type,
                target_id,
                nodes,
                history_message=_build_video_history_message(
                    video_info,
                    quality_name=None,
                    file_size_mb=None,
                    video_status=failure_status,
                    danmaku_count=len(danmaku),
                ),
            )
            return f"处理失败，已发送 Bilibili 信息合并转发: {exc}"
        except Exception:
            return f"视频处理失败: {exc}"
    finally:
        if video_path is not None:
            cleanup_file(video_path)


def _get_lower_quality(current_qn: int) -> int:
    """获取比当前清晰度低一级的 qn。"""
    ordered = sorted(QUALITY_MAP.keys(), reverse=True)
    for qn in ordered:
        if qn < current_qn:
            return qn
    return 32
