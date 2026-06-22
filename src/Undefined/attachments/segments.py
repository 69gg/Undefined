"""OneBot 消息段解析与会话作用域辅助。

负责 scope 键构建、附件引用文本/XML 序列化，以及从消息段批量注册附件；
不处理磁盘持久化或 CQ 标签渲染。
"""

from __future__ import annotations

import base64
import binascii
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Mapping, Sequence
from urllib.parse import unquote, urlsplit

import httpx

from Undefined.attachments.forward_snapshot import (
    load_forward_snapshot,
    snapshot_forward_tree,
)
from Undefined.attachments.models import RegisteredMessageAttachments
from Undefined.utils.paths import WEBUI_FILE_CACHE_DIR
from Undefined.utils.xml import escape_xml_attr

if TYPE_CHECKING:
    from Undefined.attachments.registry import AttachmentRegistry

logger = logging.getLogger(__name__)

_MEDIA_LABELS = {
    "image": "图片",
    "file": "文件",
    "audio": "音频",
    "video": "视频",
    "record": "语音",
    "pic": "图片",
    "forward": "合并转发",
}
_WINDOWS_ABS_PATH_RE = re.compile(r"^[A-Za-z]:[\\/]")
_FORWARD_ATTACHMENT_MAX_DEPTH = 3


def _coerce_positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            parsed = int(text)
        except ValueError:
            return None
        return parsed if parsed > 0 else None
    return None


def build_attachment_scope(
    *,
    group_id: Any = None,
    user_id: Any = None,
    request_type: str | None = None,
    webui_session: bool = False,
) -> str | None:
    """构建附件可见性作用域键。

    Args:
        group_id: 群号；优先于私聊作用域。
        user_id: 用户 QQ 号。
        request_type: 请求类型（``private`` 等）。
        webui_session: WebUI 会话时使用固定 ``webui`` 作用域。

    Returns:
        形如 ``group:123`` / ``private:456`` / ``webui`` 的键，无法推断时返回 ``None``。
    """
    if webui_session:
        return "webui"

    group = _coerce_positive_int(group_id)
    if group is not None:
        # 群聊作用域优先于私聊，避免同会话附件串读
        return f"group:{group}"

    user = _coerce_positive_int(user_id)
    request_type_text = str(request_type or "").strip().lower()
    if request_type_text == "private" and user is not None:
        return f"private:{user}"
    if user is not None:
        return f"private:{user}"
    return None


def scope_from_context(context: Mapping[str, Any] | None) -> str | None:
    """从请求上下文字典提取附件作用域键。"""
    if not context:
        return None
    return build_attachment_scope(
        group_id=context.get("group_id"),
        user_id=context.get("user_id"),
        request_type=str(context.get("request_type", "") or ""),
        webui_session=bool(context.get("webui_session", False)),
    )


def attachment_refs_to_text(attachments: Sequence[Mapping[str, str]]) -> str:
    """将附件引用列表转为可读占位文本。"""
    if not attachments:
        return ""
    parts: list[str] = []
    for item in attachments:
        uid = str(item.get("uid", "") or "").strip()
        if not uid:
            continue
        media_type = str(item.get("media_type") or item.get("kind") or "file").strip()
        label = _MEDIA_LABELS.get(media_type, "附件")
        name = str(item.get("display_name", "") or "").strip()
        if name:
            parts.append(f"[{label} uid={uid} name={name}]")
        else:
            parts.append(f"[{label} uid={uid}]")
    return " ".join(parts)


def attachment_ref_to_tag(attachment: Mapping[str, str]) -> str:
    """将单个附件引用序列化为 AI 可复用的统一内联标签。"""
    uid = str(attachment.get("uid", "") or "").strip()
    if not uid:
        return ""
    return f'<attachment uid="{escape_xml_attr(uid)}"/>'


def forward_ref_to_tag(ref: Mapping[str, str]) -> str:
    """将合并转发引用序列化为 AI 可按需读取的内联标签。"""
    uid = str(ref.get("uid", "") or "").strip()
    if not uid:
        return ""
    return f'<forward uid="{escape_xml_attr(uid)}"/>'


def attachment_refs_to_tags(
    attachments: Sequence[Mapping[str, str]],
    *,
    separator: str = " ",
) -> str:
    """将附件引用列表转为 ``<attachment uid="..."/>`` 内联标签串。"""
    tags = [tag for item in attachments if (tag := attachment_ref_to_tag(item))]
    return separator.join(tags)


