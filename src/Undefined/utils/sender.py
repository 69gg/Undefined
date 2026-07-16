"""消息发送管理"""

import logging
from pathlib import Path
import time
from typing import Any, Literal
from urllib.parse import unquote, urlsplit

from weixin_ilink_client import (
    ApiError,
    HttpError,
    RefMessage,
    SessionPausedError,
    UnsupportedCapabilityError,
)
from weixin_ilink_client.constants import STALE_TOKEN_ERROR_CODE

from Undefined.attachments import attachment_refs_to_text, build_attachment_scope
from Undefined.config import Config
from Undefined.onebot import OneBotClient
from Undefined.utils.history import MessageHistoryManager
from Undefined.utils.common import (
    message_to_segments,
    extract_text,
    process_at_mentions,
)
from Undefined.utils.logging import redact_string
from Undefined.utils.message_targets import DeliveryAddress
from Undefined.utils.message_reply import (
    ReplyContext,
    build_safe_reply_preview,
    format_markdown_reply,
)
from Undefined.utils.message_turn import mark_message_sent_this_turn

logger = logging.getLogger(__name__)

# OneBot 与微信 iLink 的单条文本长度限制（保守值）
MAX_MESSAGE_LENGTH = 4000
_WEIXIN_MEDIA_SEGMENT_TYPES: frozenset[str] = frozenset(
    {"image", "video", "file", "record"}
)


class WeixinReplyTargetError(ValueError):
    """Raised when a quoted target is outside the current WeChat route."""


def _extract_message_id(result: object) -> int | None:
    if not isinstance(result, dict):
        return None

    message_id = result.get("message_id")
    if message_id is None:
        data = result.get("data")
        if isinstance(data, dict):
            message_id = data.get("message_id")

    try:
        return int(message_id) if message_id is not None else None
    except (TypeError, ValueError):
        return None


def _coerce_qq_reply_id(value: int | str | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("QQ 引用消息 ID 必须是正整数")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("QQ 引用消息 ID 必须是正整数") from exc
    if parsed <= 0:
        raise ValueError("QQ 引用消息 ID 必须是正整数")
    return parsed


def _should_fallback_weixin_reference(exc: BaseException) -> bool:
    if isinstance(exc, SessionPausedError):
        return False
    if isinstance(exc, UnsupportedCapabilityError):
        return True
    if isinstance(exc, ApiError):
        return exc.code != STALE_TOKEN_ERROR_CODE
    if isinstance(exc, HttpError):
        return 400 <= exc.status_code < 500 and exc.status_code not in {
            408,
            425,
            429,
        }
    return False


def _format_size(size_bytes: int | None) -> str:
    if size_bytes is None or size_bytes < 0:
        return "未知大小"
    if size_bytes < 1024:
        return f"{size_bytes}B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f}KB"
    if size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / 1024 / 1024:.2f}MB"
    return f"{size_bytes / 1024 / 1024 / 1024:.2f}GB"


def _build_file_history_message(file_name: str, size_bytes: int | None) -> str:
    return f"[文件] {file_name} ({_format_size(size_bytes)})"


def _append_attachment_refs(
    history_content: str,
    attachments: list[dict[str, str]] | None,
) -> str:
    refs_text = attachment_refs_to_text(attachments or [])
    if not refs_text or refs_text in history_content:
        return history_content
    if not history_content:
        return refs_text
    return f"{history_content}\n{refs_text}"


def _merge_attachment_refs(
    *groups: list[dict[str, str]] | None,
) -> list[dict[str, str]]:
    merged: list[dict[str, str]] = []
    seen_uids: set[str] = set()
    for group in groups:
        for item in group or []:
            uid = str(item.get("uid", "") or "").strip()
            if uid and uid in seen_uids:
                continue
            if uid:
                seen_uids.add(uid)
            merged.append(item)
    return merged


def _iter_segments_deep(value: object) -> list[dict[str, Any]]:
    """递归收集消息段，用于合并转发中的本地媒体登记。"""
    segments: list[dict[str, Any]] = []
    if isinstance(value, dict):
        type_value = value.get("type")
        data = value.get("data")
        if type_value is not None and isinstance(data, dict):
            segments.append(value)
            content = data.get("content")
            if isinstance(content, (list, dict)):
                segments.extend(_iter_segments_deep(content))
        else:
            for child in value.values():
                if isinstance(child, (list, dict)):
                    segments.extend(_iter_segments_deep(child))
    elif isinstance(value, list):
        for child in value:
            if isinstance(child, (list, dict)):
                segments.extend(_iter_segments_deep(child))
    return segments


def _local_path_from_segment_source(source: Any) -> Path | None:
    raw_source = str(source or "").strip()
    if not raw_source:
        return None
    lowered = raw_source.lower()
    if lowered.startswith(("http://", "https://", "base64://")):
        return None
    if lowered.startswith("file://"):
        parsed = urlsplit(raw_source)
        path = Path(unquote(parsed.path)).expanduser()
    else:
        path = Path(raw_source).expanduser()
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    else:
        path = path.resolve()
    return path if path.is_file() else None


def _get_file_size(file_path: str) -> int | None:
    try:
        return Path(file_path).stat().st_size
    except OSError:
        return None


def _split_text_chunks(text: str, limit: int = MAX_MESSAGE_LENGTH) -> list[str]:
    """按长度分片，优先在换行后切分并保留原始文本。"""
    if not text:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + limit, len(text))
        if end < len(text):
            newline = text.rfind("\n", start, end)
            if newline >= start:
                end = newline + 1
        chunks.append(text[start:end])
        start = end
    return chunks


