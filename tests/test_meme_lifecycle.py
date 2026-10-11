from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
import threading
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from Undefined.memes import MemeService, MemeStore, MemeVectorStore
from Undefined.memes.models import MemeRecord
from Undefined.skills.toolsets.memes.send_meme_by_uid.handler import execute


class _Vectors:
    def __init__(self) -> None:
        self.records: dict[str, MemeRecord] = {}

    async def upsert(self, record: MemeRecord) -> None:
        self.records[record.uid] = record

    async def delete(self, uid: str) -> None:
        self.records.pop(uid, None)

    async def query(
        self, query: str, *, top_k: int, include_disabled: bool = False
    ) -> list[dict[str, Any]]:
        return [
            {"uid": record.uid, "semantic_score": 1.0}
            for record in self.records.values()
            if include_disabled or record.enabled
        ][:top_k]


def _record(tmp_path: Path) -> MemeRecord:
    blob = tmp_path / "meme.png"
    blob.write_bytes(b"isolated meme")
    return MemeRecord(
        uid="pic_lifecycle",
        content_sha256="isolated content",
        blob_path=str(blob),
        preview_path=str(blob),
        mime_type="image/png",
        file_size=blob.stat().st_size,
        width=1,
        height=1,
        is_animated=False,
        enabled=True,
        pinned=False,
        auto_description="original description",
        manual_description="",
        ocr_text="",
        search_text="original description",
        created_at="2026-10-07T12:00:00",
        updated_at="2026-10-07T12:00:00",
    )


async def _fixture(
    tmp_path: Path, *, store: MemeStore | None = None, vectors: _Vectors | None = None
) -> tuple[MemeService, MemeStore, _Vectors, MemeRecord]:
    store = store or MemeStore(tmp_path / "memes.sqlite3")
    record = await store.upsert_record(_record(tmp_path))
    vectors = vectors or _Vectors()
    await vectors.upsert(record)
    config = SimpleNamespace(
        enabled=True,
        preview_dir=str(tmp_path / "previews"),
        max_items=1,
        max_total_bytes=1024,
        keyword_top_k=10,
        semantic_top_k=10,
        rerank_top_k=10,
    )
    service = MemeService(
        config_getter=lambda: config,
        store=store,
        vector_store=cast(MemeVectorStore, vectors),
    )
    return service, store, vectors, record


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["disable", "edit", "delete"])
async def test_delayed_global_image_read_cannot_restore_invalidated_cache(
    tmp_path: Path, mutation: str
) -> None:
    entered = threading.Event()
    release = threading.Event()

    class _DelayedReadStore(MemeStore):
        armed = False

        def get_sync(self, uid: str) -> MemeRecord | None:
            record = super().get_sync(uid)
            if self.armed and not entered.is_set():
                entered.set()
                assert release.wait(timeout=5)
            return record

    store = _DelayedReadStore(tmp_path / "memes.sqlite3")
    service, _, _, record = await _fixture(tmp_path, store=store)
    store.armed = True
    resolving = asyncio.create_task(service.resolve_global_image(record.uid))
    try:
        assert await asyncio.to_thread(entered.wait, 3)
        if mutation == "delete":
            assert await service.delete_meme(record.uid)
        else:
            assert await service.update_meme(
                record.uid,
                enabled=False if mutation == "disable" else None,
                manual_description="edited description" if mutation == "edit" else None,
            )
        release.set()
        resolved = await asyncio.wait_for(resolving, timeout=3)
        cached = await service.resolve_global_image(record.uid)
        if mutation == "edit":
            assert resolved is not None
            assert resolved.description == "edited description"
            assert cached is resolved
        else:
            assert resolved is None
            assert cached is None
    finally:
        release.set()
        await asyncio.gather(resolving, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["usage", "index"])
