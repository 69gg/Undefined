"""Minimal XML escaping helpers and message formatting."""

from __future__ import annotations

import html
import re
from typing import Any, Callable, Sequence, Mapping

from xml.sax.saxutils import escape


_INLINE_PRESERVED_TAG_RE = re.compile(
    r"<(?P<tag>attachment|forward)\s+uid=(?P<quote>[\"'])(?P<uid>[^\"']+)(?P=quote)\s*/?>",
    re.IGNORECASE,
)


def escape_xml_text(value: str) -> str:
    return escape(value, {'"': "&quot;", "'": "&apos;"})


def escape_xml_attr(value: object) -> str:
    text = "" if value is None else str(value)
    return escape(text, {'"': "&quot;", "'": "&apos;"})


def escape_xml_text_preserving_attachment_tags(
    value: str,
    attachments: Sequence[Mapping[str, str]] | None = None,
) -> str:
    """Escape XML text while preserving known inline resource tags."""
    allowed_attachment_uids = {
        str(item.get("uid", "") or "").strip()
        for item in (attachments or [])
        if isinstance(item, Mapping)
        and str(item.get("uid", "") or "").strip()
        and (str(item.get("media_type") or item.get("kind") or "").strip() != "forward")
    }
    allowed_forward_uids = {
        str(item.get("uid", "") or "").strip()
        for item in (attachments or [])
        if isinstance(item, Mapping)
        and str(item.get("uid", "") or "").strip()
        and (str(item.get("media_type") or item.get("kind") or "").strip() == "forward")
    }
    if not allowed_attachment_uids and not allowed_forward_uids:
        return escape_xml_text(value)

    text = str(value or "")
    parts: list[str] = []
    last_index = 0
    for match in _INLINE_PRESERVED_TAG_RE.finditer(text):
        tag = str(match.group("tag") or "").lower()
        uid = html.unescape(str(match.group("uid") or "").strip())
        if tag == "attachment" and uid not in allowed_attachment_uids:
            continue
        if tag == "forward" and uid not in allowed_forward_uids:
            continue
        parts.append(escape_xml_text(text[last_index : match.start()]))
        parts.append(f'<{tag} uid="{escape_xml_attr(uid)}"/>')
        last_index = match.end()
    parts.append(escape_xml_text(text[last_index:]))
    return "".join(parts)


def _message_location(msg_type: str, chat_name: str) -> str:
    """Derive the human-readable location label from message type."""
    if msg_type == "group":
        return chat_name if chat_name.endswith("群") else f"{chat_name}群"
    return "私聊"


def format_message_xml(
    msg: dict[str, Any],
    *,
    attachment_formatter: (Callable[[Sequence[Mapping[str, str]]], str] | None) = None,
) -> str:
    """Format a single history record dict into main-AI-compatible XML.

    ``attachment_formatter`` is an optional callable that turns the attachments
    list into an XML fragment.  When *None* (the default) a lazy import of
    :func:`Undefined.attachments.attachment_refs_to_xml` is used so that
    lightweight callers do not pay the import cost.
    """
    msg_type_val = str(msg.get("type", "group") or "group")
    sender_name = str(msg.get("display_name", "未知用户") or "未知用户")
    sender_id = str(msg.get("user_id", "") or "")
    chat_id = str(msg.get("chat_id", "") or "")
    chat_name = str(msg.get("chat_name", "未知群聊") or "未知群聊")
    timestamp = str(msg.get("timestamp", "") or "")
    text = str(msg.get("message", "") or "")
    message_id = msg.get("message_id")
    role = str(msg.get("role", "member") or "member")
    title = str(msg.get("title", "") or "")
    level = str(msg.get("level", "") or "")
    attachments = msg.get("attachments", [])

    safe_sender = escape_xml_attr(sender_name)
    safe_sender_id = escape_xml_attr(sender_id)
    safe_chat_id = escape_xml_attr(chat_id)
    safe_chat_name = escape_xml_attr(chat_name)
    safe_role = escape_xml_attr(role)
    safe_title = escape_xml_attr(title)
    safe_time = escape_xml_attr(timestamp)
    safe_text = escape_xml_text_preserving_attachment_tags(text, attachments)
    safe_location = escape_xml_attr(_message_location(msg_type_val, chat_name))

    msg_id_attr = ""
    if message_id is not None:
        msg_id_attr = f' message_id="{escape_xml_attr(str(message_id))}"'

    attachment_xml = ""
    if isinstance(attachments, list) and attachments:
        if attachment_formatter is None:
            from Undefined.attachments import attachment_refs_to_xml

            attachment_formatter = attachment_refs_to_xml
        attachment_xml = f"\n{attachment_formatter(attachments)}"

    if msg_type_val == "group":
        level_attr = f' level="{escape_xml_attr(level)}"' if level else ""
        return (
            f'<message{msg_id_attr} sender="{safe_sender}" sender_id="{safe_sender_id}" '
            f'group_id="{safe_chat_id}" group_name="{safe_chat_name}" location="{safe_location}" '
            f'role="{safe_role}" title="{safe_title}"{level_attr} time="{safe_time}">\n'
            f"<content>{safe_text}</content>{attachment_xml}\n"
            f"</message>"
        )

    return (
        f'<message{msg_id_attr} sender="{safe_sender}" sender_id="{safe_sender_id}" '
        f'location="{safe_location}" time="{safe_time}">\n'
        f"<content>{safe_text}</content>{attachment_xml}\n"
        f"</message>"
    )


def format_messages_xml(messages: list[dict[str, Any]]) -> str:
    """Format a list of history records into ``\\n---\\n``-separated XML."""
    return "\n---\n".join(format_message_xml(msg) for msg in messages)
