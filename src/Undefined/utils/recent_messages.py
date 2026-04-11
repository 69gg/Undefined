"""最近消息获取工具（本地 history 优先）。"""

from __future__ import annotations

import logging
import re
from typing import Any, cast

from Undefined.attachments import build_attachment_scope
from Undefined.onebot import get_message_content, parse_message_time
from Undefined.utils.common import extract_text
from Undefined.utils.message_utils import fetch_group_messages

logger = logging.getLogger(__name__)

_HISTORY_IMAGE_UID_RE = re.compile(r"\[图片\s+uid=(?P<uid>pic_[^\s\]]+)")


def _normalize_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_range(start: Any, end: Any) -> tuple[int, int]:
    """规范化最近消息区间参数。"""
    start_i = max(0, _normalize_int(start, 0))
    end_i = max(0, _normalize_int(end, 10))
    if end_i < start_i:
        return start_i, start_i
    return start_i, end_i


def _slice_recent(
    messages: list[dict[str, Any]], start: int, end: int
) -> list[dict[str, Any]]:
    """按 MessageHistoryManager.get_recent 的语义切片。"""
    total = len(messages)
    if total == 0:
        return []

    actual_start = total - end
    actual_end = total - start

    if actual_start < 0:
        actual_start = 0
    if actual_end > total:
        actual_end = total
    if actual_start >= actual_end:
        return []

    return messages[actual_start:actual_end]


def _format_group_history_message(
    raw_message: dict[str, Any],
    *,
    group_id: int,
    group_name_hint: str | None,
    bot_qq: int,
) -> dict[str, Any]:
    sender = raw_message.get("sender") or {}
    sender_id = str(sender.get("user_id") or "")
    sender_name = str(
        sender.get("card") or sender.get("nickname") or sender_id or "未知用户"
    )

    message_content = get_message_content(raw_message)
    text_content = extract_text(message_content, bot_qq)
    if not text_content:
        text_content = "(空消息)"

    timestamp = parse_message_time(raw_message).strftime("%Y-%m-%d %H:%M:%S")
    group_name = str(
        raw_message.get("group_name") or group_name_hint or f"群{group_id}"
    )

    return {
        "type": "group",
        "chat_id": str(group_id),
        "chat_name": group_name,
        "user_id": sender_id,
        "display_name": sender_name,
        "role": str(sender.get("role") or "member"),
        "title": str(sender.get("title") or ""),
        "timestamp": timestamp,
        "message": text_content,
    }


def _get_recent_from_history_manager(
    history_manager: Any,
    chat_id: str,
    msg_type: str,
    start: int,
    end: int,
) -> list[dict[str, Any]]:
    if history_manager is None:
        return []
    try:
        return cast(
            list[dict[str, Any]],
            history_manager.get_recent(chat_id, msg_type, start, end),
        )
    except Exception as exc:
        logger.warning("从本地 history 获取最近消息失败: %s", exc)
        return []


def _resolve_scope_key(chat_id: str, msg_type: str) -> str | None:
    if msg_type == "group":
        return build_attachment_scope(group_id=chat_id, request_type="group")
    if msg_type == "private":
        return build_attachment_scope(user_id=chat_id, request_type="private")
    return None


def _normalize_attachment_ref(item: Any) -> dict[str, str] | None:
    if not isinstance(item, dict):
        return None
    uid = str(item.get("uid", "") or "").strip()
    if not uid:
        return None
    normalized: dict[str, str] = {
        "uid": uid,
        "kind": str(item.get("kind") or item.get("media_type") or "file"),
        "media_type": str(item.get("media_type") or item.get("kind") or "file"),
        "display_name": str(item.get("display_name", "") or ""),
    }
    source_kind = str(item.get("source_kind", "") or "").strip()
    if source_kind:
        normalized["source_kind"] = source_kind
    semantic_kind = str(item.get("semantic_kind", "") or "").strip()
    if semantic_kind:
        normalized["semantic_kind"] = semantic_kind
    description = str(item.get("description", "") or "").strip()
    if description:
        normalized["description"] = description
    return normalized


def _resolve_meme_attachment_ref(
    attachment_registry: Any,
    uid: str,
    scope_key: str | None,
) -> dict[str, str] | None:
    if attachment_registry is None:
        return None
    try:
        record = attachment_registry.resolve(uid, scope_key)
    except Exception as exc:
        logger.debug("补全历史附件失败: uid=%s err=%s", uid, exc)
        return None
    if record is None:
        return None
    ref = _normalize_attachment_ref(record.prompt_ref())
    if ref is None:
        return None
    if str(ref.get("source_kind", "") or "").strip() != "meme_library":
        return None
    return ref


