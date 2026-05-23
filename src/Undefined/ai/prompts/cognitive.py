"""认知记忆检索查询构建辅助。"""

from __future__ import annotations

import html
import logging
from typing import Any

from Undefined.ai.prompts.constants import (
    COGNITIVE_CONTEXT_VALUE_MAX_LEN,
    COGNITIVE_QUERY_SHORT_THRESHOLD,
    CURRENT_MESSAGE_RE,
    XML_ATTR_RE,
)

logger = logging.getLogger(__name__)


def normalize_cognitive_context_value(value: Any) -> str:
    """压缩过长的上下文字段，避免污染检索 query。"""
    text = " ".join(str(value or "").split()).strip()
    if len(text) <= COGNITIVE_CONTEXT_VALUE_MAX_LEN:
        return text
    return text[: COGNITIVE_CONTEXT_VALUE_MAX_LEN - 3].rstrip() + "..."


def extract_current_message_signature(question: str) -> dict[str, str]:
    """从当前消息 XML 中提取 sender/time/content 签名。"""
    matched = CURRENT_MESSAGE_RE.search(str(question or ""))
    if not matched:
        return {}

    attrs_text = str(matched.group("attrs") or "")
    attrs: dict[str, str] = {}
    for attr_match in XML_ATTR_RE.finditer(attrs_text):
        key = str(attr_match.group("key") or "").strip()
        if not key:
            continue
        attrs[key] = html.unescape(str(attr_match.group("value") or "")).strip()

    content = html.unescape(str(matched.group("content") or "")).strip()
    return {
        "sender_id": attrs.get("sender_id", ""),
        "timestamp": attrs.get("time", ""),
        "content": content,
    }


def build_cognitive_query(
    question: str, extra_context: dict[str, Any] | None = None
) -> tuple[str, bool]:
    """构建认知记忆检索 query，短消息时追加少量会话语境。"""
    question_text = str(question or "").strip()
    signature = extract_current_message_signature(question_text)
    current_content = str(signature.get("content", "")).strip()
    base_query = current_content or question_text
    if not base_query:
        return "", False

    if not current_content or len(current_content) > COGNITIVE_QUERY_SHORT_THRESHOLD:
        return base_query, False

    # 短消息检索质量差，追加轻量会话语境提升向量召回
    context_parts: list[str] = []
    if extra_context:
        if bool(extra_context.get("is_private_chat", False)):
            context_parts.append("会话:私聊")
        elif str(extra_context.get("group_id", "")).strip():
            context_parts.append("会话:群聊")
        if bool(extra_context.get("is_at_bot", False)):
            context_parts.append("触发:@机器人")

        sender_name = normalize_cognitive_context_value(
            extra_context.get("sender_name", "")
        )
        if sender_name:
            context_parts.append(f"发送者:{sender_name}")

        group_name = normalize_cognitive_context_value(
            extra_context.get("group_name", "")
        )
        if group_name:
            context_parts.append(f"群:{group_name}")

    if not context_parts:
        return base_query, False
    return f"{base_query}\n语境: {'; '.join(context_parts)}", True


def drop_current_message_if_duplicated(
    recent_msgs: list[dict[str, Any]], question: str
) -> list[dict[str, Any]]:
    """若历史末尾与当前帧重复，则剔除最后一条避免双重注入。"""
    if not recent_msgs:
        return recent_msgs

    signature = extract_current_message_signature(question)
    if not signature:
        return recent_msgs

    last_msg = recent_msgs[-1]
    last_sender_id = str(last_msg.get("user_id", "")).strip()
    last_timestamp = str(last_msg.get("timestamp", "")).strip()
    last_content = str(last_msg.get("message", "")).strip()

    sig_sender_id = str(signature.get("sender_id", "")).strip()
    sig_timestamp = str(signature.get("timestamp", "")).strip()
    sig_content = str(signature.get("content", "")).strip()
    if not sig_sender_id or not sig_content:
        return recent_msgs

    if last_sender_id != sig_sender_id:
        return recent_msgs
    if last_content != sig_content:
        return recent_msgs

    if sig_timestamp and last_timestamp and sig_timestamp != last_timestamp:
        # 秒级时间戳不一致时，比较到分钟粒度，避免格式差异误杀
        if sig_timestamp[:16] != last_timestamp[:16]:
            return recent_msgs

    logger.info(
        "[Prompt] 历史注入剔除当前帧: sender=%s sig_time=%s history_time=%s content_preview=%s",
        sig_sender_id,
        sig_timestamp,
        last_timestamp,
        sig_content[:60],
    )
    return recent_msgs[:-1]


__all__ = [
    "build_cognitive_query",
    "drop_current_message_if_duplicated",
    "extract_current_message_signature",
    "normalize_cognitive_context_value",
]
