"""Attachment registry and rich-media helpers."""

from __future__ import annotations

import asyncio
import base64
import binascii
from dataclasses import asdict, dataclass
from datetime import datetime
import hashlib
import logging
import mimetypes
from pathlib import Path
import re
import time
from typing import Any, Awaitable, Callable, Mapping, Sequence
from urllib.parse import unquote, urlsplit

import httpx

from Undefined.utils import io
from Undefined.utils.paths import (
    ATTACHMENT_CACHE_DIR,
    ATTACHMENT_REGISTRY_FILE,
    WEBUI_FILE_CACHE_DIR,
    ensure_dir,
)
from Undefined.utils.xml import escape_xml_attr

logger = logging.getLogger(__name__)

_PIC_TAG_PATTERN = re.compile(
    r"<pic\s+uid=(?P<quote>[\"'])(?P<uid>[^\"']+)(?P=quote)\s*/?>",
    re.IGNORECASE,
)
_MEDIA_LABELS = {
    "image": "图片",
    "file": "文件",
    "audio": "音频",
    "video": "视频",
    "record": "语音",
}
_WINDOWS_ABS_PATH_RE = re.compile(r"^[A-Za-z]:[\\/]")
_DEFAULT_REMOTE_TIMEOUT_SECONDS = 120.0
_IMAGE_SUFFIX_TO_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".svg": "image/svg+xml",
}
_MAGIC_IMAGE_SUFFIXES: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", ".png"),
    (b"\xff\xd8\xff", ".jpg"),
    (b"GIF87a", ".gif"),
    (b"GIF89a", ".gif"),
    (b"BM", ".bmp"),
)
_FORWARD_ATTACHMENT_MAX_DEPTH = 3
_ATTACHMENT_CACHE_MAX_AGE_SECONDS = 7 * 24 * 60 * 60
_ATTACHMENT_REGISTRY_MAX_RECORDS = 2000


@dataclass(frozen=True)
class AttachmentRecord:
    uid: str
    scope_key: str
    kind: str
    media_type: str
    display_name: str
    source_kind: str
    source_ref: str
    local_path: str | None
    mime_type: str
    sha256: str
    created_at: str
    segment_data: dict[str, str]
    semantic_kind: str = ""
    description: str = ""

    def prompt_ref(self) -> dict[str, str]:
        ref: dict[str, str] = {
            "uid": self.uid,
            "kind": self.kind,
            "media_type": self.media_type,
            "display_name": self.display_name,
        }
        if self.source_kind.strip():
            ref["source_kind"] = self.source_kind.strip()
        if self.semantic_kind.strip():
            ref["semantic_kind"] = self.semantic_kind.strip()
        if self.description.strip():
            ref["description"] = self.description.strip()
        return ref


@dataclass(frozen=True)
class RegisteredMessageAttachments:
    attachments: list[dict[str, str]]
    normalized_text: str


@dataclass(frozen=True)
class RenderedRichMessage:
    delivery_text: str
    history_text: str
    attachments: list[dict[str, str]]


class AttachmentRenderError(RuntimeError):
    """Raised when a `<pic uid="..."/>` tag cannot be rendered."""


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


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
    """Build a scope key for attachment visibility."""
    if webui_session:
        return "webui"

    group = _coerce_positive_int(group_id)
    if group is not None:
        return f"group:{group}"

    user = _coerce_positive_int(user_id)
    request_type_text = str(request_type or "").strip().lower()
    if request_type_text == "private" and user is not None:
        return f"private:{user}"
    if user is not None:
        return f"private:{user}"
    return None


def scope_from_context(context: Mapping[str, Any] | None) -> str | None:
    if not context:
        return None
    return build_attachment_scope(
        group_id=context.get("group_id"),
        user_id=context.get("user_id"),
        request_type=str(context.get("request_type", "") or ""),
        webui_session=bool(context.get("webui_session", False)),
    )


def attachment_refs_to_text(attachments: Sequence[Mapping[str, str]]) -> str:
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