def _merge_meme_attachment_ref(
    base_ref: dict[str, str],
    resolved_ref: dict[str, str] | None,
) -> dict[str, str]:
    if resolved_ref is None:
        return base_ref
    merged = dict(base_ref)
    for key in ("source_kind", "semantic_kind", "description"):
        current_value = str(merged.get(key, "") or "").strip()
        if current_value:
            continue
        next_value = str(resolved_ref.get(key, "") or "").strip()
        if next_value:
            merged[key] = next_value
    return merged


def _augment_local_messages_with_meme_attachments(
    messages: list[dict[str, Any]],
    *,
    chat_id: str,
    msg_type: str,
    attachment_registry: Any | None,
) -> list[dict[str, Any]]:
    if attachment_registry is None or not messages:
        return messages

    scope_key = _resolve_scope_key(chat_id, msg_type)
    augmented_messages: list[dict[str, Any]] = []

    for message in messages:
        message_copy = dict(message)
        normalized_attachments: list[dict[str, str]] = []
        raw_attachments = message.get("attachments")
        if isinstance(raw_attachments, list):
            for item in raw_attachments:
                normalized = _normalize_attachment_ref(item)
                if normalized is None:
                    continue
                resolved = _resolve_meme_attachment_ref(
                    attachment_registry,
                    normalized["uid"],
                    scope_key,
                )
                normalized_attachments.append(
                    _merge_meme_attachment_ref(normalized, resolved)
                )

        if not normalized_attachments:
            text = str(message.get("message", "") or "")
            seen_uids: set[str] = set()
            for match in _HISTORY_IMAGE_UID_RE.finditer(text):
                uid = str(match.group("uid") or "").strip()
                if not uid or uid in seen_uids:
                    continue
                seen_uids.add(uid)
                resolved = _resolve_meme_attachment_ref(
                    attachment_registry,
                    uid,
                    scope_key,
                )
                if resolved is not None:
                    normalized_attachments.append(resolved)

        message_copy["attachments"] = normalized_attachments
        augmented_messages.append(message_copy)

    return augmented_messages


async def get_recent_messages_prefer_local(
    *,
    chat_id: str,
    msg_type: str,
    start: int,
    end: int,
    onebot_client: Any | None,
    history_manager: Any | None,
    bot_qq: int,
    attachment_registry: Any | None = None,
    group_name_hint: str | None = None,
    max_onebot_count: int = 5000,
) -> list[dict[str, Any]]:
    """优先从本地 history 获取最近消息，必要时回退到 OneBot。"""
    norm_start, norm_end = _normalize_range(start, end)
    if norm_end <= 0:
        return []

    local_messages = _get_recent_from_history_manager(
        history_manager,
        chat_id,
        msg_type,
        norm_start,
        norm_end,
    )
    if local_messages:
        return _augment_local_messages_with_meme_attachments(
            local_messages,
            chat_id=chat_id,
            msg_type=msg_type,
            attachment_registry=attachment_registry,
        )

    if msg_type == "group" and onebot_client is not None:
        try:
            group_id = int(chat_id)
            onebot_count = min(norm_end, max(1, int(max_onebot_count)))
            raw_messages = await fetch_group_messages(
                onebot_client,
                group_id,
                onebot_count,
                None,
            )

            if raw_messages:
                formatted_messages = [
                    _format_group_history_message(
                        message,
                        group_id=group_id,
                        group_name_hint=group_name_hint,
                        bot_qq=bot_qq,
                    )
                    for message in raw_messages
                ]
                formatted_messages.sort(key=lambda item: str(item.get("timestamp", "")))
                return _slice_recent(formatted_messages, norm_start, norm_end)
        except (TypeError, ValueError):
            logger.debug("群聊 chat_id 不是数字，无法回退到 OneBot: %s", chat_id)
        except Exception as exc:
            logger.warning("从 OneBot 获取群历史失败: %s", exc)

    return []


async def get_recent_messages_prefer_onebot(
    *,
    chat_id: str,
    msg_type: str,
    start: int,
    end: int,
    onebot_client: Any | None,
    history_manager: Any | None,
    bot_qq: int,
    attachment_registry: Any | None = None,
    group_name_hint: str | None = None,
    max_onebot_count: int = 5000,
) -> list[dict[str, Any]]:
    """兼容旧名称，当前行为等同于本地优先。"""
    return await get_recent_messages_prefer_local(
        chat_id=chat_id,
        msg_type=msg_type,
        start=start,
        end=end,
        onebot_client=onebot_client,
        history_manager=history_manager,
        bot_qq=bot_qq,
        attachment_registry=attachment_registry,
        group_name_hint=group_name_hint,
        max_onebot_count=max_onebot_count,
    )
