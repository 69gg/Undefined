"""MemeService 入库与后台任务处理。"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import replace
import hashlib
import logging
import mimetypes
from pathlib import Path
import shutil
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from PIL import Image

from Undefined.memes._image_utils import (
    _compose_grid,
    _extract_gif_frames,
    _guess_suffix,
    _is_retryable_llm_error,
    _normalize_tags,
    _now_iso,
)
from Undefined.memes.models import (
    IngestDigestLockEntry,
    MemeRecord,
    MemeSourceRecord,
    build_search_text,
)

if TYPE_CHECKING:
    from Undefined.memes.store import MemeStore
    from Undefined.memes.vector_store import MemeVectorStore

logger = logging.getLogger(__name__)


class MemeIngestMixin:
    if TYPE_CHECKING:
        _ai_client: Any | None
        _attachment_registry: Any | None
        _ingest_digest_locks: dict[str, Any]
        _ingest_digest_locks_guard: asyncio.Lock
        _job_queue: Any | None
        _store: MemeStore
        _vector_store: MemeVectorStore

        def _blob_dir(self) -> Path: ...
        def _cfg(self) -> Any: ...
        def _invalidate_global_image_cache(self, uid: str) -> None: ...
        def _preview_dir(self) -> Path: ...
        def _queue_enabled(self) -> bool: ...
        async def delete_meme(self, uid: str) -> bool: ...
        def enabled(self) -> bool: ...

    async def _acquire_ingest_digest_lock(self, digest: str) -> IngestDigestLockEntry:
        async with self._ingest_digest_locks_guard:
            entry = self._ingest_digest_locks.get(digest)
            if entry is None:
                entry = IngestDigestLockEntry(lock=asyncio.Lock())
                self._ingest_digest_locks[digest] = entry
            entry.users += 1
        try:
            await entry.lock.acquire()
        except BaseException:
            await self._release_ingest_digest_lock_reference(digest, entry)
            raise
        return entry

    async def _release_ingest_digest_lock_reference(
        self,
        digest: str,
        entry: IngestDigestLockEntry,
        *,
        release_lock: bool = False,
    ) -> None:
        if release_lock and entry.lock.locked():
            entry.lock.release()
        async with self._ingest_digest_locks_guard:
            entry.users = max(0, entry.users - 1)
            current = self._ingest_digest_locks.get(digest)
            if current is entry and entry.users == 0 and not entry.lock.locked():
                self._ingest_digest_locks.pop(digest, None)

    def _delete_file_if_exists(self, path: Path) -> None:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.debug("[memes] 删除文件失败: path=%s", path, exc_info=True)

    def _cleanup_gif_frame_files(self, uid: str) -> None:
        """清理 GIF 多帧分析产生的临时帧文件 ({uid}_f{i}.png)。"""
        preview_dir = self._preview_dir()
        for frame_file in preview_dir.glob(f"{uid}_f*.png"):
            try:
                frame_file.unlink(missing_ok=True)
            except OSError:
                logger.debug(
                    "[memes] 删除帧文件失败: path=%s", frame_file, exc_info=True
                )

    async def _cleanup_meme_artifacts(
        self,
        *,
        uid: str | None,
        blob_path: Path,
        preview_path: Path | None,
    ) -> None:
        if uid:
            try:
                await self._store.delete(uid)
                self._invalidate_global_image_cache(uid)
            except Exception:
                logger.exception(
                    "[memes] 清理记录失败: uid=%s",
                    uid,
                )
            try:
                await self._vector_store.delete(uid)
            except Exception:
                logger.exception(
                    "[memes] 清理向量索引失败: uid=%s",
                    uid,
                )
        await asyncio.to_thread(self._delete_file_if_exists, blob_path)
        if preview_path is not None and preview_path != blob_path:
            await asyncio.to_thread(self._delete_file_if_exists, preview_path)
        if uid:
            await asyncio.to_thread(self._cleanup_gif_frame_files, uid)

    async def enqueue_incoming_attachments(
        self,
        *,
        attachments: list[dict[str, str]],
        chat_type: str,
        chat_id: int,
        sender_id: int,
        message_id: int | None,
        scope_key: str,
    ) -> None:
        if not self.enabled() or not self._queue_enabled():
            return
        cfg = self._cfg()
        if chat_type == "group" and not bool(cfg.auto_ingest_group):
            return
        if chat_type == "private" and not bool(cfg.auto_ingest_private):
            return

        for item in attachments:
            media_type = str(item.get("media_type") or item.get("kind") or "").strip()
            uid = str(item.get("uid") or "").strip()
            if media_type != "image" or not uid:
                continue
            job = {
                "request_id": f"meme_ingest_{uid}",
                "kind": "ingest",
                "attachment_uid": uid,
                "scope_key": scope_key,
                "chat_type": chat_type,
                "chat_id": str(chat_id),
                "sender_id": str(sender_id),
                "message_id": str(message_id or ""),
                "queued_at": _now_iso(),
            }
            queue = self._job_queue
            if queue is None:
                return
            await queue.enqueue(job)

    async def enqueue_reanalyze(self, uid: str) -> str | None:
        if not self._queue_enabled():
            return None
        queue = self._job_queue
        if queue is None:
            return None
        result = await queue.enqueue(
            {
                "request_id": f"meme_reanalyze_{uid}",
                "kind": "reanalyze",
                "uid": uid,
                "queued_at": _now_iso(),
            }
        )
        return str(result)

    async def enqueue_reindex(self, uid: str) -> str | None:
        if not self._queue_enabled():
            return None
        queue = self._job_queue
        if queue is None:
            return None
        result = await queue.enqueue(
            {
                "request_id": f"meme_reindex_{uid}",
                "kind": "reindex",
                "uid": uid,
                "queued_at": _now_iso(),
            }
        )
        return str(result)

    async def process_job(self, job: Mapping[str, Any]) -> None:
        kind = str(job.get("kind") or "").strip().lower()
        if kind == "ingest":
            await self._process_ingest_job(job)
            return
        if kind == "reanalyze":
            await self._process_reanalyze_job(job)
            return
        if kind == "reindex":
            await self._process_reindex_job(job)
            return
        raise ValueError(f"unsupported meme job kind: {kind}")

    async def _process_reindex_job(self, job: Mapping[str, Any]) -> None:
        uid = str(job.get("uid") or "").strip()
        if not uid:
            return
        record = await self._store.get(uid)
        if record is None:
            return
        await self._vector_store.upsert(record)

    async def _process_reanalyze_job(self, job: Mapping[str, Any]) -> None:
        uid = str(job.get("uid") or "").strip()
        if not uid:
            return
        record = await self._store.get(uid)
        if record is None:
            return
        if self._ai_client is None:
            raise RuntimeError("reanalyze requires ai_client")
        analyze_path: str | list[str] = (
            record.preview_path if record.preview_path else record.blob_path
        )
        # GIF 多帧模式：与 ingest 路径保持一致
        if record.is_animated:
            cfg = self._cfg()
            if str(getattr(cfg, "gif_analysis_mode", "grid")).lower() == "multi":
                analyze_path = await self._prepare_gif_multi_frames(
                    Path(record.blob_path), uid
                )
        try:
            judgement = await self._ai_client.judge_meme_image(analyze_path)
        except Exception as exc:
            if _is_retryable_llm_error(exc):
                if isinstance(analyze_path, list):
                    await asyncio.to_thread(self._cleanup_gif_frame_files, uid)
                raise
            logger.exception(
                "[memes] judge stage failed during reanalyze: uid=%s err=%s", uid, exc
            )
            if isinstance(analyze_path, list):
                await asyncio.to_thread(self._cleanup_gif_frame_files, uid)
            return
        if not bool(judgement.get("is_meme", False)):
            if isinstance(analyze_path, list):
                await asyncio.to_thread(self._cleanup_gif_frame_files, uid)
            await self.delete_meme(uid)
            return
        try:
            described = await self._ai_client.describe_meme_image(analyze_path)
        except Exception as exc:
            if _is_retryable_llm_error(exc):
                if isinstance(analyze_path, list):
                    await asyncio.to_thread(self._cleanup_gif_frame_files, uid)
                raise
            logger.exception(
                "[memes] describe stage failed during reanalyze: uid=%s err=%s",
                uid,
                exc,
            )
            if isinstance(analyze_path, list):
                await asyncio.to_thread(self._cleanup_gif_frame_files, uid)
            return
        # GIF 多帧文件用完即清理
        if isinstance(analyze_path, list):
            await asyncio.to_thread(self._cleanup_gif_frame_files, uid)
        auto_description = str(described.get("description") or "").strip()
        next_tags = _normalize_tags(described.get("tags"))
        if not auto_description and not next_tags:
            logger.warning(
                "[memes] reanalyze describe failed, skip update: uid=%s", uid
            )
            return
        next_record = replace(
            record,
            auto_description=auto_description,
            ocr_text="",
            tags=next_tags,
            search_text=build_search_text(
                manual_description=record.manual_description,
                auto_description=auto_description,
                ocr_text="",
                tags=next_tags,
                aliases=record.aliases,
            ),
            updated_at=_now_iso(),
        )
        saved = await self._store.upsert_record(next_record)
        self._invalidate_global_image_cache(saved.uid)
        await self._vector_store.upsert(saved)

    async def _process_ingest_job(self, job: Mapping[str, Any]) -> None:
        if self._attachment_registry is None:
            raise RuntimeError("ingest requires attachment_registry")
        if self._ai_client is None:
            raise RuntimeError("ingest requires ai_client")

        attachment_uid = str(job.get("attachment_uid") or "").strip()
        scope_key = str(job.get("scope_key") or "").strip() or None
        if not attachment_uid:
            return
        attachment = self._attachment_registry.resolve(attachment_uid, scope_key)
        if attachment is None:
            raise FileNotFoundError(f"attachment uid unavailable: {attachment_uid}")
        if str(attachment.media_type).lower() != "image":
            return
        source_path = Path(str(attachment.local_path or ""))
        if not source_path.is_file():
            raise FileNotFoundError(source_path)
        file_size = source_path.stat().st_size
        cfg = self._cfg()
        if file_size > int(cfg.max_source_image_bytes):
            logger.info(
                "[memes] skip oversized image: uid=%s size=%s limit=%s",
                attachment_uid,
                file_size,
                cfg.max_source_image_bytes,
            )
            return

        digest = await asyncio.to_thread(self._hash_file, source_path)
        # 同一 SHA256 并发入库串行化，避免重复 AI 判定
        digest_lock_entry = await self._acquire_ingest_digest_lock(digest)
        try:
            existing = await self._store.find_by_sha256(digest)
            if existing is not None and not Path(existing.blob_path).is_file():
                logger.warning(
                    "[memes] 检测到孤儿记录，删除后重新入库: uid=%s blob_path=%s",
                    existing.uid,
                    existing.blob_path,
                )
                await self._cleanup_meme_artifacts(
                    uid=existing.uid,
                    blob_path=Path(existing.blob_path),
                    preview_path=(
                        Path(existing.preview_path) if existing.preview_path else None
                    ),
                )
                existing = await self._store.find_by_sha256(digest)
                if existing is not None and not Path(existing.blob_path).is_file():
                    raise RuntimeError(
                        f"stale meme record cleanup failed: uid={existing.uid}"
                    )
            source = MemeSourceRecord(
                uid=existing.uid if existing is not None else "",
                source_type="message_attachment",
                chat_type=str(job.get("chat_type") or ""),
                chat_id=str(job.get("chat_id") or ""),
                sender_id=str(job.get("sender_id") or ""),
                message_id=str(job.get("message_id") or ""),
                attachment_uid=attachment_uid,
                source_url=str(attachment.source_ref or ""),
                seen_at=_now_iso(),
            )
            if existing is not None:
                # 内容已存在：仅追加来源记录并刷新向量索引
                await self._store.add_source(replace(source, uid=existing.uid))
                await self._vector_store.upsert(existing)
                return

            with Image.open(source_path) as image:
                width, height = image.size
                is_animated = bool(getattr(image, "is_animated", False))
            if is_animated and not bool(cfg.allow_gif):
                return

            uid = await self._generate_uid()
            suffix = _guess_suffix(source_path, str(attachment.mime_type or ""))
            blob_path = self._blob_dir() / f"{uid}{suffix}"
            cleanup_preview_path = (
                self._preview_dir() / f"{uid}.png" if is_animated else blob_path
            )
            persisted_uid: str | None = None

            try:
                preview_path = await self._prepare_blob_and_preview(
                    source_path=source_path,
                    target_uid=uid,
                    suffix=suffix,
                    is_animated=is_animated,
                )
                if preview_path is not None:
                    cleanup_preview_path = preview_path
                mime_type = str(
                    attachment.mime_type
                    or mimetypes.guess_type(source_path.name)[0]
                    or "application/octet-stream"
                )
                analyze_path: str | list[str] = str(
                    preview_path if preview_path is not None else blob_path
                )
                if (
                    is_animated
                    and str(getattr(cfg, "gif_analysis_mode", "grid")).lower()
                    == "multi"
                ):
                    analyze_path = await self._prepare_gif_multi_frames(
                        source_path, uid
                    )
                try:
                    judgement = await self._ai_client.judge_meme_image(analyze_path)
                except Exception as exc:
                    if _is_retryable_llm_error(exc):
                        if isinstance(analyze_path, list):
                            await asyncio.to_thread(self._cleanup_gif_frame_files, uid)
                        raise
                    logger.exception(
                        "[memes] judge stage failed, treat as non-meme: uid=%s err=%s",
                        uid,
                        exc,
                    )
                    judgement = {"is_meme": False}
                if not bool(judgement.get("is_meme", False)):
                    if isinstance(analyze_path, list):
                        await asyncio.to_thread(self._cleanup_gif_frame_files, uid)
                    # 非表情包：清理已落盘文件，不入库
                    await self._cleanup_meme_artifacts(
                        uid=None,
                        blob_path=blob_path,
                        preview_path=cleanup_preview_path,
                    )
                    return

                try:
                    described = await self._ai_client.describe_meme_image(analyze_path)
                except Exception as exc:
                    if _is_retryable_llm_error(exc):
                        if isinstance(analyze_path, list):
                            await asyncio.to_thread(self._cleanup_gif_frame_files, uid)
                        raise
                    logger.exception(
                        "[memes] describe stage failed, drop uid=%s err=%s", uid, exc
                    )
                    described = {"description": "", "tags": []}
                # GIF 多帧文件用完即清理
                if isinstance(analyze_path, list):
                    await asyncio.to_thread(self._cleanup_gif_frame_files, uid)
                tags = _normalize_tags(described.get("tags"))
                auto_description = str(described.get("description") or "").strip()
                if not auto_description and not tags:
                    logger.warning(
                        "[memes] describe stage returned empty result, drop uid=%s", uid
                    )
                    await self._cleanup_meme_artifacts(
                        uid=None,
                        blob_path=blob_path,
                        preview_path=cleanup_preview_path,
                    )
                    return
                now = _now_iso()
                record = MemeRecord(
                    uid=uid,
                    content_sha256=digest,
                    blob_path=str(blob_path),
                    preview_path=(
                        str(preview_path) if preview_path is not None else None
                    ),
                    mime_type=mime_type,
                    file_size=file_size,
                    width=width,
                    height=height,
                    is_animated=is_animated,
                    enabled=True,
                    pinned=False,
                    auto_description=auto_description,
                    manual_description="",
                    ocr_text="",
                    tags=tags,
                    aliases=[],
                    search_text=build_search_text(
                        manual_description="",
                        auto_description=auto_description,
                        ocr_text="",
                        tags=tags,
                        aliases=[],
                    ),
                    use_count=0,
                    last_used_at="",
                    created_at=now,
                    updated_at=now,
                    status="ready",
                    segment_data={"subType": "1"},
                )
                saved = await self._store.upsert_record(record)
                self._invalidate_global_image_cache(saved.uid)
                persisted_uid = saved.uid
                await self._store.add_source(replace(source, uid=saved.uid))
                await self._vector_store.upsert(saved)
            except Exception:
                await self._cleanup_meme_artifacts(
                    uid=persisted_uid,
                    blob_path=blob_path,
                    preview_path=cleanup_preview_path,
                )
                raise
        finally:
            await self._release_ingest_digest_lock_reference(
                digest,
                digest_lock_entry,
                release_lock=True,
            )
        await self._prune_if_needed()

    async def _prepare_blob_and_preview(
        self,
        *,
        source_path: Path,
        target_uid: str,
        suffix: str,
        is_animated: bool,
    ) -> Path | None:
        blob_path = self._blob_dir() / f"{target_uid}{suffix}"

        def _copy() -> None:
            shutil.copy2(source_path, blob_path)

        await asyncio.to_thread(_copy)
        if not is_animated:
            return blob_path

        cfg = self._cfg()
        mode = str(getattr(cfg, "gif_analysis_mode", "grid")).lower()
        n_frames = max(2, int(getattr(cfg, "gif_analysis_frames", 6)))
        preview_path = self._preview_dir() / f"{target_uid}.png"

        def _render_preview() -> None:
            frames = _extract_gif_frames(source_path, n_frames)
            if mode == "multi":
                frames[0].save(preview_path, format="PNG")
            else:
                _compose_grid(frames, preview_path)
            for f in frames:
                f.close()

        await asyncio.to_thread(_render_preview)
        return preview_path

    async def _prepare_gif_multi_frames(
        self, source_path: Path, target_uid: str
    ) -> list[str]:
        """multi 模式：将 GIF 各帧单独保存为 PNG，返回路径列表。"""
        cfg = self._cfg()
        n_frames = max(2, int(getattr(cfg, "gif_analysis_frames", 6)))
        preview_dir = self._preview_dir()

        def _render_frames() -> list[str]:
            frames = _extract_gif_frames(source_path, n_frames)
            paths: list[str] = []
            for i, frame in enumerate(frames):
                p = preview_dir / f"{target_uid}_f{i}.png"
                frame.save(p, format="PNG")
                frame.close()
                paths.append(str(p))
            return paths

        return await asyncio.to_thread(_render_frames)

    def _hash_file(self, path: Path) -> str:
        hasher = hashlib.sha256()
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                hasher.update(chunk)
        return hasher.hexdigest()

    async def _generate_uid(self) -> str:
        while True:
            candidate = f"pic_{uuid4().hex[:8]}"
            if await self._store.get(candidate) is not None:
                continue
            if (
                self._attachment_registry is not None
                and self._attachment_registry.get(candidate) is not None
            ):
                continue
            return candidate

    async def _prune_if_needed(self) -> None:
        stats = await self._store.stats()
        cfg = self._cfg()
        total_count = int(stats.get("total_count", 0))
        total_bytes = int(stats.get("total_bytes", 0))
        if total_count <= int(cfg.max_items) and total_bytes <= int(
            cfg.max_total_bytes
        ):
            return
        candidates = await self._store.list_prune_candidates()
        for candidate in candidates:
            if candidate.pinned:
                continue
            if total_count <= int(cfg.max_items) and total_bytes <= int(
                cfg.max_total_bytes
            ):
                break
            deleted = await self._store.delete(candidate.uid)
            if deleted is None:
                continue
            self._invalidate_global_image_cache(candidate.uid)
            await self._vector_store.delete(candidate.uid)
            await asyncio.to_thread(
                self._delete_file_if_exists, Path(deleted.blob_path)
            )
            if deleted.preview_path and deleted.preview_path != deleted.blob_path:
                await asyncio.to_thread(
                    self._delete_file_if_exists,
                    Path(deleted.preview_path),
                )
            total_count -= 1
            total_bytes -= int(deleted.file_size)