def attachment_refs_to_xml(
    attachments: Sequence[Mapping[str, str]],
    *,
    indent: str = " ",
) -> str:
    if not attachments:
        return ""
    lines = [f"{indent}<attachments>"]
    for item in attachments:
        uid = str(item.get("uid", "") or "").strip()
        if not uid:
            continue
        kind = str(item.get("kind", "") or item.get("media_type", "") or "file").strip()
        media_type = str(item.get("media_type", "") or kind or "file").strip()
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
        semantic_kind = str(item.get("semantic_kind", "") or "").strip()
        if semantic_kind:
            attrs.append(f'semantic_kind="{escape_xml_attr(semantic_kind)}"')
        description = str(item.get("description", "") or "").strip()
        if description:
            attrs.append(f'description="{escape_xml_attr(description)}"')
        lines.append(f"{indent} <attachment {' '.join(attrs)} />")
    lines.append(f"{indent}</attachments>")
    return "\n".join(lines)


def append_attachment_text(
    base_text: str, attachments: Sequence[Mapping[str, str]]
) -> str:
    attachment_text = attachment_refs_to_text(attachments)
    if not attachment_text:
        return base_text
    if not base_text.strip():
        return attachment_text
    return f"{base_text}\n附件: {attachment_text}"


def _is_http_url(value: str) -> bool:
    return value.startswith("http://") or value.startswith("https://")


def _is_data_url(value: str) -> bool:
    return value.startswith("data:")


def _is_localish_path(value: str) -> bool:
    return (
        value.startswith("/")
        or value.startswith("file://")
        or bool(_WINDOWS_ABS_PATH_RE.match(value))
    )


def _decode_data_url(data_url: str) -> tuple[bytes, str]:
    header, _, payload = data_url.partition(",")
    if ";base64" not in header.lower():
        raise ValueError("unsupported data URL encoding")
    mime_type = (
        header.split(":", 1)[1].split(";", 1)[0].strip() or "application/octet-stream"
    )
    return base64.b64decode(payload), mime_type


def _guess_suffix_from_bytes(content: bytes) -> str:
    for magic, suffix in _MAGIC_IMAGE_SUFFIXES:
        if content.startswith(magic):
            return suffix
    if content.startswith(b"RIFF") and content[8:12] == b"WEBP":
        return ".webp"
    return ".bin"


def _guess_suffix(name: str, content: bytes, mime_type: str) -> str:
    suffix = Path(name).suffix.lower()
    if suffix:
        return suffix
    guessed_ext = mimetypes.guess_extension(mime_type or "")
    if guessed_ext:
        return guessed_ext.lower()
    return _guess_suffix_from_bytes(content)


def _guess_mime_type(name: str, content: bytes) -> str:
    guessed, _ = mimetypes.guess_type(name)
    if guessed:
        return guessed
    suffix = _guess_suffix_from_bytes(content)
    return _IMAGE_SUFFIX_TO_MIME.get(suffix, "application/octet-stream")


def _display_name_from_source(raw_source: str, fallback: str) -> str:
    if not raw_source:
        return fallback
    if raw_source.startswith("file://"):
        raw_source = raw_source[7:]
    name = Path(unquote(urlsplit(raw_source).path)).name
    return name or fallback


def _media_kind_from_value(value: str) -> str:
    text = str(value or "").strip().lower()
    if text in {"image", "file", "audio", "video", "record"}:
        return text
    return "file"


def _segment_text(
    type_: str, data: Mapping[str, Any], ref: Mapping[str, str] | None
) -> str:
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
        forward_id = str(data.get("id") or data.get("resid") or "").strip()
        return f"[合并转发: {forward_id}]" if forward_id else "[合并转发]"
    if ref is not None:
        label = _MEDIA_LABELS.get(
            str(ref.get("media_type") or ref.get("kind") or type_).strip(), "附件"
        )
        uid = str(ref.get("uid", "") or "").strip()
        name = str(ref.get("display_name", "") or "").strip()
        if uid and name:
            return f"[{label} uid={uid} name={name}]"
        if uid:
            return f"[{label} uid={uid}]"
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


def _normalize_message_segments(message: Any) -> list[Mapping[str, Any]]:
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