def attachment_refs_to_xml(
    attachments: Sequence[Mapping[str, str]],
    *,
    indent: str = " ",
) -> str:
    """将附件引用列表序列化为 XML ``<attachments>`` 片段。"""
    if not attachments:
        return ""
    lines = [f"{indent}<attachments>"]
    for item in attachments:
        uid = str(item.get("uid", "") or "").strip()
        if not uid:
            continue
        kind = str(item.get("kind", "") or item.get("media_type", "") or "file").strip()
        media_type = str(item.get("media_type", "") or kind or "file").strip()
        if media_type == "forward" or kind == "forward":
            continue
        name = str(item.get("display_name", "") or "").strip()
        attrs = [
            f'uid="{escape_xml_attr(uid)}"',
            f'type="{escape_xml_attr(kind or media_type)}"',
            f'media_type="{escape_xml_attr(media_type)}"',
        ]
        if name:
            attrs.append(f'name="{escape_xml_attr(name)}"')
        source_kind = str(item.get("source_kind", "") or "").strip()
        if source_kind:
            attrs.append(f'source_kind="{escape_xml_attr(source_kind)}"')
        source_ref = str(item.get("source_ref", "") or "").strip()
        if source_ref:
            attrs.append(f'source_ref="{escape_xml_attr(source_ref)}"')
        semantic_kind = str(item.get("semantic_kind", "") or "").strip()
        if semantic_kind:
            attrs.append(f'semantic_kind="{escape_xml_attr(semantic_kind)}"')
        description = str(item.get("description", "") or "").strip()
        if description:
            attrs.append(f'description="{escape_xml_attr(description)}"')
        lines.append(f"{indent} <attachment {' '.join(attrs)} />")
    if len(lines) == 1:
        return ""
    lines.append(f"{indent}</attachments>")
    return "\n".join(lines)


def append_attachment_text(
    base_text: str, attachments: Sequence[Mapping[str, str]]
) -> str:
    """在基础文本后追加统一附件标签行。"""
    missing_tags = [
        tag
        for item in attachments
        if (tag := attachment_ref_to_tag(item)) and tag not in base_text
    ]
    if not missing_tags:
        return base_text
    attachment_text = " ".join(missing_tags)
    if not base_text.strip():
        return attachment_text
    return f"{base_text}\n附件: {attachment_text}"


def is_http_url(value: str) -> bool:
    """判断字符串是否为 HTTP(S) URL。"""
    return value.startswith("http://") or value.startswith("https://")


def is_data_url(value: str) -> bool:
    """判断字符串是否为 ``data:`` URL。"""
    return value.startswith("data:")


def is_localish_path(value: str) -> bool:
    """判断字符串是否像本地绝对路径或 ``file://`` URI。"""
    return (
        value.startswith("/")
        or value.startswith("file://")
        or bool(_WINDOWS_ABS_PATH_RE.match(value))
    )


def display_name_from_source(raw_source: str, fallback: str) -> str:
    """从 URL 或路径推断展示文件名。"""
    if not raw_source:
        return fallback
    if raw_source.startswith("file://"):
        raw_source = raw_source[7:]
    name = Path(unquote(urlsplit(raw_source).path)).name
    return name or fallback


def media_kind_from_value(value: str) -> str:
    """将任意媒体类型字符串规范为 registry 支持的 kind。"""
    text = str(value or "").strip().lower()
    if text in {"image", "file", "audio", "video", "record", "forward"}:
        return text
    return "file"


def segment_text(
    type_: str, data: Mapping[str, Any], ref: Mapping[str, str] | None
) -> str:
    """将单条 OneBot 消息段转为可读占位文本。"""
    if type_ == "text":
        return str(data.get("text", "") or "")
    if type_ == "at":
        qq = str(data.get("qq", "") or "").strip()
        name = str(data.get("name") or data.get("nickname") or "").strip()
        if qq and name:
            return f"[@{qq}({name})]"
        if qq:
            return f"[@{qq}]"
        return "[@]"
    if type_ == "face":
        return "[表情]"
    if type_ == "reply":
        reply_id = str(data.get("id") or data.get("message_id") or "").strip()
        return f"[引用: {reply_id}]" if reply_id else "[引用]"
    if type_ == "forward":
        if ref is not None:
            tag = forward_ref_to_tag(ref)
            if tag:
                return tag
        forward_id = str(data.get("id") or data.get("resid") or "").strip()
        return f"[合并转发: {forward_id}]" if forward_id else "[合并转发]"
    if ref is not None:
        tag = attachment_ref_to_tag(ref)
        if tag:
            return tag
    label = _MEDIA_LABELS.get(type_, "附件")
    raw = str(data.get("file") or data.get("url") or data.get("id") or "").strip()
    return f"[{label}: {raw}]" if raw else f"[{label}]"


