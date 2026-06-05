"""认知记忆检索查询构建辅助。"""

from __future__ import annotations

import logging
from typing import Any

from Undefined.ai.prompts.constants import (
    COGNITIVE_CONTEXT_VALUE_MAX_LEN,
    COGNITIVE_QUERY_SHORT_THRESHOLD,
)
from Undefined.ai.prompts.current_input import (
    build_current_input_query_text,
    drop_current_input_batch_if_duplicated,
    extract_current_message_signature,
    extract_current_message_signatures,
)

logger = logging.getLogger(__name__)


def normalize_cognitive_context_value(value: Any) -> str:
    """压缩过长的上下文字段，避免污染检索 query。"""
    text = " ".join(str(value or "").split()).strip()
    if len(text) <= COGNITIVE_CONTEXT_VALUE_MAX_LEN:
        return text
    return text[: COGNITIVE_CONTEXT_VALUE_MAX_LEN - 3].rstrip() + "..."


def build_cognitive_query(
    question: str, extra_context: dict[str, Any] | None = None
) -> tuple[str, bool]:
    """构建认知记忆检索 query，短消息时追加少量会话语境。"""
    question_text = str(question or "").strip()
    base_query, from_current_messages = build_current_input_query_text(question_text)
    if not base_query:
        return "", False

    if not from_current_messages or len(base_query) > COGNITIVE_QUERY_SHORT_THRESHOLD:
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
    """若历史末尾与当前输入批次重复，则整批剔除避免双重注入。"""
    filtered, dropped = drop_current_input_batch_if_duplicated(recent_msgs, question)
    if dropped:
        logger.info(
            "[Prompt] 历史注入剔除当前输入批次重复消息: count=%s",
            dropped,
        )
    return filtered


__all__ = [
    "build_cognitive_query",
    "drop_current_message_if_duplicated",
    "extract_current_message_signature",
    "extract_current_message_signatures",
    "normalize_cognitive_context_value",
]