class AttachmentRegistry:
    """Persistent attachment registry scoped by conversation."""

    def __init__(
        self,
        *,
        registry_path: Path = ATTACHMENT_REGISTRY_FILE,
        cache_dir: Path = ATTACHMENT_CACHE_DIR,
        http_client: httpx.AsyncClient | None = None,
        max_records: int = _ATTACHMENT_REGISTRY_MAX_RECORDS,
        max_age_seconds: int = _ATTACHMENT_CACHE_MAX_AGE_SECONDS,
    ) -> None:
        self._registry_path = registry_path
        self._cache_dir = cache_dir
        self._http_client = http_client
        self._max_records = max(0, int(max_records))
        self._max_age_seconds = max(0, int(max_age_seconds))
        self._lock = asyncio.Lock()
        self._records: dict[str, AttachmentRecord] = {}
        self._loaded = False
        self._load_task: asyncio.Task[None] | None = None
        self._global_image_resolver: Callable[[str], AttachmentRecord | None] | None = (
            None
        )

    def set_global_image_resolver(
        self,
        resolver: Callable[[str], AttachmentRecord | None] | None,
    ) -> None:
        self._global_image_resolver = resolver

    def _resolve_managed_cache_path(self, raw_path: str | None) -> Path | None:
        text = str(raw_path or "").strip()
        if not text:
            return None
        try:
            path = Path(text).expanduser().resolve()
            cache_root = self._cache_dir.resolve()
        except Exception:
            return None
        if path == cache_root or cache_root not in path.parents:
            return None
        return path

    def _prune_records(self) -> bool:
        dirty = False
        now = time.time()
        retained: list[tuple[str, AttachmentRecord, Path | None, float]] = []
        removable_paths: set[Path] = set()

        for uid, record in self._records.items():
            cache_path = self._resolve_managed_cache_path(record.local_path)
            if cache_path is None or not cache_path.is_file():
                dirty = True
                continue
            try:
                mtime = float(cache_path.stat().st_mtime)
            except OSError:
                dirty = True
                removable_paths.add(cache_path)
                continue
            if self._max_age_seconds > 0 and now - mtime > self._max_age_seconds:
                dirty = True
                removable_paths.add(cache_path)
                continue
            retained.append((uid, record, cache_path, mtime))

        if self._max_records > 0 and len(retained) > self._max_records:
            retained.sort(key=lambda item: item[3])
            overflow = len(retained) - self._max_records
            for _uid, _record, cache_path, _mtime in retained[:overflow]:
                if cache_path is not None:
                    removable_paths.add(cache_path)
            retained = retained[overflow:]
            dirty = True

        retained_records = {uid: record for uid, record, _path, _mtime in retained}
        retained_paths = {
            path.resolve()
            for _uid, _record, path, _mtime in retained
            if path is not None and path.exists()
        }

        for path in removable_paths:
            try:
                resolved = path.resolve()
            except Exception:
                resolved = path
            if resolved in retained_paths:
                continue
            try:
                path.unlink(missing_ok=True)
                dirty = True
            except OSError:
                continue

        if self._cache_dir.exists():
            for item in self._cache_dir.iterdir():
                if not item.is_file():
                    continue
                try:
                    resolved = item.resolve()
                except Exception:
                    resolved = item
                if resolved in retained_paths:
                    continue
                try:
                    item.unlink()
                    dirty = True
                except OSError:
                    continue

        if dirty:
            self._records = retained_records
        return dirty

    def _load_records_from_payload(self, raw: Any) -> dict[str, AttachmentRecord]:
        if not isinstance(raw, dict):
            return {}
        loaded: dict[str, AttachmentRecord] = {}
        for uid, item in raw.items():
            if not isinstance(item, dict):
                continue
            try:
                loaded[str(uid)] = AttachmentRecord(
                    uid=str(item.get("uid") or uid),
                    scope_key=str(item.get("scope_key", "") or ""),
                    kind=_media_kind_from_value(item.get("kind", "file")),
                    media_type=_media_kind_from_value(
                        item.get("media_type") or item.get("kind") or "file"
                    ),
                    display_name=str(item.get("display_name", "") or ""),
                    source_kind=str(item.get("source_kind", "") or ""),
                    source_ref=str(item.get("source_ref", "") or ""),
                    local_path=str(item.get("local_path", "") or "") or None,
                    mime_type=str(
                        item.get("mime_type", "") or "application/octet-stream"
                    ),
                    sha256=str(item.get("sha256", "") or ""),
                    created_at=str(item.get("created_at", "") or ""),
                    segment_data={
                        str(k): str(v)
                        for k, v in dict(item.get("segment_data") or {}).items()
                        if str(k).strip() and str(v).strip()
                    },
                    semantic_kind=str(item.get("semantic_kind", "") or ""),
                    description=str(item.get("description", "") or ""),
                )
            except Exception:
                continue
        return loaded

    async def _load_from_disk_async(self) -> None:
        try:
            raw = await io.read_json(self._registry_path, use_lock=False)
        except Exception as exc:
            logger.warning("[AttachmentRegistry] 读取失败: %s", exc)
            self._loaded = True
            return
        self._records = self._load_records_from_payload(raw)
        dirty = self._prune_records()
        if dirty:
            await self._persist()
        self._loaded = True

    async def load(self) -> None:
        """等待注册表完成初始加载。"""
        if self._loaded:
            return
        if self._load_task is None:
            self._load_task = asyncio.create_task(self._load_from_disk_async())
        await self._load_task

    async def _persist(self) -> None:
        payload = {uid: asdict(record) for uid, record in self._records.items()}
        await io.write_json(self._registry_path, payload, use_lock=True)

    async def flush(self) -> None:
        """将当前注册表状态强制落盘。"""
        await self.load()
        async with self._lock:
            await self._persist()

    def get(self, uid: str) -> AttachmentRecord | None:
        return self._records.get(str(uid).strip())

    def resolve(self, uid: str, scope_key: str | None) -> AttachmentRecord | None:
        record = self.get(uid)
        if record is not None:
            if record.scope_key and scope_key and record.scope_key != scope_key:
                return None
            return record
        if self._global_image_resolver is not None:
            try:
                record = self._global_image_resolver(uid)
            except Exception:
                logger.exception(
                    "[AttachmentRegistry] global image resolver failed: uid=%s", uid
                )
                record = None
        if record is None:
            return None
        if record.scope_key and scope_key and record.scope_key != scope_key:
            return None
        return record

    def resolve_for_context(
        self,
        uid: str,
        context: Mapping[str, Any] | None,
    ) -> AttachmentRecord | None:
        return self.resolve(uid, scope_from_context(context))

    def _build_uid(self, prefix: str) -> str:
        from uuid import uuid4

        while True:
            uid = f"{prefix}_{uuid4().hex[:8]}"
            if uid not in self._records:
                return uid

    async def register_bytes(
        self,
        scope_key: str,
        content: bytes,
        *,
        kind: str,
        display_name: str,
        source_kind: str,
        source_ref: str = "",
        mime_type: str | None = None,
        segment_data: Mapping[str, str] | None = None,
    ) -> AttachmentRecord:
        await self.load()
        normalized_kind = _media_kind_from_value(kind)
        normalized_media_type = (
            "image" if normalized_kind == "image" else normalized_kind
        )
        normalized_mime = mime_type or _guess_mime_type(display_name, content)
        suffix = _guess_suffix(display_name, content, normalized_mime)
        prefix = "pic" if normalized_media_type == "image" else "file"

        async with self._lock:
            uid = self._build_uid(prefix)
            file_name = f"{uid}{suffix}"
            cache_path = ensure_dir(self._cache_dir) / file_name

            def _write() -> str:
                cache_path.write_bytes(content)
                return hashlib.sha256(content).hexdigest()

            digest = await asyncio.to_thread(_write)
            record = AttachmentRecord(
                uid=uid,
                scope_key=scope_key,
                kind=normalized_kind,
                media_type=normalized_media_type,
                display_name=display_name or file_name,
                source_kind=source_kind,
                source_ref=source_ref,
                local_path=str(cache_path),
                mime_type=normalized_mime,
                sha256=digest,
                created_at=_now_iso(),
                segment_data={
                    str(k): str(v)
                    for k, v in dict(segment_data or {}).items()
                    if str(k).strip() and str(v).strip()
                },
            )
            self._records[uid] = record
            self._prune_records()
            await self._persist()
            return record

    async def register_local_file(
        self,
        scope_key: str,
        local_path: str | Path,
        *,
        kind: str,
        display_name: str | None = None,
        source_kind: str = "local_file",
        source_ref: str = "",
        segment_data: Mapping[str, str] | None = None,
    ) -> AttachmentRecord:
        path = Path(str(local_path)).expanduser()
        if not path.is_absolute():
            path = (Path.cwd() / path).resolve()
        else:
            path = path.resolve()
        if not path.is_file():
            raise FileNotFoundError(path)

        def _read() -> bytes:
            return path.read_bytes()

        content = await asyncio.to_thread(_read)
        return await self.register_bytes(
            scope_key,
            content,
            kind=kind,
            display_name=display_name or path.name,
            source_kind=source_kind,
            source_ref=source_ref or str(path),
            mime_type=mimetypes.guess_type(path.name)[0] or None,
            segment_data=segment_data,
        )

    async def register_data_url(
        self,
        scope_key: str,
        data_url: str,
        *,
        kind: str,
        display_name: str,
        source_kind: str,
        source_ref: str = "",
        segment_data: Mapping[str, str] | None = None,
    ) -> AttachmentRecord:
        content, mime_type = _decode_data_url(data_url)
        return await self.register_bytes(
            scope_key,
            content,
            kind=kind,
            display_name=display_name,
            source_kind=source_kind,
            source_ref=source_ref,
            mime_type=mime_type,
            segment_data=segment_data,
        )

    async def register_remote_url(
        self,
        scope_key: str,
        url: str,
        *,
        kind: str,
        display_name: str | None = None,
        source_kind: str = "remote_url",
        source_ref: str = "",
        segment_data: Mapping[str, str] | None = None,
    ) -> AttachmentRecord:
        timeout = httpx.Timeout(_DEFAULT_REMOTE_TIMEOUT_SECONDS)
        if self._http_client is not None:
            response = await self._http_client.get(
                url, timeout=timeout, follow_redirects=True
            )
        else:
            async with httpx.AsyncClient(
                timeout=timeout, follow_redirects=True
            ) as client:
                response = await client.get(url)
        response.raise_for_status()
        name = display_name or _display_name_from_source(url, "attachment.bin")
        mime_type = response.headers.get("content-type", "").split(";", 1)[0].strip()
        return await self.register_bytes(
            scope_key,
            response.content,
            kind=kind,
            display_name=name,
            source_kind=source_kind,
            source_ref=source_ref or url,
            mime_type=mime_type or None,
            segment_data=segment_data,
        )


