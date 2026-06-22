from __future__ import annotations

from datetime import datetime
import logging
from typing import Any, Mapping

from Undefined.attachments import build_attachment_scope, register_message_attachments
from Undefined.attachments.segments import (
    forward_ref_to_tag,
    normalize_message_segments,
)
from Undefined.utils.xml import (
    escape_xml_attr,
    escape_xml_text_preserving_attachment_tags,
)

logger = logging.getLogger(__name__)

_DEFAULT_LIMIT = 50
_MAX_LIMIT = 100


def _safe_int(value: Any, default: int, *, minimum: int = 0, maximum: int = 100) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def _format_time(raw_time: Any) -> str:
    if raw_time is None or raw_time == "":
        return "未知时间"
    try:
        timestamp = float(raw_time)
        if timestamp > 1_000_000_000_000:
            timestamp /= 1000.0
        if timestamp <= 0:
            return str(raw_time)
        return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError, OSError, OverflowError):
        return str(raw_time)


def _normalize_nodes(raw_nodes: Any) -> list[Mapping[str, Any]]:
    if isinstance(raw_nodes, list):
        return [node for node in raw_nodes if isinstance(node, Mapping)]
    if isinstance(raw_nodes, Mapping):
        messages = raw_nodes.get("messages")
        if isinstance(messages, list):
            return [node for node in messages if isinstance(node, Mapping)]
    return []


def _resolve_scope_key(context: Mapping[str, Any]) -> str | None:
    get_scope = context.get("get_scope_from_context")
    if callable(get_scope):
        try:
            resolved = get_scope(context)
            if resolved is None:
                return None
            return str(resolved)
        except Exception:
            logger.debug("从工具上下文推断 scope 失败", exc_info=True)
    return build_attachment_scope(
        group_id=context.get("group_id"),
        user_id=context.get("user_id"),
        request_type=str(context.get("request_type", "") or ""),
        webui_session=bool(context.get("webui_session", False)),
    )


def _raw_forward_id_from_record(uid_or_id: str, context: Mapping[str, Any]) -> str:
    if not uid_or_id.startswith("forward_"):
        return uid_or_id
    registry = context.get("attachment_registry")
    scope_key = _resolve_scope_key(context)
    if registry is None or not scope_key:
        return ""
    resolve = getattr(registry, "resolve", None)
    if not callable(resolve):
        return ""
    record = resolve(uid_or_id, scope_key)
    if record is None or getattr(record, "media_type", "") != "forward":
        return ""
    return str(getattr(record, "source_ref", "") or "").strip()


async def _register_node_segments(
    *,
    segments: list[Mapping[str, Any]],
    context: Mapping[str, Any],
) -> tuple[str, list[dict[str, str]]]:
    registry = context.get("attachment_registry")
    scope_key = _resolve_scope_key(context)
    onebot = context.get("onebot_client")
    resolve_image_url = (
        getattr(onebot, "get_image", None) if onebot is not None else None
    )
    if registry is None or not scope_key:
        text_parts: list[str] = []
        for segment in segments:
            type_ = str(segment.get("type", "") or "")
            raw_data = segment.get("data", {})
            data = raw_data if isinstance(raw_data, Mapping) else {}
            if type_ == "text":
                text_parts.append(str(data.get("text", "") or ""))
            elif type_ == "forward":
                forward_id = str(data.get("id") or data.get("resid") or "").strip()
                text_parts.append(
                    f"[合并转发: {forward_id}]" if forward_id else "[合并转发]"
                )
            elif type_ == "image":
                text_parts.append("[图片]")
            elif type_ == "file":
                text_parts.append("[文件]")
            elif type_ == "at":
                qq = str(data.get("qq", "") or "").strip()
                text_parts.append(f"[@{qq}]" if qq else "[@]")
            elif type_ == "face":
                text_parts.append("[表情]")
            elif type_ == "reply":
                text_parts.append("[引用]")
            elif type_:
                text_parts.append(f"[{type_}]")
        return "".join(text_parts).strip(), []

    result = await register_message_attachments(
        registry=registry,
        segments=segments,
        scope_key=scope_key,
        resolve_image_url=resolve_image_url,
        get_forward_messages=None,
        register_forward_refs=True,
        expand_forward_attachments=False,
    )
    refs = list(result.attachments) + list(result.forward_refs)
    return result.normalized_text, refs