def _prepare_weixin_delivery_units(
    segments: list[dict[str, Any]],
    bot_qq: int,
) -> tuple[list[tuple[str, str | Path]], str]:
    """Validate all media and preserve the original text/media segment order."""

    units: list[tuple[str, str | Path]] = []
    pending_text: list[dict[str, Any]] = []
    all_text: list[dict[str, Any]] = []

    def flush_text() -> None:
        if not pending_text:
            return
        text = extract_text(pending_text, bot_qq)
        pending_text.clear()
        if text:
            units.append(("text", text))

    for segment in segments:
        segment_type = str(segment.get("type", "") or "").strip().lower()
        if segment_type not in _WEIXIN_MEDIA_SEGMENT_TYPES:
            pending_text.append(segment)
            all_text.append(segment)
            continue
        if segment_type == "record":
            raise ValueError("微信 iLink 暂不支持发送语音")
        data = segment.get("data")
        if not isinstance(data, dict):
            raise ValueError("微信媒体消息缺少有效参数")
        path = _local_path_from_segment_source(data.get("file"))
        if path is None:
            raise ValueError("微信 iLink 当前只支持发送本地媒体文件")
        flush_text()
        units.append((segment_type, path))
    flush_text()
    return units, extract_text(all_text, bot_qq)


class MessageSender:
    """消息发送器"""

    def __init__(
        self,
        onebot: OneBotClient,
        history_manager: MessageHistoryManager,
        bot_qq: int,
        config: Config,
        attachment_registry: Any | None = None,
    ):
        self.onebot = onebot
        self.history_manager = history_manager
        self.bot_qq = bot_qq
        self.config = config
        self.attachment_registry = attachment_registry
        self._weixin_service: Any | None = None

    def set_weixin_service(self, service: Any | None) -> None:
        """注入可选的微信投递服务。"""
        self._weixin_service = service

    async def send_address_message(
        self,
        address: DeliveryAddress,
        message: str,
        auto_history: bool = True,
        *,
        mark_sent: bool = True,
        reply_to: int | str | None = None,
        preferred_temp_group_id: int | None = None,
        history_message: str | None = None,
        attachments: list[dict[str, str]] | None = None,
    ) -> int | str | None:
        """按规范地址投递消息，并保留原 QQ 方法的兼容语义。"""
        if address.channel == "group":
            return await self.send_group_message(
                address.target_id,
                message,
                auto_history=auto_history,
                mark_sent=mark_sent,
                reply_to=_coerce_qq_reply_id(reply_to),
                history_message=history_message,
                attachments=attachments,
            )
        if address.channel == "qq":
            return await self.send_private_message(
                address.target_id,
                message,
                auto_history=auto_history,
                mark_sent=mark_sent,
                reply_to=_coerce_qq_reply_id(reply_to),
                preferred_temp_group_id=preferred_temp_group_id,
                history_message=history_message,
                attachments=attachments,
            )
        return await self._send_weixin_message(
            address.target_id,
            message,
            auto_history=auto_history,
            mark_sent=mark_sent,
            reply_to=reply_to,
            history_message=history_message,
            attachments=attachments,
        )

    async def send_address_file(
        self,
        address: DeliveryAddress,
        file_path: str,
        name: str | None = None,
        *,
        kind: str | None = None,
        auto_history: bool = True,
    ) -> None:
        """按规范地址发送一个本地文件。"""
        if address.channel == "group":
            await self.send_group_file(
                address.target_id, file_path, name=name, auto_history=auto_history
            )
            return
        if address.channel == "qq":
            await self.send_private_file(
                address.target_id, file_path, name=name, auto_history=auto_history
            )
            return
        if not self.config.is_private_allowed(address.target_id):
            enabled = self.config.access_control_enabled()
            reason = (
                self.config.private_access_denied_reason(address.target_id) or "unknown"
            )
            logger.warning(
                "[访问控制] 已拦截微信文件发送: user=%s reason=%s (access enabled=%s)",
                address.target_id,
                reason,
                enabled,
            )
            raise PermissionError(
                "blocked by access control: "
                f"type=private reason={reason} user_id={address.target_id} "
                f"enabled={enabled}"
            )
        service = self._require_weixin_service()
        sent_message_id = await service.send_file(
            address.target_id,
            file_path,
            name=name,
            kind=kind,
        )
        sent_at_ms = time.time_ns() // 1_000_000
        if not auto_history:
            return
        file_name = name or Path(file_path).name
        file_size = _get_file_size(file_path)
        history_attachments = await self.register_sent_file_attachment(
            "private",
            address.target_id,
            file_path,
            file_name,
            kind=kind or "file",
        )
        history_content = _append_attachment_refs(
            _build_file_history_message(file_name, file_size),
            history_attachments,
        )
        await self.history_manager.add_private_message(
            user_id=address.target_id,
            text_content=history_content,
            display_name="Bot",
            user_name="Bot",
            attachments=history_attachments,
            message_id=sent_message_id,
            transport={
                "channel": "wechat",
                "address": address.canonical,
                "direction": "outbound",
                "message_ids": [sent_message_id],
                "sent_at_ms": sent_at_ms,
            },
        )

    async def set_address_typing(self, address: DeliveryAddress, typing: bool) -> None:
        """仅微信支持的输入状态提示；其他通道无操作。"""
        if address.channel != "wechat":
            return
        service = self._require_weixin_service()
        await service.set_typing(address.target_id, typing)

    def _require_weixin_service(self) -> Any:
        if self._weixin_service is None:
            raise RuntimeError("微信消息服务未启用")
        return self._weixin_service

    async def _send_weixin_message(
        self,
        user_id: int,
        message: str,
        *,
        auto_history: bool,
        mark_sent: bool,
        reply_to: int | str | None,
        history_message: str | None,
        attachments: list[dict[str, str]] | None,
    ) -> str | None:
        if not self.config.is_private_allowed(user_id):
            enabled = self.config.access_control_enabled()
            reason = self.config.private_access_denied_reason(user_id) or "unknown"
            logger.warning(
                "[访问控制] 已拦截微信消息发送: user=%s reason=%s (access enabled=%s)",
                user_id,
                reason,
                enabled,
            )
            raise PermissionError(
                "blocked by access control: "
                f"type=private reason={reason} user_id={user_id} enabled={enabled}"
            )
        service = self._require_weixin_service()
        reply_context: ReplyContext | None = None
        reference: RefMessage | None = None
        if reply_to is not None:
            reply_context = await self._resolve_weixin_reply_context(
                user_id,
                reply_to,
            )
            preview = build_safe_reply_preview(
                reply_context.text,
                reply_context.attachments,
            )
            reference = RefMessage.from_text(reply_context.title, preview)
        segments = message_to_segments(message)
        delivery_units, text = _prepare_weixin_delivery_units(segments, self.bot_qq)

        sent_ids: list[str] = []
        sent_any = False
        first_sent_at_ms: int | None = None

        def record_sent(receipt: object) -> None:
            nonlocal first_sent_at_ms, sent_any
            sent_any = True
            if first_sent_at_ms is None:
                first_sent_at_ms = time.time_ns() // 1_000_000
            receipt_id = str(receipt or "").strip()
            if receipt_id:
                sent_ids.append(receipt_id)
            if mark_sent:
                mark_message_sent_this_turn()

        reply_mode = ""
        reference_pending = reference is not None
        for unit_type, payload in delivery_units:
            if unit_type == "text":
                assert isinstance(payload, str)
                text_chunks = _split_text_chunks(payload)
                if reference_pending:
                    assert reference is not None
                    try:
                        receipt = await service.send_text(
                            user_id,
                            text_chunks[0],
                            reference=reference,
                        )
                    except Exception as exc:
                        if not _should_fallback_weixin_reference(exc):
                            raise
                        logger.warning(
                            "[微信引用] 原生引用被明确拒绝，降级为 Markdown: "
                            "user=%s target=%s error=%s",
                            user_id,
                            reply_to,
                            type(exc).__name__,
                        )
                        assert reply_context is not None
                        fallback_text = format_markdown_reply(reply_context, payload)
                        for chunk in _split_text_chunks(fallback_text):
                            record_sent(await service.send_text(user_id, chunk))
                        reply_mode = "markdown_fallback"
                    else:
                        record_sent(receipt)
                        for chunk in text_chunks[1:]:
                            record_sent(await service.send_text(user_id, chunk))
                        reply_mode = "native"
                    reference_pending = False
                else:
                    for chunk in text_chunks:
                        record_sent(await service.send_text(user_id, chunk))
                continue

            assert isinstance(payload, Path)
            kind = "image" if unit_type == "image" else unit_type
            if reference_pending:
                assert reference is not None
                try:
                    receipt = await service.send_file(
                        user_id,
                        payload,
                        name=payload.name,
                        kind=kind,
                        reference=reference,
                    )
                except Exception as exc:
                    if not _should_fallback_weixin_reference(exc):
                        raise
                    logger.warning(
                        "[微信引用] 原生媒体引用被明确拒绝，降级为 Markdown: "
                        "user=%s target=%s error=%s",
                        user_id,
                        reply_to,
                        type(exc).__name__,
                    )
                    assert reply_context is not None
                    fallback_text = format_markdown_reply(reply_context, "")
                    for chunk in _split_text_chunks(fallback_text):
                        record_sent(await service.send_text(user_id, chunk))
                    record_sent(
                        await service.send_file(
                            user_id,
                            payload,
                            name=payload.name,
                            kind=kind,
                        )
                    )
                    reply_mode = "markdown_fallback"
                else:
                    record_sent(receipt)
                    reply_mode = "native"
                reference_pending = False
            else:
                record_sent(
                    await service.send_file(
                        user_id,
                        payload,
                        name=payload.name,
                        kind=kind,
                    )
                )
        if not sent_any and message.strip():
            raise ValueError("微信消息中没有可投递的文本或本地媒体")

        if auto_history:
            history_attachments = _merge_attachment_refs(
                attachments,
                await self._register_local_segment_attachments(
                    "private",
                    user_id,
                    segments,
                ),
            )
            history_content = history_message
            if history_content is None:
                history_content = text
            history_content = _append_attachment_refs(
                history_content,
                history_attachments,
            )
            transport: dict[str, Any] = {
                "channel": "wechat",
                "address": f"wechat:{user_id}",
                "direction": "outbound",
            }
            if first_sent_at_ms is not None:
                transport["sent_at_ms"] = first_sent_at_ms
            if sent_ids:
                transport["message_ids"] = list(sent_ids)
            if reply_to is not None:
                transport["reply_to"] = str(reply_to)
                transport["reply_mode"] = reply_mode
            await self.history_manager.add_private_message(
                user_id=user_id,
                text_content=history_content,
                display_name="Bot",
                user_name="Bot",
                message_id=(sent_ids[0] if sent_ids else None),
                attachments=history_attachments,
                transport=transport,
                reply_context=reply_context,
            )
        return sent_ids[0] if sent_ids else None

    async def _resolve_weixin_reply_context(
        self,
        user_id: int,
        reply_to: int | str,
    ) -> ReplyContext:
        address = f"wechat:{user_id}"
        record = await self.history_manager.find_private_message_by_id(
            user_id,
            reply_to,
            channel="wechat",
            address=address,
        )
        if record is None:
            raise WeixinReplyTargetError(
                f"微信引用目标 {reply_to} 不在当前微信会话历史中"
            )
        raw_attachments = record.get("attachments")
        attachments: list[dict[str, str]] = []
        if isinstance(raw_attachments, list):
            for item in raw_attachments:
                if not isinstance(item, dict):
                    continue
                uid = str(item.get("uid", "") or "").strip()
                if not uid:
                    continue
                attachments.append(
                    {str(key): str(value) for key, value in item.items()}
                )
        return ReplyContext(
            title=str(record.get("display_name", "") or "消息").strip() or "消息",
            message_id=str(reply_to),
            text=str(record.get("message", "") or ""),
            attachments=tuple(attachments),
        )

    async def register_sent_file_attachment(
        self,
        target_type: Literal["group", "private"],
        target_id: int,
        file_path: str,
        name: str | None = None,
        *,
        kind: str = "file",
        source_kind: str = "sent_file",
        source_ref: str = "",
    ) -> list[dict[str, str]]:
        """将发送出的本地文件登记为当前会话可见的统一附件 UID。"""
        registry = self.attachment_registry
        if registry is None:
            return []

        scope_key = build_attachment_scope(
            group_id=target_id if target_type == "group" else None,
            user_id=target_id if target_type == "private" else None,
            request_type=target_type,
        )
        if scope_key is None:
            return []

        file_name = name or Path(file_path).name
        try:
            record = await registry.register_local_file(
                scope_key,
                file_path,
                kind=kind,
                display_name=file_name,
                source_kind=source_kind,
                source_ref=source_ref or str(Path(file_path).resolve()),
            )
            return [record.prompt_ref()]
        except Exception:
            logger.exception(
                "[附件登记] 发送文件登记失败: target=%s:%s file=%s",
                target_type,
                target_id,
                file_name,
            )
            return []

    async def _register_local_segment_attachments(
        self,
        target_type: Literal["group", "private"],
        target_id: int,
        segments: list[dict[str, Any]],
    ) -> list[dict[str, str]]:
        kind_by_segment_type = {
            "image": "image",
            "video": "video",
            "record": "record",
        }
        attachments: list[dict[str, str]] = []
        seen_paths: set[str] = set()
        for segment in segments:
            segment_type = str(segment.get("type", "") or "").strip().lower()
            kind = kind_by_segment_type.get(segment_type)
            if kind is None:
                continue
            data = segment.get("data")
            if not isinstance(data, dict):
                continue
            path = _local_path_from_segment_source(data.get("file"))
            if path is None:
                continue
            path_text = str(path)
            if path_text in seen_paths:
                continue
            seen_paths.add(path_text)
            attachments.extend(
                await self.register_sent_file_attachment(
                    target_type,
                    target_id,
                    path_text,
                    path.name,
                    kind=kind,
                    source_kind=f"sent_{segment_type}",
                    source_ref=str(data.get("file", "") or path_text),
                )
            )
        return attachments

    async def send_group_message(
        self,
        group_id: int,
        message: str,
        auto_history: bool = True,
        history_prefix: str = "",
        *,
        mark_sent: bool = True,
        reply_to: int | None = None,
        history_message: str | None = None,
        attachments: list[dict[str, str]] | None = None,
    ) -> int | None:
        """发送群消息"""
        if not self.config.is_group_allowed(group_id):
            enabled = self.config.access_control_enabled()
            reason = self.config.group_access_denied_reason(group_id) or "unknown"
            logger.warning(
                "[访问控制] 已拦截群消息发送: group=%s reason=%s (access enabled=%s)",
                group_id,
                reason,
                enabled,
            )
            raise PermissionError(
                "blocked by access control: "
                f"type=group reason={reason} group_id={int(group_id)} enabled={enabled}"
            )

        safe_message = redact_string(message)
        logger.info(f"[发送消息] 目标群:{group_id} | 内容摘要:{safe_message[:100]}...")

        # 将 [@{qq_id}] 格式转换为 [CQ:at,qq={qq_id}]
        message = process_at_mentions(message)

        segments = message_to_segments(message)

        # 准备历史记录文本（不含 reply 段）
        history_content: str | None = None
        if auto_history:
            if history_message is not None:
                history_content = history_message
            else:
                history_content = extract_text(segments, self.bot_qq)
            if history_prefix:
                history_content = f"{history_prefix}{history_content}"

        # 发送消息
        bot_message_id: int | None = None
        if len(message) <= MAX_MESSAGE_LENGTH:
            send_segments = list(segments)
            if reply_to is not None:
                send_segments.insert(
                    0, {"type": "reply", "data": {"id": str(reply_to)}}
                )
            result = await self.onebot.send_group_message(
                group_id, send_segments, mark_sent=mark_sent
            )
            bot_message_id = _extract_message_id(result)
        else:
            bot_message_id = await self._send_chunked_group(
                group_id, message, mark_sent=mark_sent, reply_to=reply_to
            )

        # 发送成功后写入历史记录
        if auto_history and history_content is not None:
            history_attachments = _merge_attachment_refs(
                attachments,
                await self._register_local_segment_attachments(
                    "group",
                    group_id,
                    segments,
                ),
            )
            history_content = _append_attachment_refs(
                history_content,
                history_attachments,
            )
            logger.debug(f"[历史记录] 正在保存 Bot 群聊回复: group={group_id}")
            await self.history_manager.add_group_message(
                group_id=group_id,
                sender_id=self.bot_qq,
                text_content=history_content,
                sender_nickname="Bot",
                group_name="",
                message_id=bot_message_id,
                attachments=history_attachments,
            )
        return bot_message_id

    async def _send_chunked_group(
        self,
        group_id: int,
        message: str,
        *,
        mark_sent: bool = True,
        reply_to: int | None = None,
    ) -> int | None:
        """分段发送群消息，返回第一段的 message_id。"""
        logger.info(f"[消息分段] 消息过长 ({len(message)} 字符)，正在自动分段发送...")
        lines = message.split("\n")
        current_chunk: list[str] = []
        current_length = 0
        chunk_count = 0
        first_message_id: int | None = None

        for line in lines:
            line_length = len(line) + 1

            if current_length + line_length > MAX_MESSAGE_LENGTH and current_chunk:
                chunk_count += 1
                chunk_text = "\n".join(current_chunk)
                logger.debug(f"[消息分段] 发送第 {chunk_count} 段")
                segments = message_to_segments(chunk_text)
                if chunk_count == 1 and reply_to is not None:
                    segments.insert(0, {"type": "reply", "data": {"id": str(reply_to)}})
                result = await self.onebot.send_group_message(
                    group_id, segments, mark_sent=mark_sent
                )
                if chunk_count == 1:
                    first_message_id = _extract_message_id(result)
                current_chunk = []
                current_length = 0

            current_chunk.append(line)
            current_length += line_length

        if current_chunk:
            chunk_count += 1
            chunk_text = "\n".join(current_chunk)
            logger.debug(f"[消息分段] 发送第 {chunk_count} 段 (最后一段)")
            segments = message_to_segments(chunk_text)
            if chunk_count == 1 and reply_to is not None:
                segments.insert(0, {"type": "reply", "data": {"id": str(reply_to)}})
            result = await self.onebot.send_group_message(
                group_id, segments, mark_sent=mark_sent
            )
            if chunk_count == 1:
                first_message_id = _extract_message_id(result)

        logger.info(f"[消息分段] 已完成 {chunk_count} 段消息的发送")
        return first_message_id

    async def send_private_message(
        self,
        user_id: int,
        message: str,
        auto_history: bool = True,
        *,
        mark_sent: bool = True,
        reply_to: int | None = None,
        preferred_temp_group_id: int | None = None,
        history_message: str | None = None,
        attachments: list[dict[str, str]] | None = None,
    ) -> int | None:
        """发送私聊消息"""
        if not self.config.is_private_allowed(user_id):
            enabled = self.config.access_control_enabled()
            reason = self.config.private_access_denied_reason(user_id) or "unknown"
            logger.warning(
                "[访问控制] 已拦截私聊消息发送: user=%s reason=%s (access enabled=%s)",
                user_id,
                reason,
                enabled,
            )
            raise PermissionError(
                "blocked by access control: "
                f"type=private reason={reason} user_id={int(user_id)} enabled={enabled}"
            )

        safe_message = redact_string(message)
        logger.info(f"[发送消息] 目标用户:{user_id} | 内容摘要:{safe_message[:100]}...")

        segments = message_to_segments(message)

        # 准备历史记录文本
        history_content: str | None = None
        if auto_history:
            if history_message is not None:
                history_content = history_message
            else:
                history_content = extract_text(segments, self.bot_qq)

        # 发送消息
        bot_message_id: int | None = None
        if len(message) <= MAX_MESSAGE_LENGTH:
            send_segments = list(segments)
            if reply_to is not None:
                send_segments.insert(
                    0, {"type": "reply", "data": {"id": str(reply_to)}}
                )
            result, _ = await self._send_private_segments(
                user_id,
                send_segments,
                mark_sent=mark_sent,
                preferred_temp_group_id=preferred_temp_group_id,
            )
            bot_message_id = _extract_message_id(result)
        else:
            bot_message_id = await self._send_chunked_private(
                user_id,
                message,
                mark_sent=mark_sent,
                reply_to=reply_to,
                preferred_temp_group_id=preferred_temp_group_id,
            )

        # 发送成功后写入历史记录
        if auto_history and history_content is not None:
            history_attachments = _merge_attachment_refs(
                attachments,
                await self._register_local_segment_attachments(
                    "private",
                    user_id,
                    segments,
                ),
            )
            history_content = _append_attachment_refs(
                history_content,
                history_attachments,
            )
            logger.debug(f"[历史记录] 正在保存 Bot 私聊回复: user={user_id}")
            await self.history_manager.add_private_message(
                user_id=user_id,
                text_content=history_content,
                display_name="Bot",
                user_name="Bot",
                message_id=bot_message_id,
                attachments=history_attachments,
            )
        return bot_message_id

    async def send_group_forward_message(
        self,
        group_id: int,
        messages: list[dict[str, Any]],
        *,
        history_message: str,
        auto_history: bool = True,
    ) -> None:
        """发送群合并转发，并将可读摘要写入历史。"""
        if not self.config.is_group_allowed(group_id):
            enabled = self.config.access_control_enabled()
            reason = self.config.group_access_denied_reason(group_id) or "unknown"
            logger.warning(
                "[访问控制] 已拦截群合并转发: group=%s reason=%s (access enabled=%s)",
                group_id,
                reason,
                enabled,
            )
            raise PermissionError(
                "blocked by access control: "
                f"type=group reason={reason} group_id={int(group_id)} enabled={enabled}"
            )

        logger.info("[发送合并转发] 目标群:%s | 节点数:%s", group_id, len(messages))
        await self.onebot.send_forward_msg(group_id, messages)

        text_content = str(history_message or "").strip()
        if not auto_history or not text_content:
            return

        try:
            history_attachments = await self._register_local_segment_attachments(
                "group",
                group_id,
                _iter_segments_deep(messages),
            )
            text_content = _append_attachment_refs(text_content, history_attachments)
            await self.history_manager.add_group_message(
                group_id=group_id,
                sender_id=self.bot_qq,
                text_content=text_content,
                sender_nickname="Bot",
                group_name="",
                attachments=history_attachments,
            )
        except Exception:
            logger.exception("[历史记录] 记录群合并转发失败: group=%s", group_id)

    async def send_private_forward_message(
        self,
        user_id: int,
        messages: list[dict[str, Any]],
        *,
        history_message: str,
        auto_history: bool = True,
    ) -> None:
        """发送私聊合并转发，并将可读摘要写入历史。"""
        if not self.config.is_private_allowed(user_id):
            enabled = self.config.access_control_enabled()
            reason = self.config.private_access_denied_reason(user_id) or "unknown"
            logger.warning(
                "[访问控制] 已拦截私聊合并转发: user=%s reason=%s (access enabled=%s)",
                user_id,
                reason,
                enabled,
            )
            raise PermissionError(
                "blocked by access control: "
                f"type=private reason={reason} user_id={int(user_id)} enabled={enabled}"
            )

        send_private_forward = getattr(self.onebot, "send_private_forward_msg", None)
        if not callable(send_private_forward):
            raise RuntimeError("OneBot 客户端不支持私聊合并转发")

        logger.info(
            "[发送私聊合并转发] 目标用户:%s | 节点数:%s", user_id, len(messages)
        )
        try:
            await send_private_forward(user_id, messages)
        except TypeError:
            await send_private_forward(user_id=user_id, messages=messages)

        text_content = str(history_message or "").strip()
        if not auto_history or not text_content:
            return

        try:
            history_attachments = await self._register_local_segment_attachments(
                "private",
                user_id,
                _iter_segments_deep(messages),
            )
            text_content = _append_attachment_refs(text_content, history_attachments)
            await self.history_manager.add_private_message(
                user_id=user_id,
                text_content=text_content,
                display_name="Bot",
                user_name="Bot",
                attachments=history_attachments,
            )
        except Exception:
            logger.exception("[历史记录] 记录私聊合并转发失败: user=%s", user_id)

    async def _send_private_segments(
        self,
        user_id: int,
        segments: list[dict[str, Any]],
        *,
        mark_sent: bool = True,
        temp_group_id: int | None = None,
        preferred_temp_group_id: int | None = None,
    ) -> tuple[object, int | None]:
        """发送私聊消息段，必要时回退到群临时会话。"""
        if temp_group_id is not None:
            try:
                result = await self.onebot.send_private_message(
                    user_id,
                    segments,
                    group_id=temp_group_id,
                    mark_sent=mark_sent,
                )
                return result, temp_group_id
            except Exception as exc:
                logger.warning(
                    "[发送消息] 复用群临时会话失败，尝试其他共享群: user=%s group=%s err=%s",
                    user_id,
                    temp_group_id,
                    exc,
                )
                return await self._send_private_segments_via_temp_session(
                    user_id,
                    segments,
                    mark_sent=mark_sent,
                    skip_group_ids={temp_group_id},
                    preferred_group_id=preferred_temp_group_id,
                )

        try:
            result = await self.onebot.send_private_message(
                user_id,
                segments,
                mark_sent=mark_sent,
            )
            return result, None
        except Exception as exc:
            logger.warning(
                "[发送消息] 私聊直发失败，尝试群临时会话回退: user=%s err=%s",
                user_id,
                exc,
            )
            return await self._send_private_segments_via_temp_session(
                user_id,
                segments,
                mark_sent=mark_sent,
                preferred_group_id=preferred_temp_group_id,
            )

    async def _send_private_segments_via_temp_session(
        self,
        user_id: int,
        segments: list[dict[str, Any]],
        *,
        mark_sent: bool = True,
        skip_group_ids: set[int] | None = None,
        preferred_group_id: int | None = None,
    ) -> tuple[object, int]:
        """遍历共享群，逐个尝试通过群临时会话发送。"""
        skipped = skip_group_ids or set()
        seen_group_ids: set[int] = set()
        last_error: Exception | None = None

        async def _try_group(group_id: int) -> tuple[object, int] | None:
            nonlocal last_error
            if group_id <= 0 or group_id in seen_group_ids or group_id in skipped:
                return None
            seen_group_ids.add(group_id)

            try:
                result = await self.onebot.send_private_message(
                    user_id,
                    segments,
                    group_id=group_id,
                    mark_sent=mark_sent,
                )
                logger.info(
                    "[发送消息] 群临时会话发送成功: user=%s group=%s",
                    user_id,
                    group_id,
                )
                return result, group_id
            except Exception as exc:
                last_error = exc
                logger.debug(
                    "[发送消息] 群临时会话发送失败: user=%s group=%s err=%s",
                    user_id,
                    group_id,
                    exc,
                )
                return None

        if preferred_group_id is not None:
            preferred_result = await _try_group(int(preferred_group_id))
            if preferred_result is not None:
                return preferred_result

        group_list = await self.onebot.get_group_list()
        for group in group_list:
            try:
                raw_group_id = group.get("group_id")
                if raw_group_id is None:
                    continue
                group_id = int(raw_group_id)
            except (AttributeError, TypeError, ValueError):
                continue
            result = await _try_group(group_id)
            if result is not None:
                return result

        if last_error is not None:
            raise last_error
        raise RuntimeError(
            f"unable to find shared group temporary session for user {int(user_id)}"
        )

    async def _send_chunked_private(
        self,
        user_id: int,
        message: str,
        *,
        mark_sent: bool = True,
        reply_to: int | None = None,
        preferred_temp_group_id: int | None = None,
    ) -> int | None:
        """分段发送私聊消息，返回第一段的 message_id。"""
        logger.info(f"[消息分段] 消息过长 ({len(message)} 字符)，正在自动分段发送...")
        lines = message.split("\n")
        current_chunk: list[str] = []
        current_length = 0
        chunk_count = 0
        first_message_id: int | None = None
        temp_group_id: int | None = None

        for line in lines:
            line_length = len(line) + 1

            if current_length + line_length > MAX_MESSAGE_LENGTH and current_chunk:
                chunk_count += 1
                chunk_text = "\n".join(current_chunk)
                logger.debug(f"[消息分段] 发送第 {chunk_count} 段")
                segments = message_to_segments(chunk_text)
                if chunk_count == 1 and reply_to is not None:
                    segments.insert(0, {"type": "reply", "data": {"id": str(reply_to)}})
                result, temp_group_id = await self._send_private_segments(
                    user_id,
                    segments,
                    mark_sent=mark_sent,
                    temp_group_id=temp_group_id,
                    preferred_temp_group_id=preferred_temp_group_id,
                )
                if chunk_count == 1:
                    first_message_id = _extract_message_id(result)
                current_chunk = []
                current_length = 0

            current_chunk.append(line)
            current_length += line_length

        if current_chunk:
            chunk_count += 1
            chunk_text = "\n".join(current_chunk)
            logger.debug(f"[消息分段] 发送第 {chunk_count} 段 (最后一段)")
            segments = message_to_segments(chunk_text)
            if chunk_count == 1 and reply_to is not None:
                segments.insert(0, {"type": "reply", "data": {"id": str(reply_to)}})
            result, temp_group_id = await self._send_private_segments(
                user_id,
                segments,
                mark_sent=mark_sent,
                temp_group_id=temp_group_id,
                preferred_temp_group_id=preferred_temp_group_id,
            )
            if chunk_count == 1:
                first_message_id = _extract_message_id(result)

        logger.info(f"[消息分段] 已完成 {chunk_count} 段消息的发送")
        return first_message_id

    async def send_group_poke(
        self,
        group_id: int,
        user_id: int,
        *,
        mark_sent: bool = True,
    ) -> None:
        """在群聊中拍一拍指定成员。"""
        if not self.config.is_group_allowed(group_id):
            enabled = self.config.access_control_enabled()
            reason = self.config.group_access_denied_reason(group_id) or "unknown"
            logger.warning(
                "[访问控制] 已拦截群拍一拍: group=%s user=%s reason=%s (access enabled=%s)",
                group_id,
                user_id,
                reason,
                enabled,
            )
            raise PermissionError(
                "blocked by access control: "
                f"type=group reason={reason} group_id={int(group_id)} enabled={enabled}"
            )

        logger.info("[拍一拍] 群=%s 用户=%s", group_id, user_id)
        await self.onebot.send_group_poke(group_id, user_id, mark_sent=mark_sent)

    async def send_private_poke(
        self,
        user_id: int,
        *,
        mark_sent: bool = True,
    ) -> None:
        """在私聊中拍一拍指定用户。"""
        if not self.config.is_private_allowed(user_id):
            enabled = self.config.access_control_enabled()
            reason = self.config.private_access_denied_reason(user_id) or "unknown"
            logger.warning(
                "[访问控制] 已拦截私聊拍一拍: user=%s reason=%s (access enabled=%s)",
                user_id,
                reason,
                enabled,
            )
            raise PermissionError(
                "blocked by access control: "
                f"type=private reason={reason} user_id={int(user_id)} enabled={enabled}"
            )

        logger.info("[拍一拍] 私聊用户=%s", user_id)
        await self.onebot.send_private_poke(user_id, mark_sent=mark_sent)

    async def send_group_file(
        self,
        group_id: int,
        file_path: str,
        name: str | None = None,
        auto_history: bool = True,
    ) -> None:
        """通过统一发送层上传群文件。"""
        if not self.config.is_group_allowed(group_id):
            enabled = self.config.access_control_enabled()
            reason = self.config.group_access_denied_reason(group_id) or "unknown"
            logger.warning(
                "[访问控制] 已拦截群文件发送: group=%s reason=%s (access enabled=%s)",
                group_id,
                reason,
                enabled,
            )
            raise PermissionError(
                "blocked by access control: "
                f"type=group reason={reason} group_id={int(group_id)} enabled={enabled}"
            )

        file_name = name or Path(file_path).name
        logger.info("[发送文件] 目标群:%s | 文件:%s", group_id, file_name)

        await self.onebot.upload_group_file(group_id, file_path, file_name)

        if not auto_history:
            return

        file_size = _get_file_size(file_path)
        history_content = _build_file_history_message(file_name, file_size)
        attachments = await self.register_sent_file_attachment(
            "group",
            group_id,
            file_path,
            file_name,
        )
        history_content = _append_attachment_refs(history_content, attachments)
        try:
            await self.history_manager.add_group_message(
                group_id=group_id,
                sender_id=self.bot_qq,
                text_content=history_content,
                sender_nickname="Bot",
                group_name="",
                attachments=attachments,
            )
        except Exception:
            logger.exception(
                "[历史记录] 记录群文件发送失败: group=%s file=%s",
                group_id,
                file_name,
            )

    async def send_private_file(
        self,
        user_id: int,
        file_path: str,
        name: str | None = None,
        auto_history: bool = True,
    ) -> None:
        """通过统一发送层上传私聊文件。"""
        if not self.config.is_private_allowed(user_id):
            enabled = self.config.access_control_enabled()
            reason = self.config.private_access_denied_reason(user_id) or "unknown"
            logger.warning(
                "[访问控制] 已拦截私聊文件发送: user=%s reason=%s (access enabled=%s)",
                user_id,
                reason,
                enabled,
            )
            raise PermissionError(
                "blocked by access control: "
                f"type=private reason={reason} user_id={int(user_id)} enabled={enabled}"
            )

        file_name = name or Path(file_path).name
        logger.info("[发送文件] 目标用户:%s | 文件:%s", user_id, file_name)

        await self.onebot.upload_private_file(user_id, file_path, file_name)

        if not auto_history:
            return

        file_size = _get_file_size(file_path)
        history_content = _build_file_history_message(file_name, file_size)
        attachments = await self.register_sent_file_attachment(
            "private",
            user_id,
            file_path,
            file_name,
        )
        history_content = _append_attachment_refs(history_content, attachments)
        try:
            await self.history_manager.add_private_message(
                user_id=user_id,
                text_content=history_content,
                display_name="Bot",
                user_name="Bot",
                attachments=attachments,
            )
        except Exception:
            logger.exception(
                "[历史记录] 记录私聊文件发送失败: user=%s file=%s",
                user_id,
                file_name,
            )


