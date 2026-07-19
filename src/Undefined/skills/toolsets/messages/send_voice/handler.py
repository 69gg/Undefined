from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from Undefined.skills.toolsets.messages.context_utils import mark_message_sent

logger = logging.getLogger(__name__)

_AUDIO_SUFFIXES = frozenset(
    {
        ".aac",
        ".flac",
        ".m4a",
        ".mp3",
        ".ogg",
        ".opus",
        ".silk",
        ".wav",
        ".webm",
        ".wma",
    }
)


def _is_audio_record(record: Any) -> bool:
    media_type = str(getattr(record, "media_type", "") or "").strip().lower()
    mime_type = str(getattr(record, "mime_type", "") or "").strip().lower()
    display_name = str(getattr(record, "display_name", "") or "").strip()
    return (
        media_type in {"audio", "record"}
        or mime_type.startswith("audio/")
        or Path(display_name).suffix.lower() in _AUDIO_SUFFIXES
    )


async def execute(args: dict[str, Any], context: dict[str, Any]) -> str:
    """将会话附件显式发送为语音，不接受模型提供任意本地路径。"""

    uid = str(args.get("uid", "") or "").strip()
    if not uid:
        return "发送失败：音频附件 UID 不能为空"

    resolve_address = context.get("resolve_delivery_address")
    scope_getter = context.get("get_scope_from_context")
    registry = context.get("attachment_registry")
    sender = context.get("sender")
    if not callable(resolve_address) or not callable(scope_getter):
        return "发送失败：投递地址服务未设置"
    if registry is None or sender is None:
        return "发送失败：附件或消息服务未设置"

    target, target_error = resolve_address(args, context)
    if target_error or target is None:
        return f"发送失败：{target_error or '无法确定投递地址'}"
    scope_key = scope_getter(context)
    if not scope_key:
        return "发送失败：无法确定当前附件作用域"

    try:
        record = await registry.resolve_async(uid, scope_key)
        if record is None:
            return f"发送失败：附件 UID 不可用或不属于当前会话：{uid}"
        if not _is_audio_record(record):
            return "发送失败：该附件不是支持的音频文件"
        record = await registry.ensure_local_file(record)
        local_path = str(getattr(record, "local_path", "") or "").strip()
        if not local_path:
            return "发送失败：音频附件无法获取本地文件"
        send_address_voice = getattr(sender, "send_address_voice", None)
        if not callable(send_address_voice):
            return "发送失败：当前消息服务不支持语音投递"
        sent_message_id = await send_address_voice(
            target,
            local_path,
            name=str(getattr(record, "display_name", "") or "").strip() or None,
        )
        mark_message_sent(context)
    except ValueError as exc:
        return f"发送失败：{exc}"
    except Exception:
        logger.exception("[语音发送] 投递失败: uid=%s", uid)
        return "发送失败：语音服务暂时不可用，请稍后重试"

    normalized_id = str(sent_message_id or "").strip()
    if normalized_id:
        return f"语音已发送（message_id={normalized_id}）"
    return "语音已发送"
