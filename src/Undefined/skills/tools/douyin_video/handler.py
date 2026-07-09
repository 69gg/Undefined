from __future__ import annotations

import logging
from typing import Any, Literal

from Undefined.attachments import scope_from_context
from Undefined.douyin.client import get_video_info
from Undefined.douyin.downloader import DEFAULT_RATIOS
from Undefined.douyin.sender import (
    fetch_douyin_video_attachment,
    format_douyin_video_info,
    send_douyin_video,
)

logger = logging.getLogger(__name__)


def _resolve_target(
    args: dict[str, Any], context: dict[str, Any]
) -> tuple[tuple[Literal["group", "private"], int] | None, str | None]:
    target_type_raw = args.get("target_type")
    target_id_raw = args.get("target_id")

    if target_type_raw is not None and target_id_raw is not None:
        target_type = str(target_type_raw).strip().lower()
        if target_type not in ("group", "private"):
            return None, "target_type 只能是 group 或 private"
        try:
            target_id = int(target_id_raw)
        except (TypeError, ValueError):
            return None, "target_id 必须是整数"
        return (target_type, target_id), None  # type: ignore[return-value]

    request_type = context.get("request_type")
    if request_type == "group" and context.get("group_id"):
        return ("group", int(context["group_id"])), None
    if request_type == "private" and context.get("user_id"):
        return ("private", int(context["user_id"])), None

    if context.get("group_id"):
        return ("group", int(context["group_id"])), None
    if context.get("user_id"):
        return ("private", int(context["user_id"])), None
    return None, "无法确定目标会话，请提供 target_type 与 target_id"


def _runtime_douyin_options(
    runtime_config: Any | None,
) -> tuple[int, int, tuple[str, ...]]:
    max_duration = 600
    max_file_size = 100
    prefer_ratios: tuple[str, ...] = DEFAULT_RATIOS
    if runtime_config is not None:
        max_duration = int(getattr(runtime_config, "douyin_max_duration", 600))
        max_file_size = int(getattr(runtime_config, "douyin_max_file_size", 100))
        raw_ratios = getattr(runtime_config, "douyin_prefer_ratios", None)
        if raw_ratios:
            prefer_ratios = tuple(str(item) for item in raw_ratios if str(item).strip())
    return max_duration, max_file_size, prefer_ratios or DEFAULT_RATIOS


async def execute(args: dict[str, Any], context: dict[str, Any]) -> str:
    """下载并发送抖音视频。"""

    video_id = str(args.get("video_id", "")).strip()
    if not video_id:
        return "video_id 不能为空"

    output_mode = str(args.get("output_mode", "send") or "send").strip().lower()
    if output_mode not in {"send", "uid", "info"}:
        return "output_mode 只能是 send、uid 或 info"

    runtime_config = context.get("runtime_config")
    max_duration, max_file_size, prefer_ratios = _runtime_douyin_options(runtime_config)

    try:
        if output_mode == "info":
            video_info = await get_video_info(video_id, config=runtime_config)
            return format_douyin_video_info(video_info)

        if output_mode == "uid":
            attachment_registry = context.get("attachment_registry")
            scope_key = str(context.get("scope_key") or "").strip()
            if not scope_key:
                scope_key = scope_from_context(context) or ""
            return await fetch_douyin_video_attachment(
                video_id=video_id,
                attachment_registry=attachment_registry,
                scope_key=scope_key,
                max_duration=max_duration,
                max_file_size=max_file_size,
                prefer_ratios=prefer_ratios,
                config=runtime_config,
            )

        target, error = _resolve_target(args, context)
        if error or target is None:
            return f"目标解析失败: {error or '参数错误'}"
        target_type, target_id = target

        sender = context.get("sender")
        if sender is None:
            return "缺少必要的运行时组件（sender）"

        return await send_douyin_video(
            video_id=video_id,
            sender=sender,
            target_type=target_type,
            target_id=target_id,
            max_duration=max_duration,
            max_file_size=max_file_size,
            prefer_ratios=prefer_ratios,
            config=runtime_config,
        )
    except Exception as exc:
        logger.exception("[douyin_video] 执行失败: %s", exc)
        return f"抖音视频处理失败: {exc}"
