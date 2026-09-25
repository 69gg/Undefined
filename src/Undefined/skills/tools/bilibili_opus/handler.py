from __future__ import annotations

import logging
from typing import Any, Dict, Literal

from Undefined.attachments import scope_from_context
from Undefined.bilibili.opus_parser import DYNAMIC_ID_URL_PATTERN, OPUS_URL_PATTERN
from Undefined.bilibili.opus_render import format_opus_info
from Undefined.bilibili.opus_sender import (
    fetch_bilibili_opus_attachment,
    fetch_opus_info,
    send_opus,
)
from Undefined.bilibili.parser import SHORT_URL_PATTERN, resolve_short_url

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


async def _normalize_opus_id(raw: str) -> str | None:
    """把动态 ID / 图文链接 / 短链统一成裸动态 ID。"""
    text = raw.strip()
    if not text:
        return None
    if text.isdigit():
        return text

    for pattern in (OPUS_URL_PATTERN, DYNAMIC_ID_URL_PATTERN):
        match = pattern.search(text)
        if match:
            return match.group(1)

    if SHORT_URL_PATTERN.search(text):
        real_url = await resolve_short_url(text)
        if real_url:
            return await _normalize_opus_id(real_url)
    return None


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    """获取并发送 Bilibili 图文（opus）。"""
    raw_id = str(args.get("opus_id", "") or "").strip()
    if not raw_id:
        return "opus_id 不能为空"

    output_mode = str(args.get("output_mode", "send") or "send").strip().lower()
    if output_mode not in {"send", "uid", "info"}:
        return "output_mode 只能是 send、uid 或 info"

    runtime_config = context.get("runtime_config")
    sender = context.get("sender")
    onebot = context.get("onebot_client") or context.get("onebot")
    if not onebot and sender is not None and hasattr(sender, "onebot"):
        onebot = getattr(sender, "onebot")

    cookie = ""
    if runtime_config:
        cookie = getattr(runtime_config, "bilibili_cookie", "")

    try:
        opus_id = await _normalize_opus_id(raw_id)
        if not opus_id:
            return f"无法解析图文标识: {raw_id}"

        if output_mode == "info":
            return format_opus_info(await fetch_opus_info(opus_id, cookie=cookie))

        if output_mode == "uid":
            attachment_registry = context.get("attachment_registry")
            scope_key = str(context.get("scope_key") or "").strip()
            if not scope_key:
                scope_key = scope_from_context(context) or ""
            max_images_raw = args.get("max_images")
            try:
                max_images = int(max_images_raw) if max_images_raw is not None else 9
            except (TypeError, ValueError):
                return "max_images 必须是整数"
            if max_images <= 0:
                return "max_images 必须大于 0"
            return await fetch_bilibili_opus_attachment(
                opus_id,
                attachment_registry=attachment_registry,
                scope_key=scope_key,
                cookie=cookie,
                config=runtime_config,
                max_images=max_images,
            )

        target, error = _resolve_target(args, context)
        if error or target is None:
            return f"目标解析失败: {error or '参数错误'}"
        target_type, target_id = target

        if not sender or not onebot:
            return "缺少必要的运行时组件（sender/onebot）"

        return await send_opus(
            opus_id,
            sender=sender,
            target_type=target_type,
            target_id=target_id,
            cookie=cookie,
            config=runtime_config,
        )
    except Exception as exc:
        logger.exception("[bilibili_opus] 执行失败: %s", exc)
        return f"图文处理失败: {exc}"