def _resolve_webui_file_id(file_id: str) -> Path | None:
    if not file_id or not file_id.isalnum():
        return None
    file_dir = (Path.cwd() / WEBUI_FILE_CACHE_DIR / file_id).resolve()
    cache_root = (Path.cwd() / WEBUI_FILE_CACHE_DIR).resolve()
    if cache_root not in file_dir.parents and file_dir != cache_root:
        return None
    if not file_dir.is_dir():
        return None
    try:
        files = list(file_dir.iterdir())
    except OSError:
        return None
    for candidate in files:
        if candidate.is_file():
            return candidate
    return None


def _extract_forward_id(data: Mapping[str, Any]) -> str:
    forward_id = data.get("id") or data.get("resid") or data.get("message_id")
    return str(forward_id).strip() if forward_id is not None else ""


def segment_data_from_onebot_data(
    data: Mapping[str, Any],
    *,
    exclude_keys: set[str] | None = None,
) -> dict[str, str]:
    """提取 OneBot 段 ``data`` 中需保留的字符串键值。"""
    excluded = {key.strip().lower() for key in (exclude_keys or set()) if key.strip()}
    normalized: dict[str, str] = {}
    for raw_key, raw_value in data.items():
        key = str(raw_key or "").strip()
        if not key:
            continue
        if key.lower() in excluded:
            continue
        text = str(raw_value or "").strip()
        if not text:
            continue
        normalized[key] = text
    return normalized


def normalize_message_segments(message: Any) -> list[Mapping[str, Any]]:
    """将多种消息表示统一为 OneBot 段列表。"""
    if isinstance(message, list):
        normalized: list[Mapping[str, Any]] = []
        for item in message:
            if isinstance(item, Mapping):
                normalized.append(item)
            elif isinstance(item, str):
                normalized.append({"type": "text", "data": {"text": item}})
        return normalized
    if isinstance(message, Mapping):
        return [message]
    if isinstance(message, str):
        return [{"type": "text", "data": {"text": message}}]
    return []


def _normalize_forward_nodes(raw_nodes: Any) -> list[Mapping[str, Any]]:
    if isinstance(raw_nodes, list):
        return [node for node in raw_nodes if isinstance(node, Mapping)]
    if isinstance(raw_nodes, Mapping):
        messages = raw_nodes.get("messages")
        if isinstance(messages, list):
            return [node for node in messages if isinstance(node, Mapping)]
    return []


