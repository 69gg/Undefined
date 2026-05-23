"""附件持久化注册表。

负责本地缓存、远程下载、去重与 scope 隔离；由 handlers 与 AI 协调器持有进程级单例。
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import mimetypes
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path
import time
from typing import Any, Awaitable, Callable, Mapping
from uuid import uuid4

import httpx

from Undefined.attachments.models import AttachmentRecord, _RemoteAttachmentTooLarge
from Undefined.attachments.segments import (
    display_name_from_source,
    is_http_url,
    media_kind_from_value,
    scope_from_context,
)
from Undefined.utils import io
from Undefined.utils.paths import (
    ATTACHMENT_CACHE_DIR,
    ATTACHMENT_REGISTRY_FILE,
    ensure_dir,
)

logger = logging.getLogger(__name__)

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
_ATTACHMENT_CACHE_MAX_AGE_SECONDS = 7 * 24 * 60 * 60
_ATTACHMENT_REGISTRY_MAX_RECORDS = 2000
_ATTACHMENT_CACHE_MAX_BYTES = 0
_ATTACHMENT_URL_REFERENCE_MAX_RECORDS = 2000
_ATTACHMENT_URL_MAX_LENGTH = 8192
_DEFAULT_REMOTE_DOWNLOAD_MAX_BYTES = 25 * 1024 * 1024


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


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


def _remote_reference_source_kind(source_kind: str) -> str:
    cleaned = str(source_kind or "").strip()
    if not cleaned:
        return "remote_url_reference"
    if cleaned.endswith("_reference"):
        return cleaned
    return f"{cleaned}_reference"


class AttachmentRegistry:
    """按会话作用域持久化的附件注册表。

    写入 JSON 注册表与本地缓存目录，支持远程 URL 引用与按需回源下载。
    """

    def __init__(
        self,
        *,
        registry_path: Path = ATTACHMENT_REGISTRY_FILE,
        cache_dir: Path = ATTACHMENT_CACHE_DIR,
        http_client: httpx.AsyncClient | None = None,
        max_records: int = _ATTACHMENT_REGISTRY_MAX_RECORDS,
        max_age_seconds: int = _ATTACHMENT_CACHE_MAX_AGE_SECONDS,
        max_cache_bytes: int = _ATTACHMENT_CACHE_MAX_BYTES,
        url_reference_max_records: int = _ATTACHMENT_URL_REFERENCE_MAX_RECORDS,
        url_max_length: int = _ATTACHMENT_URL_MAX_LENGTH,
        remote_download_max_bytes: int = _DEFAULT_REMOTE_DOWNLOAD_MAX_BYTES,
    ) -> None:
        self._registry_path = registry_path
        self._cache_dir = cache_dir
        self._http_client = http_client
        self._max_records = max(0, int(max_records))
        self._max_age_seconds = max(0, int(max_age_seconds))
        self._max_cache_bytes = max(0, int(max_cache_bytes))
        self._url_reference_max_records = max(0, int(url_reference_max_records))
        self._url_max_length = max(0, int(url_max_length))
        self._remote_download_max_bytes = max(0, int(remote_download_max_bytes))
        self._lock = asyncio.Lock()
        self._records: dict[str, AttachmentRecord] = {}
        self._loaded = False
        self._load_task: asyncio.Task[None] | None = None
        self._global_image_resolver: Callable[[str], AttachmentRecord | None] | None = (
            None
        )
        self._global_image_resolver_async: (
            Callable[[str], Awaitable[AttachmentRecord | None]] | None
        ) = None

    def set_remote_download_max_bytes(self, value: int) -> None:
        """设置单次远程下载字节上限。"""
        self._remote_download_max_bytes = max(0, int(value))

    def set_limits(
        self,
        *,
        remote_download_max_bytes: int | None = None,
        max_cache_bytes: int | None = None,
        max_records: int | None = None,
        max_age_seconds: int | None = None,
        url_reference_max_records: int | None = None,
        url_max_length: int | None = None,
    ) -> None:
        """批量更新注册表容量与 TTL 限制。"""
        if remote_download_max_bytes is not None:
            self._remote_download_max_bytes = max(0, int(remote_download_max_bytes))
        if max_cache_bytes is not None:
            self._max_cache_bytes = max(0, int(max_cache_bytes))
        if max_records is not None:
            self._max_records = max(0, int(max_records))
        if max_age_seconds is not None:
            self._max_age_seconds = max(0, int(max_age_seconds))
        if url_reference_max_records is not None:
            self._url_reference_max_records = max(0, int(url_reference_max_records))
        if url_max_length is not None:
            self._url_max_length = max(0, int(url_max_length))

    def set_global_image_resolver(
        self,
        resolver: Callable[[str], AttachmentRecord | None] | None,
    ) -> None:
        """注册同步全局图片 UID 回退解析器。"""
        self._global_image_resolver = resolver

    def set_global_image_resolver_async(
        self,
        resolver: Callable[[str], Awaitable[AttachmentRecord | None]] | None,
    ) -> None:
        """注册异步全局图片 UID 回退解析器。"""
        self._global_image_resolver_async = resolver

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

    def _normalized_url_ref(self, value: str) -> str:
        text = str(value or "").strip()
        if not is_http_url(text):
            return ""
        if self._url_max_length > 0 and len(text) > self._url_max_length:
            return ""
        return text

    def _record_with_local_path(
        self, record: AttachmentRecord, local_path: str | None
    ) -> AttachmentRecord:
        return replace(
            record,
            local_path=local_path,
            source_kind=_remote_reference_source_kind(record.source_kind)
            if local_path is None and is_http_url(record.source_ref)
            else record.source_kind,
        )

    def _remove_cached_content(
        self,
        record: AttachmentRecord,
        cache_path: Path | None,
        removable_paths: set[Path],
    ) -> AttachmentRecord | None:
        source_ref = self._normalized_url_ref(record.source_ref)
        if source_ref:
            if cache_path is not None:
                removable_paths.add(cache_path)
            return self._record_with_local_path(record, None)
        if cache_path is not None:
            removable_paths.add(cache_path)
        return None

    def _prune_records(self) -> bool:
        dirty = False
        now = time.time()
        retained: list[tuple[str, AttachmentRecord, Path | None, float, int]] = []
        removable_paths: set[Path] = set()

        for uid, record in self._records.items():
            cache_path = self._resolve_managed_cache_path(record.local_path)
            if record.local_path is None:
                has_url_ref = bool(self._normalized_url_ref(record.source_ref))
                if is_http_url(record.source_ref) and not has_url_ref:
                    dirty = True
                    continue
                try:
                    mtime = datetime.fromisoformat(record.created_at).timestamp()
                except ValueError:
                    mtime = now
                if (
                    not has_url_ref
                    and self._max_age_seconds > 0
                    and now - mtime > self._max_age_seconds
                ):
                    dirty = True
                    continue
                retained.append((uid, record, None, mtime, 0))
                continue
            if cache_path is None:
                replacement = self._remove_cached_content(record, None, removable_paths)
                if replacement is not None:
                    retained.append((uid, replacement, None, now, 0))
                dirty = True
                continue
            try:
                stat_result = cache_path.stat()
                mtime = float(stat_result.st_mtime)
                size = int(stat_result.st_size)
            except OSError:
                replacement = self._remove_cached_content(
                    record, cache_path, removable_paths
                )
                if replacement is not None:
                    retained.append((uid, replacement, None, now, 0))
                dirty = True
                continue
            if not cache_path.is_file():
                replacement = self._remove_cached_content(
                    record, cache_path, removable_paths
                )
                if replacement is not None:
                    retained.append((uid, replacement, None, mtime, 0))
                dirty = True
                continue
            if self._max_age_seconds > 0 and now - mtime > self._max_age_seconds:
                replacement = self._remove_cached_content(
                    record, cache_path, removable_paths
                )
                if replacement is not None:
                    retained.append((uid, replacement, None, mtime, 0))
                dirty = True
                continue
            retained.append((uid, record, cache_path, mtime, size))

        if self._max_records > 0 and len(retained) > self._max_records:
            # 超出记录上限时按 mtime 淘汰最旧条目
            retained.sort(key=lambda item: item[3])
            overflow = len(retained) - self._max_records
            for _uid, _record, cache_path, _mtime, _size in retained[:overflow]:
                if cache_path is not None:
                    removable_paths.add(cache_path)
            retained = retained[overflow:]
            dirty = True

        if self._max_cache_bytes > 0:
            cache_total = sum(
                size
                for _uid, _record, path, _mtime, size in retained
                if path is not None
            )
            if cache_total > self._max_cache_bytes:
                reduced: list[
                    tuple[str, AttachmentRecord, Path | None, float, int]
                ] = []
                for uid, record, cache_path, mtime, size in sorted(
                    retained, key=lambda item: item[3]
                ):
                    if cache_path is not None and cache_total > self._max_cache_bytes:
                        replacement = self._remove_cached_content(
                            record, cache_path, removable_paths
                        )
                        if replacement is not None:
                            reduced.append((uid, replacement, None, mtime, 0))
                        cache_total -= size
                        dirty = True
                    else:
                        reduced.append((uid, record, cache_path, mtime, size))
                retained = reduced

        if self._url_reference_max_records > 0:
            url_refs = [
                item
                for item in retained
                if item[2] is None and is_http_url(item[1].source_ref)
            ]
            if len(url_refs) > self._url_reference_max_records:
                # 仅 URL 引用（未下载）单独计数上限
                url_ref_ids = {
                    uid
                    for uid, _record, _path, _mtime, _size in sorted(
                        url_refs, key=lambda item: item[3]
                    )[: len(url_refs) - self._url_reference_max_records]
                }
                retained = [item for item in retained if item[0] not in url_ref_ids]
                dirty = True

        retained_records = {
            uid: record for uid, record, _path, _mtime, _size in retained
        }
        retained_paths = {
            path.resolve()
            for _uid, _record, path, _mtime, _size in retained
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
                    kind=media_kind_from_value(item.get("kind", "file")),
                    media_type=media_kind_from_value(
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
        """按 UID 读取内存中的附件记录（不触发磁盘加载）。"""
        return self._records.get(str(uid).strip())

    def resolve(self, uid: str, scope_key: str | None) -> AttachmentRecord | None:
        """同步解析 UID，含 scope 校验与全局图片回退。"""
        record = self.get(uid)
        if record is not None:
            # scope 不匹配时拒绝跨会话引用
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

    async def resolve_async(
        self, uid: str, scope_key: str | None
    ) -> AttachmentRecord | None:
        """异步解析 UID，优先异步全局回退解析器。"""
        record = self.get(uid)
        if record is not None:
            if record.scope_key and scope_key and record.scope_key != scope_key:
                return None
            return record
        if self._global_image_resolver_async is not None:
            try:
                record = await self._global_image_resolver_async(uid)
            except Exception:
                logger.exception(
                    "[AttachmentRegistry] async global image resolver failed: uid=%s",
                    uid,
                )
                record = None
        elif self._global_image_resolver is not None:
            try:
                record = self._global_image_resolver(uid)
            except Exception:
                logger.exception(
                    "[AttachmentRegistry] global image resolver failed: uid=%s", uid
                )
                record = None
        else:
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
        """从请求上下文推断 scope 后解析 UID。"""
        return self.resolve(uid, scope_from_context(context))

    async def get_url_by_uid(self, uid: str) -> str | None:
        """通过附件 UID 获取 source_ref（URL）。"""
        await self.load()
        record = self.get(uid)
        if record is None or not record.source_ref.strip():
            return None
        return record.source_ref.strip()

    async def get_uid_by_url(self, url: str) -> str | None:
        """通过 URL 查找对应的附件 UID。"""
        await self.load()
        url = url.strip()
        if not url:
            return None
        for record in self._records.values():
            if record.source_ref.strip() == url:
                return record.uid
        return None

    def _build_uid(self, prefix: str) -> str:
        while True:
            uid = f"{prefix}_{uuid4().hex[:8]}"
            if uid not in self._records:
                return uid

    def _find_by_sha256(
        self, scope_key: str, sha256: str, kind: str
    ) -> AttachmentRecord | None:
        """Find an existing record with matching scope, kind, and SHA-256.

        Only returns a record whose *local_path* still exists on disk.
        Must be called while ``self._lock`` is held.
        """
        for record in self._records.values():
            if (
                record.scope_key == scope_key
                and record.sha256 == sha256
                and record.kind == kind
                and record.local_path
                and Path(record.local_path).is_file()
            ):
                return record
        return None

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
        """将字节内容写入缓存并注册新附件（含 SHA-256 去重）。"""
        await self.load()
        normalized_kind = media_kind_from_value(kind)
        normalized_media_type = (
            "image" if normalized_kind == "image" else normalized_kind
        )
        normalized_mime = mime_type or _guess_mime_type(display_name, content)
        suffix = _guess_suffix(display_name, content, normalized_mime)
        prefix = "pic" if normalized_media_type == "image" else "file"

        async with self._lock:
            digest = await asyncio.to_thread(hashlib.sha256, content)
            digest_hex = digest.hexdigest()

            existing = self._find_by_sha256(scope_key, digest_hex, normalized_kind)
            if existing is not None:
                # 同 scope+SHA256 去重，复用已有 UID
                return existing

            uid = self._build_uid(prefix)
            file_name = f"{uid}{suffix}"
            cache_path = ensure_dir(self._cache_dir) / file_name
            await asyncio.to_thread(cache_path.write_bytes, content)

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
                sha256=digest_hex,
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
            return self._records.get(uid, record)

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
        """读取本地文件并注册为附件。"""
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
        """解码 ``data:`` URL 并注册附件。"""
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
        """下载远程 URL 或在上限时降级为 URL 引用。"""
        name = display_name or display_name_from_source(url, "attachment.bin")
        return await self._register_remote_url_or_reference(
            scope_key,
            url,
            kind=kind,
            display_name=name,
            source_kind=source_kind,
            source_ref=source_ref or url,
            segment_data=segment_data,
        )

    async def register_remote_reference(
        self,
        scope_key: str,
        url: str,
        *,
        kind: str,
        display_name: str | None = None,
        source_kind: str = "remote_url_reference",
        source_ref: str = "",
        mime_type: str | None = None,
        segment_data: Mapping[str, str] | None = None,
        description: str = "",
    ) -> AttachmentRecord:
        """仅登记远程 URL 引用，不下载内容。"""
        await self.load()
        if not self._normalized_url_ref(url):
            raise ValueError("远程附件 URL 为空或超过长度上限")
        normalized_kind = media_kind_from_value(kind)
        normalized_media_type = (
            "image" if normalized_kind == "image" else normalized_kind
        )
        prefix = "pic" if normalized_media_type == "image" else "file"
        ref = url
        normalized_segment_data = dict(segment_data or {})
        if source_ref and source_ref != url:
            normalized_segment_data.setdefault("original_source_ref", source_ref)
        name = display_name or display_name_from_source(url, "attachment.bin")
        digest_hex = hashlib.sha256(ref.encode("utf-8")).hexdigest()

        async with self._lock:
            for existing in self._records.values():
                if (
                    existing.scope_key == scope_key
                    and existing.kind == normalized_kind
                    and existing.local_path is None
                    and existing.source_ref == ref
                ):
                    return existing

            uid = self._build_uid(prefix)
            record = AttachmentRecord(
                uid=uid,
                scope_key=scope_key,
                kind=normalized_kind,
                media_type=normalized_media_type,
                display_name=name,
                source_kind=source_kind,
                source_ref=ref,
                local_path=None,
                mime_type=mime_type or mimetypes.guess_type(name)[0] or "",
                sha256=digest_hex,
                created_at=_now_iso(),
                segment_data={
                    str(k): str(v)
                    for k, v in normalized_segment_data.items()
                    if str(k).strip() and str(v).strip()
                },
                description=description,
            )
            self._records[uid] = record
            self._prune_records()
            await self._persist()
            return self._records.get(uid, record)

    async def _register_remote_url_or_reference(
        self,
        scope_key: str,
        url: str,
        *,
        kind: str,
        display_name: str,
        source_kind: str,
        source_ref: str,
        segment_data: Mapping[str, str] | None,
    ) -> AttachmentRecord:
        if not self._normalized_url_ref(url):
            raise ValueError("远程附件 URL 为空或超过长度上限")
        timeout = httpx.Timeout(_DEFAULT_REMOTE_TIMEOUT_SECONDS)
        max_bytes = self._remote_download_max_bytes
        reference_segment_data = dict(segment_data or {})
        if source_ref and source_ref != url:
            reference_segment_data.setdefault("original_source_ref", source_ref)
        if max_bytes <= 0:
            # 配置为 0 时一律只登记 URL 引用，不下载
            return await self.register_remote_reference(
                scope_key,
                url,
                kind=kind,
                display_name=display_name,
                source_kind=_remote_reference_source_kind(source_kind),
                source_ref=url,
                segment_data=reference_segment_data,
                description="远程附件未下载：remote_download_max_size_mb=0",
            )

        async def _stream(client: httpx.AsyncClient) -> tuple[bytes, str]:
            async with client.stream(
                "GET", url, timeout=timeout, follow_redirects=True
            ) as response:
                response.raise_for_status()
                mime_type = (
                    response.headers.get("content-type", "").split(";", 1)[0].strip()
                )
                raw_length = response.headers.get("content-length", "").strip()
                if raw_length.isdigit() and int(raw_length) > max_bytes:
                    raise _RemoteAttachmentTooLarge(mime_type)

                chunks: list[bytes] = []
                total = 0
                async for chunk in response.aiter_bytes():
                    total += len(chunk)
                    # 流式累计超限则降级为 URL 引用
                    if total > max_bytes:
                        raise _RemoteAttachmentTooLarge(mime_type)
                    chunks.append(chunk)
                return b"".join(chunks), mime_type

        try:
            if self._http_client is not None:
                content, mime_type = await _stream(self._http_client)
            else:
                async with httpx.AsyncClient(
                    timeout=timeout, follow_redirects=True
                ) as client:
                    content, mime_type = await _stream(client)
        except _RemoteAttachmentTooLarge as exc:
            return await self.register_remote_reference(
                scope_key,
                url,
                kind=kind,
                display_name=display_name,
                source_kind=_remote_reference_source_kind(source_kind),
                source_ref=url,
                mime_type=exc.mime_type,
                segment_data=reference_segment_data,
                description=f"远程附件超过下载上限 {max_bytes} bytes，保留 URL 引用。",
            )

        return await self.register_bytes(
            scope_key,
            content,
            kind=kind,
            display_name=display_name,
            source_kind=source_kind,
            source_ref=url,
            mime_type=mime_type or None,
            segment_data=reference_segment_data,
        )

    async def ensure_local_file(self, record: AttachmentRecord) -> AttachmentRecord:
        """若记录仅有 URL 引用则尝试回源下载到本地缓存。"""
        await self.load()
        if record.local_path and Path(record.local_path).is_file():
            return record
        source_ref = self._normalized_url_ref(record.source_ref)
        if not source_ref:
            return record
        existing_uids = set(self._records)
        refreshed = await self._register_remote_url_or_reference(
            record.scope_key,
            source_ref,
            kind=record.kind,
            display_name=record.display_name,
            source_kind=record.source_kind,
            source_ref=source_ref,
            segment_data=record.segment_data,
        )
        if refreshed.local_path is None:
            return refreshed
        async with self._lock:
            current = self._records.get(record.uid)
            if current is None:
                return refreshed
            updated = replace(
                current,
                local_path=refreshed.local_path,
                mime_type=refreshed.mime_type,
                sha256=refreshed.sha256,
                source_kind=refreshed.source_kind,
                segment_data=refreshed.segment_data,
            )
            self._records[record.uid] = updated
            if refreshed.uid != record.uid and refreshed.uid not in existing_uids:
                self._records.pop(refreshed.uid, None)
            self._prune_records()
            await self._persist()
            return self._records.get(record.uid, updated)