async def register_message_attachments(
    *,
    registry: AttachmentRegistry | None,
    segments: Sequence[Mapping[str, Any]],
    scope_key: str | None,
    resolve_image_url: Callable[[str], Awaitable[str | None]] | None = None,
    get_forward_messages: Callable[[str], Awaitable[list[dict[str, Any]]]]
    | None = None,
) -> RegisteredMessageAttachments:
    attachments: list[dict[str, str]] = []
    normalized_parts: list[str] = []
    if registry is None or not scope_key:
        for segment in segments:
            type_ = str(segment.get("type", "") or "")
            raw_data = segment.get("data", {})
            data = raw_data if isinstance(raw_data, Mapping) else {}
            normalized_parts.append(_segment_text(type_, data, None))
        return RegisteredMessageAttachments(
            attachments=[],
            normalized_text="".join(normalized_parts).strip(),
        )

    visited_forward_ids: set[str] = set()

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
                    display_name = _display_name_from_source(
                        raw_source,
                        f"image_{index + 1}.png",
                    )
                    if raw_source.startswith("base64://"):
                        payload = raw_source[len("base64://") :].strip()
                        content = base64.b64decode(payload)
                        record = await registry.register_bytes(
                            scope_key,
                            content,
                            kind="image",
                            display_name=display_name,
                            source_kind="base64_image",
                            source_ref=f"{prefix}segment:{index}",
                        )
                        ref = record.prompt_ref()
                    elif _is_data_url(raw_source):
                        record = await registry.register_data_url(
                            scope_key,
                            raw_source,
                            kind="image",
                            display_name=display_name,
                            source_kind="data_url_image",
                            source_ref=f"{prefix}segment:{index}",
                        )
                        ref = record.prompt_ref()
                    else:
                        resolved_source = raw_source
                        if raw_source and resolve_image_url is not None:
                            try:
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

                        if _is_http_url(resolved_source):
                            record = await registry.register_remote_url(
                                scope_key,
                                resolved_source,
                                kind="image",
                                display_name=display_name,
                                source_kind="remote_image",
                                source_ref=raw_source or resolved_source,
                            )
                            ref = record.prompt_ref()
                        elif _is_localish_path(resolved_source):
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
                            )
                            ref = record.prompt_ref()

                elif type_ == "file":
                    file_id = str(data.get("id", "") or "").strip()
                    raw_source = str(data.get("file") or data.get("url") or "").strip()
                    local_file_path: Path | None = None
                    if file_id:
                        local_file_path = _resolve_webui_file_id(file_id)
                    elif _is_localish_path(raw_source):
                        local_file_path = Path(
                            raw_source[7:]
                            if raw_source.startswith("file://")
                            else raw_source
                        )
                    display_name = (
                        str(data.get("name", "") or "").strip()
                        or (local_file_path.name if local_file_path is not None else "")
                        or _display_name_from_source(
                            raw_source, f"file_{index + 1}.bin"
                        )
                    )
                    if local_file_path is not None and local_file_path.is_file():
                        record = await registry.register_local_file(
                            scope_key,
                            local_file_path,
                            kind="file",
                            display_name=display_name,
                            source_kind="webui_file" if file_id else "local_file",
                            source_ref=file_id or raw_source or str(local_file_path),
                        )
                        ref = record.prompt_ref()
                    elif _is_http_url(raw_source):
                        record = await registry.register_remote_url(
                            scope_key,
                            raw_source,
                            kind="file",
                            display_name=display_name,
                            source_kind="remote_file",
                            source_ref=file_id or raw_source,
                        )
                        ref = record.prompt_ref()

                elif (
                    type_ == "forward"
                    and get_forward_messages is not None
                    and depth < _FORWARD_ATTACHMENT_MAX_DEPTH
                ):
                    forward_id = _extract_forward_id(data)
                    if forward_id and forward_id not in visited_forward_ids:
                        visited_forward_ids.add(forward_id)
                        try:
                            nodes = _normalize_forward_nodes(
                                await get_forward_messages(forward_id)
                            )
                        except Exception as exc:
                            logger.debug(
                                "[AttachmentRegistry] forward resolver failed: id=%s err=%s",
                                forward_id,
                                exc,
                            )
                            nodes = []
                        for node_index, node in enumerate(nodes):
                            raw_message = (
                                node.get("content")
                                or node.get("message")
                                or node.get("raw_message")
                            )
                            nested_segments = _normalize_message_segments(raw_message)
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
                attachments.append(ref)
            if depth == 0:
                normalized_parts.append(_segment_text(type_, data, ref))

    await _collect_from_segments(segments, depth=0, prefix="")

    return RegisteredMessageAttachments(
        attachments=attachments,
        normalized_text="".join(normalized_parts).strip(),
    )