async def register_message_attachments(
    *,
    registry: AttachmentRegistry | None,
    segments: Sequence[Mapping[str, Any]],
    scope_key: str | None,
    resolve_image_url: Callable[[str], Awaitable[str | None]] | None = None,
    get_forward_messages: Callable[[str], Awaitable[list[dict[str, Any]]]]
    | None = None,
    register_forward_refs: bool = False,
    expand_forward_attachments: bool = True,
    snapshot_forward_messages: bool = False,
    snapshot_nested_forward_messages: bool = False,
) -> RegisteredMessageAttachments:
    """扫描消息段并将图片/文件注册到 ``AttachmentRegistry``。

    Args:
        registry: 附件注册表；为 ``None`` 时仅归一化文本。
        segments: OneBot 消息段序列。
        scope_key: 会话作用域键。
        resolve_image_url: 可选，将 ``file`` 字段解析为可下载 URL。
        get_forward_messages: 可选，拉取合并转发子消息。
        register_forward_refs: 是否将顶层合并转发注册为 ``forward_`` 引用。
        expand_forward_attachments: 是否递归扫描合并转发内的附件。
        snapshot_forward_messages: 是否读取合并转发并递归缓存可访问的节点快照。
        snapshot_nested_forward_messages: 向后兼容参数；递归缓存已覆盖内层转发。

    Returns:
        已注册附件引用与归一化纯文本。
    """
    attachments: list[dict[str, str]] = []
    forward_refs: list[dict[str, str]] = []
    normalized_parts: list[str] = []
    if registry is None or not scope_key:
        for segment in segments:
            type_ = str(segment.get("type", "") or "")
            raw_data = segment.get("data", {})
            data = raw_data if isinstance(raw_data, Mapping) else {}
            normalized_parts.append(segment_text(type_, data, None))
        return RegisteredMessageAttachments(
            attachments=[],
            normalized_text="".join(normalized_parts).strip(),
        )

    visited_forward_ids: set[str] = set()

    async def _fetch_forward_nodes(forward_id: str) -> list[Mapping[str, Any]]:
        if get_forward_messages is None:
            return []
        try:
            return _normalize_forward_nodes(await get_forward_messages(forward_id))
        except Exception as exc:
            logger.debug(
                "[AttachmentRegistry] forward resolver failed: id=%s err=%s",
                forward_id,
                exc,
            )
            return []

    async def _collect_from_segments(
        current_segments: Sequence[Mapping[str, Any]],
        *,
        depth: int,
        prefix: str,
    ) -> None:
        for index, segment in enumerate(current_segments):
            type_ = str(segment.get("type", "") or "").strip().lower()
            raw_data = segment.get("data", {})
            data = raw_data if isinstance(raw_data, Mapping) else {}
            ref: dict[str, str] | None = None

            try:
                if type_ == "image":
                    raw_source = str(data.get("file") or data.get("url") or "").strip()
                    if raw_source.startswith("base64://"):
                        display_name = f"image_{index + 1}.png"
                        payload = raw_source[len("base64://") :].strip()
                        content = base64.b64decode(payload)
                        record = await registry.register_bytes(
                            scope_key,
                            content,
                            kind="image",
                            display_name=display_name,
                            source_kind="base64_image",
                            source_ref=f"{prefix}segment:{index}",
                            segment_data=segment_data_from_onebot_data(
                                data,
                                exclude_keys={"file", "url"},
                            ),
                        )
                        ref = record.prompt_ref()
                    elif is_data_url(raw_source):
                        display_name = f"image_{index + 1}.png"
                        record = await registry.register_data_url(
                            scope_key,
                            raw_source,
                            kind="image",
                            display_name=display_name,
                            source_kind="data_url_image",
                            source_ref=f"{prefix}segment:{index}",
                            segment_data=segment_data_from_onebot_data(
                                data,
                                exclude_keys={"file", "url"},
                            ),
                        )
                        ref = record.prompt_ref()
                    else:
                        display_name = display_name_from_source(
                            raw_source,
                            f"image_{index + 1}.png",
                        )
                        resolved_source = raw_source
                        if raw_source and resolve_image_url is not None:
                            try:
                                # NapCat file id 需经 get_image 解析为可下载 URL
                                resolved = await resolve_image_url(raw_source)
                            except Exception as exc:
                                logger.debug(
                                    "[AttachmentRegistry] image resolver failed: file=%s err=%s",
                                    raw_source,
                                    exc,
                                )
                                resolved = None
                            if resolved:
                                resolved_source = str(resolved)

                        if is_http_url(resolved_source):
                            record = await registry.register_remote_url(
                                scope_key,
                                resolved_source,
                                kind="image",
                                display_name=display_name,
                                source_kind="remote_image",
                                source_ref=raw_source or resolved_source,
                                segment_data=segment_data_from_onebot_data(
                                    data,
                                    exclude_keys={"file", "url"},
                                ),
                            )
                            ref = record.prompt_ref()
                        elif is_localish_path(resolved_source):
                            local_path = (
                                resolved_source[7:]
                                if resolved_source.startswith("file://")
                                else resolved_source
                            )
                            record = await registry.register_local_file(
                                scope_key,
                                local_path,
                                kind="image",
                                display_name=display_name,
                                source_kind="local_image",
                                source_ref=raw_source or resolved_source,
                                segment_data=segment_data_from_onebot_data(
                                    data,
                                    exclude_keys={"file", "url"},
                                ),
                            )
                            ref = record.prompt_ref()

                elif type_ == "file":
                    file_id = str(data.get("id", "") or "").strip()
                    raw_source = str(data.get("file") or data.get("url") or "").strip()
                    local_file_path: Path | None = None
                    if file_id:
                        local_file_path = _resolve_webui_file_id(file_id)
                    elif is_localish_path(raw_source):
                        local_file_path = Path(
                            raw_source[7:]
                            if raw_source.startswith("file://")
                            else raw_source
                        )
                    display_name = (
                        str(data.get("name", "") or "").strip()
                        or (local_file_path.name if local_file_path is not None else "")
                        or display_name_from_source(raw_source, f"file_{index + 1}.bin")
                    )
                    if local_file_path is not None and local_file_path.is_file():
                        record = await registry.register_local_file(
                            scope_key,
                            local_file_path,
                            kind="file",
                            display_name=display_name,
                            source_kind="webui_file" if file_id else "local_file",
                            source_ref=file_id or raw_source or str(local_file_path),
                            segment_data=segment_data_from_onebot_data(
                                data,
                                exclude_keys={"file", "url"},
                            ),
                        )
                        ref = record.prompt_ref()
                    elif is_http_url(raw_source):
                        record = await registry.register_remote_url(
                            scope_key,
                            raw_source,
                            kind="file",
                            display_name=display_name,
                            source_kind="remote_file",
                            source_ref=file_id or raw_source,
                            segment_data=segment_data_from_onebot_data(
                                data,
                                exclude_keys={"file", "url"},
                            ),
                        )
                        ref = record.prompt_ref()

                elif type_ == "forward":
                    # 合并转发递归展开，深度上限防止无限嵌套
                    forward_id = _extract_forward_id(data)
                    forward_nodes: Sequence[Mapping[str, Any]] = []
                    if register_forward_refs and depth == 0 and forward_id:
                        register_forward = getattr(
                            registry,
                            "register_forward_reference",
                            None,
                        )
                        if callable(register_forward):
                            record = await register_forward(
                                scope_key,
                                forward_id,
                                display_name=f"合并转发 {forward_id}",
                                source_kind="onebot_forward",
                                segment_data=segment_data_from_onebot_data(data),
                            )
                            ref = record.prompt_ref()

                    should_fetch_forward = (
                        get_forward_messages is not None
                        and forward_id
                        and forward_id not in visited_forward_ids
                        and (
                            snapshot_forward_messages
                            or (
                                expand_forward_attachments
                                and depth < _FORWARD_ATTACHMENT_MAX_DEPTH
                            )
                        )
                    )
                    if should_fetch_forward:
                        assert get_forward_messages is not None
                        visited_forward_ids.add(forward_id)
                        if snapshot_forward_messages:
                            try:
                                await snapshot_forward_tree(
                                    scope_key=scope_key,
                                    forward_id=forward_id,
                                    get_forward_messages=get_forward_messages,
                                )
                            except Exception:
                                logger.debug(
                                    "[AttachmentRegistry] forward snapshot failed: id=%s",
                                    forward_id,
                                    exc_info=True,
                                )
                            forward_nodes = await load_forward_snapshot(
                                scope_key=scope_key,
                                forward_id=forward_id,
                            )
                        else:
                            forward_nodes = await _fetch_forward_nodes(forward_id)

                    if (
                        expand_forward_attachments
                        and get_forward_messages is not None
                        and depth < _FORWARD_ATTACHMENT_MAX_DEPTH
                        and forward_id
                    ):
                        if not forward_nodes:
                            if forward_id in visited_forward_ids:
                                forward_nodes = []
                            else:
                                visited_forward_ids.add(forward_id)
                                forward_nodes = await _fetch_forward_nodes(forward_id)
                        if not forward_nodes:
                            continue
                        for node_index, node in enumerate(forward_nodes):
                            raw_message = (
                                node.get("content")
                                or node.get("message")
                                or node.get("raw_message")
                            )
                            nested_segments = normalize_message_segments(raw_message)
                            if not nested_segments:
                                continue
                            await _collect_from_segments(
                                nested_segments,
                                depth=depth + 1,
                                prefix=f"{prefix}forward:{forward_id}:{node_index}:",
                            )
            except (
                binascii.Error,
                ValueError,
                FileNotFoundError,
                httpx.HTTPError,
            ) as exc:
                logger.warning(
                    "[AttachmentRegistry] segment registration skipped: type=%s index=%s err=%s",
                    type_,
                    index,
                    exc,
                )
            except Exception as exc:
                logger.exception(
                    "[AttachmentRegistry] unexpected segment registration failure: type=%s index=%s err=%s",
                    type_,
                    index,
                    exc,
                )

            if ref is not None:
                if str(ref.get("media_type") or "") == "forward":
                    forward_refs.append(ref)
                else:
                    attachments.append(ref)
            if depth == 0:
                normalized_parts.append(segment_text(type_, data, ref))

    await _collect_from_segments(segments, depth=0, prefix="")

    return RegisteredMessageAttachments(
        attachments=attachments,
        normalized_text="".join(normalized_parts).strip(),
        forward_refs=forward_refs,
    )
