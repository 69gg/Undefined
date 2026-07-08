import logging
from typing import Any, Dict, Literal

from Undefined.attachments import scope_from_context
from Undefined.bilibili.downloader import get_video_info
from Undefined.bilibili.parser import normalize_to_bvid
from Undefined.bilibili.sender import (
    fetch_bilibili_video_attachment,
    format_bilibili_video_info,
    send_bilibili_video,
)

logger = logging.getLogger(__name__)


def _resolve_target(
    args: Dict[str, Any], context: Dict[str, Any]
) -> tuple[tuple[Literal["group", "private"], int] | None, str | None]:
    """解析目标会话，复用 send_message 的逻辑模式。"""
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
    if request_type == "group":
        group_id = context.get("group_id")
        if group_id:
            return ("group", int(group_id)), None
    elif request_type == "private":
        user_id = context.get("user_id")
        if user_id:
            return ("private", int(user_id)), None

    group_id = context.get("group_id")
    if group_id:
        return ("group", int(group_id)), None
    user_id = context.get("user_id")
    if user_id:
        return ("private", int(user_id)), None

    return None, "无法确定目标会话，请提供 target_type 与 target_id"


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    """下载并发送 Bilibili 视频"""
    video_id = args.get("video_id", "")
    if not video_id:
        return "video_id 不能为空"

    output_mode = str(args.get("output_mode", "send") or "send").strip().lower()
    if output_mode not in {"send", "uid", "info"}:
        return "output_mode 只能是 send、uid 或 info"

    runtime_config = context.get("runtime_config")
    sender = context.get("sender")
    onebot = context.get("onebot_client") or context.get("onebot")
    if not onebot and sender is not None and hasattr(sender, "onebot"):
        onebot = getattr(sender, "onebot")

    cookie = ""
    prefer_quality = 80
    max_duration = 600
    max_file_size = 100
    oversize_strategy = "downgrade"
    danmaku_enabled = True
    danmaku_batch_size = 100
    danmaku_max_count = 0

    if runtime_config:
        cookie = getattr(
            runtime_config,
            "bilibili_cookie",
            getattr(runtime_config, "bilibili_sessdata", ""),
        )
        prefer_quality = getattr(runtime_config, "bilibili_prefer_quality", 80)
        max_duration = getattr(runtime_config, "bilibili_max_duration", 600)
        max_file_size = getattr(runtime_config, "bilibili_max_file_size", 100)
        oversize_strategy = getattr(
            runtime_config, "bilibili_oversize_strategy", "downgrade"
        )
        danmaku_enabled = getattr(runtime_config, "bilibili_danmaku_enabled", True)
        danmaku_batch_size = getattr(runtime_config, "bilibili_danmaku_batch_size", 100)
        danmaku_max_count = getattr(runtime_config, "bilibili_danmaku_max_count", 0)

    try:
        if output_mode == "info":
            bvid = await normalize_to_bvid(str(video_id))
            if not bvid:
                return f"无法解析视频标识: {video_id}"
            video_info = await get_video_info(bvid, cookie=cookie)
            return format_bilibili_video_info(video_info)

        if output_mode == "uid":
            attachment_registry = context.get("attachment_registry")
            scope_key = str(context.get("scope_key") or "").strip()
            if not scope_key:
                scope_key = scope_from_context(context) or ""
            return await fetch_bilibili_video_attachment(
                video_id=str(video_id),
                attachment_registry=attachment_registry,
                scope_key=scope_key,
                cookie=cookie,
                prefer_quality=prefer_quality,
                max_duration=max_duration,
                max_file_size=max_file_size,
                oversize_strategy=oversize_strategy,
            )

        target, error = _resolve_target(args, context)
        if error or target is None:
            return f"目标解析失败: {error or '参数错误'}"
        target_type, target_id = target

        if not sender or not onebot:
            return "缺少必要的运行时组件（sender/onebot）"

        result = await send_bilibili_video(
            video_id=video_id,
            sender=sender,
            onebot=onebot,
            target_type=target_type,
            target_id=target_id,
            cookie=cookie,
            prefer_quality=prefer_quality,
            max_duration=max_duration,
            max_file_size=max_file_size,
            oversize_strategy=oversize_strategy,
            danmaku_enabled=danmaku_enabled,
            danmaku_batch_size=danmaku_batch_size,
            danmaku_max_count=danmaku_max_count,
        )
        return result
    except Exception as exc:
        logger.exception("[bilibili_video] 执行失败: %s", exc)
        return f"视频处理失败: {exc}"
