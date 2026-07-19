"""Minimal XML escaping helpers and message formatting."""

from __future__ import annotations

import html
import re
from typing import Any, Callable, Final, Mapping, Sequence

from xml.sax.saxutils import escape

from Undefined.utils.message_reply import ReplyContext


_INLINE_PRESERVED_TAG_RE = re.compile(
    r"<(?P<tag>attachment|forward)\s+uid=(?P<quote>[\"'])(?P<uid>[^\"']+)(?P=quote)\s*/?>",
    re.IGNORECASE,
)
_CDATA_SECTION_RE = re.compile(r"<!\[CDATA\[(.*?)\]\]>", re.DOTALL)
XML_CONTENT_BODY_PATTERN: Final[str] = r"(?:(?:<!\[CDATA\[.*?\]\]>)+|.*?)"


def wrap_xml_cdata(value: object) -> str:
    """Wrap literal text in one or more safe XML CDATA sections."""

    text = "" if value is None else str(value)
    return f"<![CDATA[{text.replace(']]>', ']]]]><![CDATA[>')}]]>"


def decode_xml_content_text(value: object) -> str:
    """Decode content emitted by this module from CDATA or XML entities."""

    text = "" if value is None else str(value)
    parts: list[str] = []
    position = 0
    for match in _CDATA_SECTION_RE.finditer(text):
        if match.start() != position:
            parts.clear()
            break
        parts.append(match.group(1))
        position = match.end()
    if parts and position == len(text):
        return "".join(parts)
    return html.unescape(text)


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


def _message_location(
    msg_type: str,
    chat_name: str,
    transport: Mapping[str, Any] | None = None,
) -> str:
    """Derive the human-readable location label from message type."""
    if msg_type == "group":
        return chat_name if chat_name.endswith("群") else f"{chat_name}群"
    if transport and str(transport.get("channel", "")).strip() == "wechat":
        return "微信私聊"
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
    transport_raw = msg.get("transport")
    transport = transport_raw if isinstance(transport_raw, Mapping) else None

    safe_sender = escape_xml_attr(sender_name)
    safe_sender_id = escape_xml_attr(sender_id)
    safe_chat_id = escape_xml_attr(chat_id)
    safe_chat_name = escape_xml_attr(chat_name)
    safe_role = escape_xml_attr(role)
    safe_title = escape_xml_attr(title)
    safe_time = escape_xml_attr(timestamp)
    use_cdata = bool(
        transport and str(transport.get("channel", "") or "").strip() == "wechat"
    )
    safe_text = (
        wrap_xml_cdata(text)
        if use_cdata
        else escape_xml_text_preserving_attachment_tags(text, attachments)
    )
    reply_xml = format_reply_context_xml(
        msg.get("reply_context"),
        use_cdata=use_cdata,
    )
    safe_location = escape_xml_attr(
        _message_location(msg_type_val, chat_name, transport)
    )

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
            f"<content>{safe_text}</content>{reply_xml}{attachment_xml}\n"
            f"</message>"
        )

    transport_attrs = ""
    if transport:
        channel = str(transport.get("channel", "") or "").strip()
        address = str(transport.get("address", "") or "").strip()
        if channel:
            transport_attrs += f' channel="{escape_xml_attr(channel)}"'
        if address:
            transport_attrs += f' address="{escape_xml_attr(address)}"'
    return (
        f'<message{msg_id_attr} sender="{safe_sender}" sender_id="{safe_sender_id}" '
        f'{transport_attrs.lstrip()} location="{safe_location}" time="{safe_time}">\n'
        f"<content>{safe_text}</content>{reply_xml}{attachment_xml}\n"
        f"</message>"
    )


def format_reply_context_xml(
    value: object,
    *,
    indent: str = " ",
    use_cdata: bool = False,
) -> str:
    """Format optional quoted-message metadata as read-only nested XML."""

    context = (
        value if isinstance(value, ReplyContext) else ReplyContext.from_mapping(value)
    )
    if context is None or context.is_empty:
        return ""
    attrs = ['readonly="true"']
    if context.title:
        attrs.append(f'title="{escape_xml_attr(context.title)}"')
    if context.message_id:
        attrs.append(f'message_id="{escape_xml_attr(context.message_id)}"')
    safe_text = (
        wrap_xml_cdata(context.text)
        if use_cdata
        else escape_xml_text_preserving_attachment_tags(
            context.text,
            context.attachments,
        )
    )
    attachment_xml = ""
    if context.attachments:
        from Undefined.attachments import attachment_refs_to_xml

        attachment_xml = (
            f"\n{attachment_refs_to_xml(context.attachments, indent=indent + ' ')}"
        )
    return (
        f"\n{indent}<reply_context {' '.join(attrs)}>\n"
        f"{indent} <content>{safe_text}</content>{attachment_xml}\n"
        f"{indent}</reply_context>"
    )


def format_messages_xml(messages: list[dict[str, Any]]) -> str:
    """Format a list of history records into ``\\n---\\n``-separated XML."""
    return "\n---\n".join(format_message_xml(msg) for msg in messages)