class AddressBoundSender:
    """将当前逻辑私聊绑定到指定物理地址的轻量发送代理。"""

    def __init__(self, sender: MessageSender, address: DeliveryAddress) -> None:
        if address.target_type != "private":
            raise ValueError("AddressBoundSender 仅支持私聊地址")
        self._sender = sender
        self._address = address

    def __getattr__(self, name: str) -> Any:
        return getattr(self._sender, name)

    async def send_private_message(
        self,
        user_id: int,
        message: str,
        auto_history: bool = True,
        *,
        mark_sent: bool = True,
        reply_to: int | str | None = None,
        preferred_temp_group_id: int | None = None,
        history_message: str | None = None,
        attachments: list[dict[str, str]] | None = None,
    ) -> int | str | None:
        if int(user_id) != self._address.target_id:
            return await self._sender.send_private_message(
                user_id,
                message,
                auto_history=auto_history,
                mark_sent=mark_sent,
                reply_to=_coerce_qq_reply_id(reply_to),
                preferred_temp_group_id=preferred_temp_group_id,
                history_message=history_message,
                attachments=attachments,
            )
        return await self._sender.send_address_message(
            self._address,
            message,
            auto_history=auto_history,
            mark_sent=mark_sent,
            reply_to=reply_to,
            preferred_temp_group_id=preferred_temp_group_id,
            history_message=history_message,
            attachments=attachments,
        )

    async def send_private_file(
        self,
        user_id: int,
        file_path: str,
        name: str | None = None,
        auto_history: bool = True,
    ) -> None:
        if int(user_id) != self._address.target_id:
            await self._sender.send_private_file(
                user_id,
                file_path,
                name=name,
                auto_history=auto_history,
            )
            return
        await self._sender.send_address_file(
            self._address,
            file_path,
            name=name,
            auto_history=auto_history,
        )

    async def send_private_forward_message(
        self,
        user_id: int,
        messages: list[dict[str, Any]],
        *,
        history_message: str,
        auto_history: bool = True,
    ) -> None:
        if int(user_id) != self._address.target_id or self._address.channel == "qq":
            await self._sender.send_private_forward_message(
                user_id,
                messages,
                history_message=history_message,
                auto_history=auto_history,
            )
            return
        await self._send_weixin_forward(messages)
        sent_at_ms = time.time_ns() // 1_000_000
        if auto_history:
            history_attachments = (
                await self._sender._register_local_segment_attachments(
                    "private",
                    user_id,
                    _iter_segments_deep(messages),
                )
            )
            history_content = _append_attachment_refs(
                history_message,
                history_attachments,
            )
            await self._sender.history_manager.add_private_message(
                user_id=user_id,
                text_content=history_content,
                display_name="Bot",
                user_name="Bot",
                attachments=history_attachments,
                transport={
                    "channel": "wechat",
                    "address": self._address.canonical,
                    "direction": "outbound",
                    "sent_at_ms": sent_at_ms,
                },
            )

    async def _send_weixin_forward(self, messages: list[dict[str, Any]]) -> None:
        for node in messages:
            data = node.get("data")
            if not isinstance(data, dict):
                continue
            content = data.get("content")
            if isinstance(content, str) and content.strip():
                await self._sender.send_address_message(
                    self._address,
                    content,
                    auto_history=False,
                )
                continue
            if not isinstance(content, list):
                continue
            text_parts: list[str] = []
            for segment in content:
                if not isinstance(segment, dict):
                    continue
                segment_type = str(segment.get("type", "") or "").strip().lower()
                if segment_type not in {"text", "image", "video", "file"}:
                    logger.warning(
                        "[微信转发] 丢弃不支持的消息段: address=%s type=%s",
                        self._address.canonical,
                        segment_type or "unknown",
                    )
                    continue
                segment_data = segment.get("data")
                if not isinstance(segment_data, dict):
                    continue
                if segment_type == "text":
                    text_parts.append(str(segment_data.get("text", "") or ""))
                    continue
                path = _local_path_from_segment_source(segment_data.get("file"))
                if path is not None:
                    await self._sender.send_address_file(
                        self._address,
                        str(path),
                        name=path.name,
                        kind=segment_type,
                        auto_history=False,
                    )
            text = "".join(text_parts).strip()
            if text:
                await self._sender.send_address_message(
                    self._address,
                    text,
                    auto_history=False,
                )
