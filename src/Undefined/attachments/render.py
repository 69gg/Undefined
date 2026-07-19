"""富媒体标签渲染与待发送文件派发。

将 ``<pic>`` / ``<attachment>`` 占位符转为 CQ 段或历史可读文本；
不修改注册表结构。
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from Undefined.attachments.models import (
    AttachmentRecord,
    AttachmentRenderError,
    RenderedRichMessage,
)
from Undefined.attachments.segments import _MEDIA_LABELS, is_http_url

if TYPE_CHECKING:
    from Undefined.attachments.registry import AttachmentRegistry

logger = logging.getLogger(__name__)

_PIC_TAG_PATTERN = re.compile(
    r"<pic\s+uid=(?P<quote>[\"'])(?P<uid>[^\"']+)(?P=quote)\s*/?>",
    re.IGNORECASE,
)
_ATTACHMENT_TAG_PATTERN = re.compile(
    r"<attachment\s+uid=(?P<quote>[\"'])(?P<uid>[^\"']+)(?P=quote)\s*/?>",
    re.IGNORECASE,
)
_UNIFIED_TAG_PATTERN = re.compile(
    r"<(?P<tag>pic|attachment)\s+uid=(?P<quote>[\"'])(?P<uid>[^\"']+)(?P=quote)\s*/?>",
    re.IGNORECASE,
)


def _escape_cq_component(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("[", "&#91;")
        .replace("]", "&#93;")
        .replace(",", "&#44;")
    )


async def render_message_with_attachments(
    message: str,
    *,
    registry: AttachmentRegistry | None,
    scope_key: str | None,
    strict: bool,
) -> RenderedRichMessage:
    """Render ``<pic>`` and ``<attachment>`` tags into delivery/history text.

    * ``<pic uid="pic_xxx"/>`` — backward-compatible, image-only.
    * ``<attachment uid="..."/>`` — unified tag for any media type.
      Images (``pic_*``) are inlined as CQ images; files (``file_*``)
      are collected into *pending_file_sends* for later dispatch.

    Args:
        message: 含占位标签的原始消息文本。
        registry: 附件注册表。
        scope_key: 当前会话作用域键。
        strict: 为 True 时 UID 不可用或类型不匹配则抛出 ``AttachmentRenderError``。

    Returns:
        投递文本、历史文本、附件引用及待发送文件列表。

    Raises:
        AttachmentRenderError: ``strict=True`` 且标签无法解析时。
    """
    has_tags = message and (
        "<pic" in message.lower() or "<attachment" in message.lower()
    )
    if not has_tags or registry is None or not scope_key:
        return RenderedRichMessage(
            delivery_text=message or "",
            history_text=message or "",
            attachments=[],
        )

    attachments: list[dict[str, str]] = []
    delivery_parts: list[str] = []
    history_parts: list[str] = []
    pending_files: list[AttachmentRecord] = []
    last_index = 0

    for match in _UNIFIED_TAG_PATTERN.finditer(message):
        tag_name = str(match.group("tag") or "").lower()
        uid = str(match.group("uid") or "").strip()
        delivery_parts.append(message[last_index : match.start()])
        history_parts.append(message[last_index : match.start()])
        last_index = match.end()

        record = await registry.resolve_async(uid, scope_key)
        if record is None:
            label = _MEDIA_LABELS.get(tag_name, "附件")
            replacement = f"[{label} uid={uid} 不可用]"
            if strict:
                raise AttachmentRenderError(f"附件 UID 不可用或不属于当前会话：{uid}")
            delivery_parts.append(replacement)
            history_parts.append(replacement)
            continue

        # <pic> tag: strictly image-only
        if tag_name == "pic" and record.media_type != "image":
            replacement = f"[图片 uid={uid} 类型错误]"
            if strict:
                raise AttachmentRenderError(f"UID 不是图片，不能用于 <pic>：{uid}")
            delivery_parts.append(replacement)
            history_parts.append(replacement)
            continue

        # <pic> 仅允许图片；<attachment> 按 media_type 分流
        if record.media_type == "image":
            ok = _render_image_tag(record, uid, strict, delivery_parts, history_parts)
        else:
            ok = _render_file_tag(
                record,
                uid,
                strict,
                delivery_parts,
                history_parts,
                pending_files,
            )

        if ok:
            attachments.append(record.prompt_ref())

    delivery_parts.append(message[last_index:])
    history_parts.append(message[last_index:])
    return RenderedRichMessage(
        delivery_text="".join(delivery_parts),
        history_text="".join(history_parts),
        attachments=attachments,
        pending_file_sends=tuple(pending_files),
    )


def _render_image_tag(
    record: AttachmentRecord,
    uid: str,
    strict: bool,
    delivery_parts: list[str],
    history_parts: list[str],
) -> bool:
    """Render an image attachment as an inline CQ:image. Returns True on success."""
    image_source = record.source_ref
    if record.local_path and Path(record.local_path).is_file():
        image_source = Path(record.local_path).resolve().as_uri()
    elif not image_source:
        replacement = f"[图片 uid={uid} 缺少文件]"
        if strict:
            raise AttachmentRenderError(f"图片 UID 缺少可发送的文件：{uid}")
        delivery_parts.append(replacement)
        history_parts.append(replacement)
        return False

    cq_args = [f"file={image_source}"]
    for key, value in dict(getattr(record, "segment_data", {}) or {}).items():
        cleaned_key = str(key or "").strip()
        cleaned_value = str(value or "").strip()
        if (
            not cleaned_key
            or not cleaned_value
            or cleaned_key in {"file", "original_source_ref"}
        ):
            continue
        cq_args.append(
            f"{_escape_cq_component(cleaned_key)}={_escape_cq_component(cleaned_value)}"
        )
    delivery_parts.append(f"[CQ:image,{','.join(cq_args)}]")
    if record.display_name:
        history_parts.append(f"[图片 uid={uid} name={record.display_name}]")
    else:
        history_parts.append(f"[图片 uid={uid}]")
    return True


def _render_file_tag(
    record: AttachmentRecord,
    uid: str,
    strict: bool,
    delivery_parts: list[str],
    history_parts: list[str],
    pending_files: list[AttachmentRecord],
) -> bool:
    """Render a non-image attachment as a pending file send. Returns True on success."""
    if not record.local_path or not Path(record.local_path).is_file():
        if is_http_url(record.source_ref):
            # 仅有远程 URL 时先入 pending，发送前尝试回源下载
            name_part = f" name={record.display_name}" if record.display_name else ""
            history_parts.append(f"[文件 uid={uid}{name_part}]")
            pending_files.append(record)
            return True
        replacement = f"[文件 uid={uid} 缺少本地文件]"
        if strict:
            raise AttachmentRenderError(f"文件 UID 缺少本地文件，无法发送：{uid}")
        delivery_parts.append(replacement)
        history_parts.append(replacement)
        return False

    # 文件不在 CQ 文本中内联，单独走 send_group/private_file
    # Keep a readable placeholder in history
    name_part = f" name={record.display_name}" if record.display_name else ""
    history_parts.append(f"[文件 uid={uid}{name_part}]")
    pending_files.append(record)
    return True


render_message_with_pic_placeholders = render_message_with_attachments


async def dispatch_pending_file_sends(
    rendered: RenderedRichMessage,
    *,
    sender: Any,
    target_type: str,
    target_id: int,
    registry: AttachmentRegistry | None = None,
    address: Any | None = None,
) -> None:
    """Send pending file attachments collected by *render_message_with_attachments*.

    This is best-effort: each file send failure is logged but does not interrupt
    the remaining sends or the caller.

    Args:
        rendered: ``render_message_with_attachments`` 的返回值。
        sender: 实现群/私聊文件发送的 OneBot 客户端。
        target_type: ``group`` 或 ``private``。
        target_id: 目标群号或 QQ 号。
        registry: 可选，用于发送前回源下载仅有 URL 的附件。
    """
    if not rendered.pending_file_sends or sender is None:
        return
    for record in rendered.pending_file_sends:
        send_record = record
        if (
            not send_record.local_path or not Path(send_record.local_path).is_file()
        ) and registry is not None:
            try:
                send_record = await registry.ensure_local_file(send_record)
            except Exception:
                logger.warning(
                    "[文件发送] 回源下载失败 uid=%s source=%s",
                    send_record.uid,
                    send_record.source_ref,
                    exc_info=True,
                )
        if not send_record.local_path or not Path(send_record.local_path).is_file():
            logger.warning(
                "[文件发送] 跳过：本地文件缺失 uid=%s path=%s",
                send_record.uid,
                send_record.local_path,
            )
            continue
        try:
            send_address_file = getattr(sender, "send_address_file", None)
            if address is not None and callable(send_address_file):
                await send_address_file(
                    address,
                    send_record.local_path,
                    name=send_record.display_name or None,
                    auto_history=False,
                )
            elif target_type == "group":
                await sender.send_group_file(
                    target_id,
                    send_record.local_path,
                    name=send_record.display_name or None,
                )
            elif target_type == "private":
                await sender.send_private_file(
                    target_id,
                    send_record.local_path,
                    name=send_record.display_name or None,
                )
            else:
                logger.warning(
                    "[文件发送] 跳过：不支持的 target_type=%s uid=%s",
                    target_type,
                    send_record.uid,
                )
                continue
        except Exception:
            logger.warning(
                "[文件发送] 发送失败（最佳努力） uid=%s target=%s:%s",
                send_record.uid,
                target_type,
                target_id,
                exc_info=True,
            )