async def test_successful_meme_delivery_stays_successful_after_stat_failure(
    tmp_path: Path, failure: str
) -> None:
    class _FailingStore(MemeStore):
        async def increment_use(self, uid: str, used_at: str) -> MemeRecord | None:
            if failure == "usage":
                raise RuntimeError("isolated usage write failure")
            return await super().increment_use(uid, used_at)

    class _FailingVectors(_Vectors):
        async def upsert(self, record: MemeRecord) -> None:
            if failure == "index" and record.use_count:
                raise RuntimeError("isolated index failure")
            await super().upsert(record)

    service, store, _, record = await _fixture(
        tmp_path,
        store=_FailingStore(tmp_path / "memes.sqlite3"),
        vectors=_FailingVectors(),
    )
    sender = SimpleNamespace(send_group_message=AsyncMock(return_value=1234))

    result = await execute(
        {"uid": record.uid},
        {
            "meme_service": service,
            "request_type": "group",
            "group_id": 123,
            "sender": sender,
        },
    )

    assert result == "表情包已发送（message_id=1234）"
    sender.send_group_message.assert_awaited_once()
    saved = await store.get(record.uid)
    assert saved is not None
    assert saved.use_count == (0 if failure == "usage" else 1)
    assert service._ingest_digest_locks == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["edit", "disable", "delete"])
@pytest.mark.parametrize("cancel", [False, True])
async def test_meme_usage_index_finishes_before_following_mutation(
    tmp_path: Path, mutation: str, cancel: bool
) -> None:
    entered = asyncio.Event()
    release = asyncio.Event()

    class _DelayedVectors(_Vectors):
        async def upsert(self, record: MemeRecord) -> None:
            if record.use_count == 1 and not entered.is_set():
                entered.set()
                await release.wait()
            await super().upsert(record)

    service, store, vectors, record = await _fixture(
        tmp_path, vectors=_DelayedVectors()
    )
    sender = SimpleNamespace(send_group_message=AsyncMock(return_value=1234))
    sending = asyncio.create_task(
        service.send_meme_by_uid(
            record.uid, {"request_type": "group", "group_id": 123, "sender": sender}
        )
    )
    following: asyncio.Task[Any] | None = None
    try:
        await asyncio.wait_for(entered.wait(), timeout=3)
        if cancel:
            sending.cancel()
        if mutation == "delete":
            following = asyncio.create_task(service.delete_meme(record.uid))
        else:
            following = asyncio.create_task(
                service.update_meme(
                    record.uid,
                    manual_description="latest description",
                    enabled=False if mutation == "disable" else None,
                )
            )
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        if cancel:
            sending.cancel()
        assert not sending.done()
        assert not following.done()
        release.set()
        if cancel:
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(sending, timeout=3)
        else:
            assert await asyncio.wait_for(sending, timeout=3) == (
                "表情包已发送（message_id=1234）"
            )
        assert await asyncio.wait_for(following, timeout=3)
        saved = await store.get(record.uid)
        if mutation == "delete":
            assert saved is None
            assert record.uid not in vectors.records
        else:
            assert saved is not None
            assert saved.manual_description == "latest description"
            assert saved.use_count == 1
            assert saved.enabled == (mutation != "disable")
            assert vectors.records[record.uid] == saved
        sender.send_group_message.assert_awaited_once()
        assert service._ingest_digest_locks == {}
    finally:
        release.set()
        await asyncio.gather(
            sending,
            *([following] if following is not None else []),
            return_exceptions=True,
        )


@pytest.mark.asyncio
async def test_old_meme_delivery_does_not_increment_reinserted_uid(
    tmp_path: Path,
) -> None:
    entered = asyncio.Event()
    release = asyncio.Event()

    async def send_group_message(*_args: Any, **_kwargs: Any) -> int:
        entered.set()
        await release.wait()
        return 1234

    service, store, vectors, record = await _fixture(tmp_path)
    sending = asyncio.create_task(
        service.send_meme_by_uid(
            record.uid,
            {
                "request_type": "group",
                "group_id": 123,
                "sender": SimpleNamespace(send_group_message=send_group_message),
            },
        )
    )
    try:
        await asyncio.wait_for(entered.wait(), timeout=3)
        assert await service.delete_meme(record.uid)
        inserted = await store.upsert_record(_record(tmp_path))
        assert inserted.generation != record.generation
        await vectors.upsert(inserted)
        release.set()
        assert await asyncio.wait_for(sending, timeout=3) == (
            "表情包已发送（message_id=1234）"
        )
        assert await store.get(record.uid) == inserted
        assert vectors.records[record.uid] == inserted
    finally:
        release.set()
        await asyncio.gather(sending, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["semantic", "hybrid"])
