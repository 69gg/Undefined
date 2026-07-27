"""Helpers for parsing the current input batch from prompt XML."""

from __future__ import annotations

import html
from dataclasses import dataclass
from typing import Any

from Undefined.ai.prompts.constants import CURRENT_MESSAGE_RE, XML_ATTR_RE
from Undefined.utils.xml import decode_xml_content_text


@dataclass(frozen=True)
class CurrentMessageSignature:
    """Stable identity for one current ``<message>`` block."""

    sender_id: str
    timestamp: str
    content: str
    message_id: str = ""


def _parse_attrs(attrs_text: str) -> dict[str, str]:
    attrs: dict[str, str] = {}
    for attr_match in XML_ATTR_RE.finditer(attrs_text):
        key = str(attr_match.group("key") or "").strip()
        if not key:
            continue
        attrs[key] = html.unescape(str(attr_match.group("value") or "")).strip()
    return attrs


def extract_current_message_signatures(
    question: str,
) -> list[CurrentMessageSignature]:
    """Extract all current ``<message>`` signatures from prompt text."""
    signatures: list[CurrentMessageSignature] = []
    for matched in CURRENT_MESSAGE_RE.finditer(str(question or "")):
        attrs = _parse_attrs(str(matched.group("attrs") or ""))
        content = decode_xml_content_text(matched.group("content")).strip()
        signatures.append(
            CurrentMessageSignature(
                sender_id=attrs.get("sender_id", ""),
                timestamp=attrs.get("time", ""),
                content=content,
                message_id=attrs.get("message_id", ""),
            )
        )
    return signatures


def extract_current_message_signature(question: str) -> dict[str, str]:
    """Compatibility helper returning the first current message signature."""
    signatures = extract_current_message_signatures(question)
    if not signatures:
        return {}
    first = signatures[0]
    return {
        "sender_id": first.sender_id,
        "timestamp": first.timestamp,
        "content": first.content,
        "message_id": first.message_id,
    }


def build_current_input_query_text(question: str) -> tuple[str, bool]:
    """Return query text from the full current input batch.

    The boolean indicates whether the query came from explicit ``<message>``
    content instead of falling back to the raw question text.
    """
    signatures = extract_current_message_signatures(question)
    contents = [sig.content for sig in signatures if sig.content]
    if contents:
        return "\n".join(contents), True
    return str(question or "").strip(), False


def build_current_input_per_message_query_texts(
    question: str,
) -> tuple[list[str], bool]:
    """Return one query text per current ``<message>`` block."""
    signatures = extract_current_message_signatures(question)
    contents = [sig.content for sig in signatures if sig.content]
    if contents:
        return contents, True
    fallback = str(question or "").strip()
    return ([fallback] if fallback else []), False


def _history_msg_matches_signature(
    msg: dict[str, Any], signature: CurrentMessageSignature
) -> bool:
    history_message_id = str(msg.get("message_id", "") or "").strip()
    if signature.message_id and history_message_id:
        return history_message_id == signature.message_id

    sig_sender_id = signature.sender_id.strip()
    sig_content = signature.content.strip()
    if not sig_sender_id or not sig_content:
        return False

    last_sender_id = str(msg.get("user_id", "") or "").strip()
    last_content = str(msg.get("message", "") or "").strip()
    if last_sender_id != sig_sender_id or last_content != sig_content:
        return False

    sig_timestamp = signature.timestamp.strip()
    last_timestamp = str(msg.get("timestamp", "") or "").strip()
    if sig_timestamp and last_timestamp and sig_timestamp != last_timestamp:
        # 秒级时间戳不一致时，比较到分钟粒度，避免格式差异误杀。
        return sig_timestamp[:16] == last_timestamp[:16]
    return True


def drop_current_input_batch_if_duplicated(
    recent_msgs: list[dict[str, Any]], question: str
) -> tuple[list[dict[str, Any]], int]:
    """从历史中剔除当前输入批次；稳定 ID 可跨越交错消息精确匹配。"""
    signatures = extract_current_message_signatures(question)
    if not recent_msgs or not signatures:
        return recent_msgs, 0

    expected_ids: dict[str, int] = {}
    for signature in signatures:
        message_id = signature.message_id.strip()
        if message_id:
            expected_ids[message_id] = expected_ids.get(message_id, 0) + 1

    matched_ids: dict[str, int] = {}
    remaining: list[dict[str, Any]] = []
    dropped = 0
    for message in recent_msgs:
        message_id = str(message.get("message_id", "") or "").strip()
        matched_count = matched_ids.get(message_id, 0)
        if message_id and matched_count < expected_ids.get(message_id, 0):
            matched_ids[message_id] = matched_count + 1
            dropped += 1
            continue
        remaining.append(message)

    unmatched_signatures: list[CurrentMessageSignature] = []
    remaining_matched_ids = dict(matched_ids)
    for signature in signatures:
        message_id = signature.message_id.strip()
        if message_id and remaining_matched_ids.get(message_id, 0) > 0:
            remaining_matched_ids[message_id] -= 1
            continue
        unmatched_signatures.append(signature)
    cursor = len(unmatched_signatures) - 1
    while remaining and cursor >= 0:
        if not _history_msg_matches_signature(
            remaining[-1],
            unmatched_signatures[cursor],
        ):
            break
        remaining.pop()
        dropped += 1
        cursor -= 1
    return remaining, dropped


__all__ = [
    "CurrentMessageSignature",
    "build_current_input_per_message_query_texts",
    "build_current_input_query_text",
    "drop_current_input_batch_if_duplicated",
    "extract_current_message_signature",
    "extract_current_message_signatures",
]
