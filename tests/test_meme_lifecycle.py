from __future__ import annotations

import asyncio
from pathlib import Path
import threading
from types import SimpleNamespace
from typing import cast

import pytest

from Undefined.memes import MemeService, MemeStore, MemeVectorStore
from Undefined.memes.models import MemeRecord


class _Vectors:
    def __init__(self) -> None:
        self.records: dict[str, MemeRecord] = {}

    async def upsert(self, record: MemeRecord) -> None:
        self.records[record.uid] = record

    async def delete(self, uid: str) -> None:
        self.records.pop(uid, None)


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