async def test_semantic_search_filters_disabled_sql_record_despite_stale_index(
    tmp_path: Path, mode: str
) -> None:
    service, store, _, record = await _fixture(tmp_path)
    assert await store.update_fields(record.uid, {"enabled": False}) is not None

    result = await service.search_memes("original description", query_mode=mode)
    included = await service.search_memes(
        "original description", query_mode=mode, include_disabled=True
    )

    assert result["count"] == 0
    assert included["count"] == 1
    assert included["items"][0]["enabled"] is False


@pytest.mark.asyncio
async def test_delivery_error_does_not_increment_meme_usage(tmp_path: Path) -> None:
    service, store, vectors, record = await _fixture(tmp_path)
    sender = SimpleNamespace(
        send_group_message=AsyncMock(
            side_effect=RuntimeError("isolated delivery failure")
        )
    )
    with pytest.raises(RuntimeError, match="isolated delivery failure"):
        await service.send_meme_by_uid(
            record.uid, {"request_type": "group", "group_id": 123, "sender": sender}
        )
    assert await store.get(record.uid) == record
    assert vectors.records[record.uid] == record


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["pin", "edit", "delete_other"])
@pytest.mark.parametrize("parallel", [False, True])
async def test_prune_skips_candidate_changed_after_snapshot(
    tmp_path: Path, mutation: str, parallel: bool
) -> None:
    entered = asyncio.Event()
    release = asyncio.Event()

    class _SnapshotStore(MemeStore):
        async def list_prune_candidates(self) -> list[MemeRecord]:
            records = await super().list_prune_candidates()
            entered.set()
            await release.wait()
            return records

    service, store, vectors, record = await _fixture(
        tmp_path, store=_SnapshotStore(tmp_path / "memes.sqlite3")
    )
    other_blob = tmp_path / "other.png"
    other_blob.write_bytes(b"second isolated meme")
    other = await store.upsert_record(
        replace(
            record,
            uid="pic_other",
            content_sha256="other content",
            blob_path=str(other_blob),
            preview_path=str(other_blob),
            file_size=other_blob.stat().st_size,
            use_count=1,
            generation="",
        )
    )
    await vectors.upsert(other)
    pruning = asyncio.create_task(service._prune_if_needed())
    prunings = [pruning]
    try:
        await asyncio.wait_for(entered.wait(), timeout=3)
        if parallel:
            prunings.append(asyncio.create_task(service._prune_if_needed()))
        if mutation == "delete_other":
            assert await service.delete_meme(other.uid)
        else:
            assert await service.update_meme(
                record.uid,
                pinned=True if mutation == "pin" else None,
                manual_description="edited description" if mutation == "edit" else None,
            )
        protected = await store.get(record.uid)
        release.set()
        await asyncio.wait_for(asyncio.gather(*prunings), timeout=3)
        assert await store.get(record.uid) == protected
        assert Path(record.blob_path).is_file()
        assert vectors.records[record.uid] == protected
        assert await store.get(other.uid) is None
        assert not other_blob.exists()
        assert (await store.stats())["total_count"] == 1
        assert service._ingest_digest_locks == {}
    finally:
        release.set()
        await asyncio.gather(*prunings, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["index", "blob", "preview", "frames"])
async def test_failed_delete_keeps_metadata_and_allows_cleanup_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    armed = False

    class _FailingVectors(_Vectors):
        async def delete(self, uid: str) -> None:
            if armed and failure == "index":
                raise RuntimeError("isolated vector delete failure")
            await super().delete(uid)

    service, store, vectors, record = await _fixture(
        tmp_path, vectors=_FailingVectors()
    )
    preview = tmp_path / "preview.png"
    preview.write_bytes(b"isolated preview")
    record = await store.upsert_record(replace(record, preview_path=str(preview)))
    await vectors.upsert(record)
    frames = tmp_path / "previews"
    frames.mkdir()
    frame = frames / f"{record.uid}_f0.png"
    frame.write_bytes(b"isolated frame")
    target = {
        "blob": Path(record.blob_path),
        "preview": preview,
        "frames": frame,
    }.get(failure)
    original_unlink = Path.unlink

    def failing_unlink(self: Path, missing_ok: bool = False) -> None:
        if armed and self == target:
            raise OSError("isolated file delete failure")
        original_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", failing_unlink)
    armed = True
    error_type = RuntimeError if failure == "index" else OSError
    with pytest.raises(error_type, match="isolated .* delete failure"):
        await service.delete_meme(record.uid)
    assert await store.get(record.uid) == record
    assert (await store.stats())["total_count"] == 1
    assert (await store.stats())["total_bytes"] == record.file_size
    if failure == "index":
        assert Path(record.blob_path).is_file()
        assert preview.is_file()
        assert frame.is_file()
        assert vectors.records[record.uid] == record
    else:
        assert target is not None and target.is_file()

    armed = False
    assert await service.delete_meme(record.uid)
    assert await store.get(record.uid) is None
    assert record.uid not in vectors.records
    assert not Path(record.blob_path).exists()
    assert not preview.exists()
    assert not frame.exists()
    assert (await store.stats())["total_count"] == 0
    assert service._ingest_digest_locks == {}


