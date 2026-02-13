"""B 站视频发送

将下载好的视频或视频信息发送到 QQ。
支持视频文件发送和降级信息卡片发送。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Literal

from Undefined.bilibili.downloader import (
    QUALITY_MAP,
    cleanup_file,
    download_video,
    get_video_info,
)
from Undefined.bilibili.parser import normalize_to_bvid

if TYPE_CHECKING:
    from Undefined.bilibili.downloader import VideoInfo
    from Undefined.onebot import OneBotClient
    from Undefined.utils.sender import MessageSender

logger = logging.getLogger(__name__)


def _build_info_card(info: "VideoInfo", truncate_desc: bool = True) -> str:
    """构造信息卡片消息。"""
    parts: list[str] = []
    if info.cover_url:
        parts.append(f"[CQ:image,file={info.cover_url}]")
    parts.append(f"「{info.title}」")
    parts.append(f"UP主: {info.up_name}")
    desc = info.desc.strip()
    if desc:
        if truncate_desc and len(desc) > 100:
            desc = desc[:100] + "..."
        parts.append(f"简介: {desc}")
    parts.append(f"https://www.bilibili.com/video/{info.bvid}")
    return "\n".join(parts)


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
) -> str:
    """下载并发送 B 站视频。

    Args:
        video_id: BV 号、AV 号或 B 站 URL。
        sender: 消息发送器。
        onebot: OneBot 客户端。
        target_type: 目标会话类型。
        target_id: 目标会话 ID。
        cookie: B 站完整 Cookie 字符串（推荐，至少包含 SESSDATA）。
        prefer_quality: 首选清晰度。
        max_duration: 最大时长限制（秒），0 不限。
        max_file_size: 最大文件大小（MB），0 不限。
        oversize_strategy: 超限策略 "downgrade" 或 "info"。
        sessdata: 兼容旧参数名，等价于 cookie。

    Returns:
        操作结果描述。
    """
    # 解析 BV 号
    bvid = await normalize_to_bvid(video_id)
    if not bvid:
        return f"无法解析视频标识: {video_id}"

    if not cookie and sessdata:
        cookie = sessdata

    try:
        # 下载视频
        video_path, video_info, actual_qn = await download_video(
            bvid=bvid,
            cookie=cookie,
            prefer_quality=prefer_quality,
            max_duration=max_duration,
        )

        # 时长超限 → 发送信息卡片
        if video_path is None:
            card = _build_info_card(video_info)
            duration_min = video_info.duration // 60
            duration_sec = video_info.duration % 60
            hint = (
                f"(视频时长 {duration_min}:{duration_sec:02d} 超过限制，仅发送信息)\n"
            )
            await _send_message(sender, target_type, target_id, hint + card)
            return f"视频时长超限，已发送信息卡片: {video_info.title}"

        # 检查文件大小
        file_size_mb = video_path.stat().st_size / 1024 / 1024
        max_size = max_file_size if max_file_size > 0 else float("inf")

        if file_size_mb > max_size:
            if oversize_strategy == "downgrade" and actual_qn > 32:
                # 降级重试：尝试更低清晰度
                cleanup_file(video_path)
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
                if video_path is None:
                    card = _build_info_card(video_info)
                    await _send_message(sender, target_type, target_id, card)
                    return "降级后仍超限，已发送信息卡片"

                file_size_mb = video_path.stat().st_size / 1024 / 1024
                if file_size_mb > max_size:
                    # 降级后仍然超限，发送信息卡片
                    cleanup_file(video_path)
                    card = _build_info_card(video_info)
                    hint = f"(视频文件 {file_size_mb:.1f}MB 超过限制，仅发送信息)\n"
                    await _send_message(sender, target_type, target_id, hint + card)
                    return "降级后文件仍超限，已发送信息卡片"
            else:
                # info 策略或已是最低清晰度
                cleanup_file(video_path)
                card = _build_info_card(video_info)
                hint = f"(视频文件 {file_size_mb:.1f}MB 超过限制，仅发送信息)\n"
                await _send_message(sender, target_type, target_id, hint + card)
                return "文件超限，已发送信息卡片"

        # 发送视频
        abs_path = str(video_path.resolve())
        quality_name = QUALITY_MAP.get(actual_qn, str(actual_qn))
        logger.info(
            "[Bilibili] 发送视频: %s (%s, %.1fMB) → %s:%s",
            bvid,
            quality_name,
            file_size_mb,
            target_type,
            target_id,
        )

        video_message = f"[CQ:video,file=file://{abs_path}]"
        try:
            # 发视频前先发送封面/标题/UP/完整简介
            pre_video_card = _build_info_card(video_info, truncate_desc=False)
            await _send_message(sender, target_type, target_id, pre_video_card)

            await _send_message(sender, target_type, target_id, video_message)
            result = f"已发送视频「{video_info.title}」({quality_name}, {file_size_mb:.1f}MB)"
        except Exception as exc:
            logger.warning("[Bilibili] 视频发送失败，降级发送信息卡片: %s", exc)
            card = _build_info_card(video_info)
            hint = "(视频发送失败，发送信息卡片)\n"
            await _send_message(sender, target_type, target_id, hint + card)
            result = f"视频发送失败（{exc}），已降级发送信息卡片"
        finally:
            cleanup_file(video_path)

        return result

    except Exception as exc:
        logger.exception("[Bilibili] 处理视频失败: %s", bvid)
        # 尝试发送基本信息
        try:
            info = await get_video_info(bvid, cookie=cookie)
            card = _build_info_card(info)
            hint = f"(视频处理失败: {exc})\n"
            await _send_message(sender, target_type, target_id, hint + card)
            return f"处理失败，已发送信息卡片: {exc}"
        except Exception:
            return f"视频处理失败: {exc}"


def _get_lower_quality(current_qn: int) -> int:
    """获取比当前清晰度低一级的 qn。"""
    ordered = sorted(QUALITY_MAP.keys(), reverse=True)
    for qn in ordered:
        if qn < current_qn:
            return qn
    return 32  # 最低 480P


async def _send_message(
    sender: "MessageSender",
    target_type: Literal["group", "private"],
    target_id: int,
    message: str,
) -> None:
    """根据目标类型发送消息。"""
    if target_type == "group":
        await sender.send_group_message(target_id, message, auto_history=False)
    else:
        await sender.send_private_message(target_id, message, auto_history=False)