async def execute(args: dict[str, Any], context: dict[str, Any]) -> str:
    message_id = str(args.get("message_id") or args.get("uid") or "").strip()
    if not message_id:
        return "错误：message_id 不能为空"

    get_forward_msg_callback = context.get("get_forward_msg_callback")
    if not callable(get_forward_msg_callback):
        return "错误：获取合并转发消息的回调未设置"

    raw_forward_id = _raw_forward_id_from_record(message_id, context)
    if not raw_forward_id:
        return f"错误：合并转发 UID 不可用或不属于当前会话：{message_id}"

    offset = _safe_int(args.get("offset"), 0, minimum=0, maximum=1_000_000)
    limit = _safe_int(args.get("limit"), _DEFAULT_LIMIT, minimum=1, maximum=_MAX_LIMIT)
    # 保留参数用于向后兼容和未来扩展；当前实现默认首层，不递归展开。
    _ = _safe_int(args.get("max_depth"), 1, minimum=1, maximum=5)

    try:
        nodes = _normalize_nodes(await get_forward_msg_callback(raw_forward_id))
    except Exception as exc:
        logger.exception("获取合并转发消息失败: id=%s", raw_forward_id)
        return f"获取合并转发消息失败：{exc}"

    if not nodes:
        return "未能获取到合并转发消息的内容或内容为空"

    window = nodes[offset : offset + limit]
    if not window:
        return (
            f"合并转发 {message_id} 共 {len(nodes)} 个节点，"
            f"offset={offset} 已超出范围。"
        )

    formatted_messages: list[str] = []
    for node in window:
        sender = node.get("sender")
        sender_data = sender if isinstance(sender, Mapping) else {}
        sender_name = (
            sender_data.get("nickname")
            or sender_data.get("card")
            or node.get("nickname")
            or node.get("card")
            or "未知用户"
        )
        sender_id = sender_data.get("user_id") or node.get("user_id") or "未知ID"
        timestamp = _format_time(node.get("time"))
        raw_content = (
            node.get("content") or node.get("message") or node.get("raw_message")
        )
        segments = normalize_message_segments(raw_content)
        text, refs = await _register_node_segments(
            segments=segments,
            context=context,
        )
        if not text:
            text = "(空消息)"
        safe_text = escape_xml_text_preserving_attachment_tags(text, refs)
        attachment_lines: list[str] = []
        forward_lines: list[str] = []
        for ref in refs:
            media_type = str(ref.get("media_type") or ref.get("kind") or "").strip()
            if media_type == "forward":
                tag = forward_ref_to_tag(ref)
                if tag:
                    forward_uid = str(ref.get("uid", "") or "").strip()
                    forward_lines.append(
                        f' <forward-ref uid="{escape_xml_attr(forward_uid)}">'
                        f"{tag}</forward-ref>"
                    )
                continue
            uid = str(ref.get("uid", "") or "").strip()
            if not uid:
                continue
            name = str(ref.get("display_name", "") or "").strip()
            name_attr = f' name="{escape_xml_attr(name)}"' if name else ""
            escaped_type = escape_xml_attr(media_type or "file")
            attachment_lines.append(
                f' <attachment uid="{escape_xml_attr(uid)}" '
                f'type="{escaped_type}"{name_attr} />'
            )
        extra = ""
        if attachment_lines or forward_lines:
            extra = "\n" + "\n".join(attachment_lines + forward_lines)
        formatted_messages.append(
            f'<message sender="{escape_xml_attr(sender_name)}" '
            f'sender_id="{escape_xml_attr(sender_id)}" location="合并转发" '
            f'time="{escape_xml_attr(timestamp)}">\n'
            f"<content>{safe_text}</content>{extra}\n"
            f"</message>"
        )

    next_offset = offset + len(window)
    page_note = (
        f"合并转发 {message_id}（源 ID: {raw_forward_id}）节点 "
        f"{offset + 1}-{next_offset}/{len(nodes)}"
    )
    if next_offset < len(nodes):
        page_note += (
            "\n继续读取：调用 "
            f'get_forward_msg(message_id="{message_id}", '
            f"offset={next_offset}, limit={limit})"
        )
    result = page_note + "\n" + "\n---\n".join(formatted_messages)
    logger.info(
        "get_forward_msg 完成: id=%s raw=%s offset=%s limit=%s total=%s",
        message_id,
        raw_forward_id,
        offset,
        limit,
        len(nodes),
    )
    return result