@pytest.mark.asyncio
async def test_stale_conditional_delete_does_not_touch_index_or_files(
    tmp_path: Path,
) -> None:
    service, store, vectors, record = await _fixture(tmp_path)
    assert await service.update_meme(
        record.uid, manual_description="latest description"
    )
    current = await store.get(record.uid)

    assert not await service.delete_meme(record.uid, expected_record=record)

    assert await store.get(record.uid) == current
    assert vectors.records[record.uid] == current
    assert Path(record.blob_path).is_file()


@pytest.mark.asyncio
async def test_cancelled_delete_finishes_cleanup_before_following_edit(
    tmp_path: Path,
) -> None:
    entered = asyncio.Event()
    release = asyncio.Event()

    class _DelayedVectors(_Vectors):
        async def delete(self, uid: str) -> None:
            entered.set()
            await release.wait()
            await super().delete(uid)

    service, store, vectors, record = await _fixture(
        tmp_path, vectors=_DelayedVectors()
    )
    deleting = asyncio.create_task(service.delete_meme(record.uid))
    editing: asyncio.Task[dict[str, Any] | None] | None = None
    try:
        await asyncio.wait_for(entered.wait(), timeout=3)
        deleting.cancel()
        editing = asyncio.create_task(
            service.update_meme(record.uid, manual_description="must not restore")
        )
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        deleting.cancel()
        assert not deleting.done()
        assert not editing.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(deleting, timeout=3)
        assert await asyncio.wait_for(editing, timeout=3) is None
        assert await store.get(record.uid) is None
        assert record.uid not in vectors.records
        assert not Path(record.blob_path).exists()
        assert service._ingest_digest_locks == {}
    finally:
        release.set()
        await asyncio.gather(
            deleting,
            *([editing] if editing is not None else []),
            return_exceptions=True,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["usage", "index"])
async def test_cancelled_meme_usage_preserves_cancellation_when_cleanup_fails(
    tmp_path: Path, failure: str
) -> None:
    entered = asyncio.Event()
    release = asyncio.Event()

    class _DelayedFailingStore(MemeStore):
        async def increment_use(self, uid: str, used_at: str) -> MemeRecord | None:
            if failure == "usage":
                entered.set()
                await release.wait()
                raise RuntimeError("isolated usage failure after cancellation")
            return await super().increment_use(uid, used_at)

    class _DelayedFailingVectors(_Vectors):
        async def upsert(self, record: MemeRecord) -> None:
            if failure == "index" and record.use_count:
                entered.set()
                await release.wait()
                raise RuntimeError("isolated index failure after cancellation")
            await super().upsert(record)

    service, store, _, record = await _fixture(
        tmp_path,
        store=_DelayedFailingStore(tmp_path / "memes.sqlite3"),
        vectors=_DelayedFailingVectors(),
    )
    sender = SimpleNamespace(send_group_message=AsyncMock(return_value=1234))
    sending = asyncio.create_task(
        service.send_meme_by_uid(
            record.uid, {"request_type": "group", "group_id": 123, "sender": sender}
        )
    )
    try:
        await asyncio.wait_for(entered.wait(), timeout=3)
        sending.cancel()
        await asyncio.sleep(0)
        sending.cancel()
        assert not sending.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(sending, timeout=3)
        assert sending.cancelled()
        sender.send_group_message.assert_awaited_once()
        saved = await store.get(record.uid)
        assert saved is not None
        assert saved.use_count == (0 if failure == "usage" else 1)
        assert service._ingest_digest_locks == {}
    finally:
        release.set()
        await asyncio.gather(sending, return_exceptions=True)