async def render_message_with_pic_placeholders(
    message: str,
    *,
    registry: AttachmentRegistry | None,
    scope_key: str | None,
    strict: bool,
) -> RenderedRichMessage:
    if (
        not message
        or registry is None
        or not scope_key
        or "<pic" not in message.lower()
    ):
        return RenderedRichMessage(
            delivery_text=message,
            history_text=message,
            attachments=[],
        )

    attachments: list[dict[str, str]] = []
    delivery_parts: list[str] = []
    history_parts: list[str] = []
    last_index = 0

    for match in _PIC_TAG_PATTERN.finditer(message):
        uid = str(match.group("uid") or "").strip()
        delivery_parts.append(message[last_index : match.start()])
        history_parts.append(message[last_index : match.start()])
        last_index = match.end()

        record = registry.resolve(uid, scope_key)
        if record is None:
            replacement = f"[图片 uid={uid} 不可用]"
            if strict:
                raise AttachmentRenderError(f"图片 UID 不可用或不属于当前会话：{uid}")
            delivery_parts.append(replacement)
            history_parts.append(replacement)
            continue
        if record.media_type != "image":
            replacement = f"[图片 uid={uid} 类型错误]"
            if strict:
                raise AttachmentRenderError(f"UID 不是图片，不能用于 <pic>：{uid}")
            delivery_parts.append(replacement)
            history_parts.append(replacement)
            continue

        image_source = record.source_ref
        if record.local_path:
            image_source = Path(record.local_path).resolve().as_uri()
        elif not image_source:
            replacement = f"[图片 uid={uid} 缺少文件]"
            if strict:
                raise AttachmentRenderError(f"图片 UID 缺少可发送的文件：{uid}")
            delivery_parts.append(replacement)
            history_parts.append(replacement)
            continue

        cq_args = [f"file={image_source}"]
        for key, value in dict(getattr(record, "segment_data", {}) or {}).items():
            cleaned_key = str(key or "").strip()
            cleaned_value = str(value or "").strip()
            if not cleaned_key or not cleaned_value or cleaned_key == "file":
                continue
            cq_args.append(f"{cleaned_key}={cleaned_value}")
        delivery_parts.append(f"[CQ:image,{','.join(cq_args)}]")
        if record.display_name:
            history_parts.append(f"[图片 uid={uid} name={record.display_name}]")
        else:
            history_parts.append(f"[图片 uid={uid}]")
        attachments.append(record.prompt_ref())

    delivery_parts.append(message[last_index:])
    history_parts.append(message[last_index:])
    return RenderedRichMessage(
        delivery_text="".join(delivery_parts),
        history_text="".join(history_parts),
        attachments=attachments,
    )
