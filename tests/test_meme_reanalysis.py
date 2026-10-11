from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
import sqlite3
import threading
from types import SimpleNamespace
from typing import Any, cast

from aiohttp import web
from PIL import Image
import pytest

from Undefined.api._context import RuntimeAPIContext
from Undefined.api.routes.memes import meme_delete_handler, meme_update_handler
from Undefined.memes import MemeService, MemeStore, MemeVectorStore
from Undefined.memes.models import MemeRecord
from Undefined.memes._image_utils import extract_gif_frames


class _ControlledAI:
    def __init__(self, *, is_meme: bool = True) -> None:
        self.is_meme = is_meme
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def judge_meme_image(self, _path: str | list[str]) -> dict[str, Any]:
        self.entered.set()
        await self.release.wait()
        return {"is_meme": self.is_meme}

    async def describe_meme_image(self, _path: str | list[str]) -> dict[str, Any]:
        return {"description": "generated description", "tags": ["generated"]}


class _RecordingVectors:
    def __init__(self) -> None:
        self.records: dict[str, MemeRecord] = {}
        self.block_analysis = False
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def upsert(self, record: MemeRecord) -> None:
        if self.block_analysis and record.manual_description == "original manual":
            self.entered.set()
            await self.release.wait()
        self.records[record.uid] = record

    async def delete(self, uid: str) -> None:
        self.records.pop(uid, None)


def _config(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(enabled=True, preview_dir=str(tmp_path / "previews"))


def _record(tmp_path: Path) -> MemeRecord:
    blob = tmp_path / "meme.png"
    blob.write_bytes(b"isolated image")
    return MemeRecord(
        uid="pic_reanalysis",
        content_sha256="same content",
        blob_path=str(blob),
        preview_path=str(blob),
        mime_type="image/png",
        file_size=blob.stat().st_size,
        width=1,
        height=1,
        is_animated=False,
        enabled=True,
        pinned=False,
        auto_description="original auto",
        manual_description="original manual",
        ocr_text="",
        tags=["original"],
        aliases=["original alias"],
        search_text="original manual original original alias",
        use_count=7,
        created_at="2026-10-06T12:00:00",
        updated_at="2026-10-06T12:00:00",
    )


async def _fixture(
    tmp_path: Path, ai: _ControlledAI, *, store: MemeStore | None = None
) -> tuple[MemeService, MemeStore, _RecordingVectors, MemeRecord]:
    store = store or MemeStore(tmp_path / "memes.sqlite3")
    record = await store.upsert_record(_record(tmp_path))
    vectors = _RecordingVectors()
    await vectors.upsert(record)
    config = _config(tmp_path)
    service = MemeService(
        config_getter=lambda: config,
        store=store,
        vector_store=cast(MemeVectorStore, vectors),
        ai_client=ai,
    )
    return service, store, vectors, record


def _context(service: MemeService) -> RuntimeAPIContext:
    return RuntimeAPIContext(
        config_getter=lambda: SimpleNamespace(),
        onebot=None,
        ai=None,
        command_dispatcher=None,
        queue_manager=None,
        history_manager=None,
        meme_service=service,
    )


def _request(uid: str, payload: dict[str, Any] | None = None) -> web.Request:
    async def json_body() -> dict[str, Any]:
        return payload or {}

    return cast(web.Request, SimpleNamespace(match_info={"uid": uid}, json=json_body))


@pytest.mark.asyncio
@pytest.mark.parametrize("is_meme", [True, False])
@pytest.mark.parametrize("mutation", ["edit", "delete", "reinsert"])
async def test_reanalysis_discards_result_after_api_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    is_meme: bool,
    mutation: str,
) -> None:
    ai = _ControlledAI(is_meme=is_meme)
    service, store, vectors, original = await _fixture(tmp_path, ai)
    # Same-second edits must still invalidate the old analysis.
    monkeypatch.setattr("Undefined.memes.service._now_iso", lambda: original.updated_at)
    task = asyncio.create_task(
        service.process_job({"kind": "reanalyze", "uid": original.uid})
    )
    try:
        await asyncio.wait_for(ai.entered.wait(), timeout=3)
        if mutation == "edit":
            response = await meme_update_handler(
                _context(service),
                _request(
                    original.uid,
                    {
                        "manual_description": "new manual",
                        "tags": ["new tag"],
                        "aliases": ["new alias"],
                        "enabled": False,
                        "pinned": True,
                    },
                ),
            )
            assert response.status == 200
            edited = await store.get(original.uid)
            assert edited is not None
            assert edited.updated_at == original.updated_at
            assert edited.revision > original.revision
        else:
            response = await meme_delete_handler(
                _context(service), _request(original.uid)
            )
            assert response.status == 200
            assert not Path(original.blob_path).exists()
            if mutation == "reinsert":
                Path(original.blob_path).write_bytes(b"isolated image")
                inserted = await store.upsert_record(
                    replace(original, manual_description="new incarnation")
                )
                await vectors.upsert(inserted)
                assert inserted.revision == original.revision
                assert inserted.generation != original.generation
        before = await store.get(original.uid)
        vector_before = vectors.records.get(original.uid)
        ai.release.set()
        await asyncio.wait_for(task, timeout=3)
        assert await store.get(original.uid) == before
        assert vectors.records.get(original.uid) == vector_before
        assert Path(original.blob_path).exists() == (mutation != "delete")
        assert service._ingest_digest_locks == {}
    finally:
        ai.release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["analysis", "commit"])
async def test_reanalysis_preserves_concurrent_usage_without_discarding_description(
    tmp_path: Path, phase: str
) -> None:
    entered = asyncio.Event()
    release = asyncio.Event()

    class _ControlledStore(MemeStore):
        async def update_fields(
            self,
            uid: str,
            values: dict[str, Any],
            *,
            expected_record: MemeRecord | None = None,
        ) -> MemeRecord | None:
            if phase == "commit" and "auto_description" in values:
                entered.set()
                await release.wait()
            return await super().update_fields(
                uid, values, expected_record=expected_record
            )

    ai = _ControlledAI()
    service, store, vectors, original = await _fixture(
        tmp_path, ai, store=_ControlledStore(tmp_path / "memes.sqlite3")
    )
    task = asyncio.create_task(
        service.process_job({"kind": "reanalyze", "uid": original.uid})
    )
    try:
        await asyncio.wait_for(ai.entered.wait(), timeout=3)
        if phase == "commit":
            ai.release.set()
            await asyncio.wait_for(entered.wait(), timeout=3)
        used_at = "2026-10-06T12:00:02"
        used = await store.increment_use(original.uid, used_at)
        assert used is not None and used.revision == original.revision
        ai.release.set()
        release.set()
        await asyncio.wait_for(task, timeout=3)
        saved = await store.get(original.uid)
        assert saved is not None
        assert saved.auto_description == "generated description"
        assert saved.tags == ["generated"]
        assert saved.manual_description == original.manual_description
        assert saved.aliases == original.aliases
        assert saved.use_count == 8
        assert saved.last_used_at == used_at
        assert vectors.records[original.uid] == saved
    finally:
        ai.release.set()
        release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["edit", "delete"])
async def test_cancelled_reanalysis_finishes_index_before_following_api_mutation(
    tmp_path: Path, mutation: str
) -> None:
    ai = _ControlledAI()
    ai.release.set()
    service, store, vectors, original = await _fixture(tmp_path, ai)
    vectors.block_analysis = True
    analysis = asyncio.create_task(
        service.process_job({"kind": "reanalyze", "uid": original.uid})
    )
    following: asyncio.Task[web.Response] | None = None
    try:
        await asyncio.wait_for(vectors.entered.wait(), timeout=3)
        analysis.cancel()
        if mutation == "edit":
            following = asyncio.create_task(
                meme_update_handler(
                    _context(service),
                    _request(original.uid, {"manual_description": "new manual"}),
                )
            )
        else:
            following = asyncio.create_task(
                meme_delete_handler(_context(service), _request(original.uid))
            )
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        analysis.cancel()
        assert not analysis.done()
        assert not following.done()
        vectors.release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(analysis, timeout=3)
        response = await asyncio.wait_for(following, timeout=3)
        assert response.status == 200
        saved = await store.get(original.uid)
        if mutation == "edit":
            assert saved is not None and saved.manual_description == "new manual"
            assert vectors.records[original.uid] == saved
        else:
            assert saved is None
            assert original.uid not in vectors.records
            assert not Path(original.blob_path).exists()
        assert service._ingest_digest_locks == {}
    finally:
        vectors.release.set()
        await asyncio.gather(
            analysis, *([following] if following else []), return_exceptions=True
        )


@pytest.mark.asyncio
async def test_existing_meme_database_migrates_identity_and_guards_stale_writes(
    tmp_path: Path,
) -> None:
    path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(path) as conn:
        conn.execute("""
            CREATE TABLE memes (
                uid TEXT PRIMARY KEY, content_sha256 TEXT NOT NULL,
                blob_path TEXT NOT NULL, preview_path TEXT, mime_type TEXT NOT NULL,
                file_size INTEGER NOT NULL, width INTEGER, height INTEGER,
                is_animated INTEGER NOT NULL DEFAULT 0, enabled INTEGER NOT NULL DEFAULT 1,
                pinned INTEGER NOT NULL DEFAULT 0, auto_description TEXT NOT NULL DEFAULT '',
                manual_description TEXT NOT NULL DEFAULT '', ocr_text TEXT NOT NULL DEFAULT '',
                tags_json TEXT NOT NULL DEFAULT '[]', aliases_json TEXT NOT NULL DEFAULT '[]',
                search_text TEXT NOT NULL DEFAULT '', use_count INTEGER NOT NULL DEFAULT 0,
                last_used_at TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'ready',
                segment_data_json TEXT NOT NULL DEFAULT '{}'
            )
        """)
        conn.execute(
            "INSERT INTO memes(uid, content_sha256, blob_path, mime_type, file_size, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "pic_legacy",
                "digest",
                str(tmp_path / "legacy.png"),
                "image/png",
                1,
                "same second",
                "same second",
            ),
        )
    store = MemeStore(path)
    original = await store.get("pic_legacy")
    assert original is not None and original.revision == 0 and original.generation
    reopened = MemeStore(path)
    assert await reopened.get(original.uid) == original
    changed = await store.update_fields(
        original.uid,
        {
            "manual_description": "fresh",
            "search_text": "fresh",
            "updated_at": original.updated_at,
        },
    )
    assert changed is not None and changed.revision == 1
    assert changed.generation == original.generation
    assert (
        await store.update_fields(
            original.uid, {"search_text": "stale"}, expected_record=original
        )
        is None
    )
    assert await store.delete(original.uid, expected_record=original) is None
    assert await store.get(original.uid) == changed
    assert (await store.search_keyword("fresh", limit=5))[0][
        "record"
    ].uid == original.uid


@pytest.mark.asyncio
@pytest.mark.parametrize("old_is_meme", [True, False])
async def test_stale_gif_analysis_only_cleans_its_own_frames(
    tmp_path: Path, old_is_meme: bool
) -> None:
    entered = [asyncio.Event(), asyncio.Event()]
    release = [asyncio.Event(), asyncio.Event()]
    inputs: list[list[str]] = []

    class _ConcurrentAI:
        async def judge_meme_image(self, paths: list[str]) -> dict[str, Any]:
            index = len(inputs)
            inputs.append(paths)
            entered[index].set()
            await release[index].wait()
            assert all(Path(path).is_file() for path in paths)
            return {"is_meme": old_is_meme if index == 0 else True}

        async def describe_meme_image(self, paths: list[str]) -> dict[str, Any]:
            assert all(Path(path).is_file() for path in paths)
            return {"description": "generated description", "tags": ["generated"]}

    service, store, vectors, original = await _fixture(tmp_path, _ControlledAI())
    gif = tmp_path / "meme.gif"
    first = Image.new("RGBA", (2, 2), "red")
    second = Image.new("RGBA", (2, 2), "blue")
    first.save(gif, format="GIF", save_all=True, append_images=[second], duration=100)
    first.close()
    second.close()
    record = await store.upsert_record(
        replace(original, blob_path=str(gif), preview_path=None, is_animated=True)
    )
    config = _config(tmp_path)
    config.gif_analysis_mode = "multi"
    service._config_getter = lambda: config
    service._ai_client = _ConcurrentAI()
    old = asyncio.create_task(
        service.process_job({"kind": "reanalyze", "uid": record.uid})
    )
    new: asyncio.Task[None] | None = None
    try:
        await asyncio.wait_for(entered[0].wait(), timeout=3)
        response = await meme_update_handler(
            _context(service),
            _request(record.uid, {"manual_description": "new manual"}),
        )
        assert response.status == 200
        new = asyncio.create_task(
            service.process_job({"kind": "reanalyze", "uid": record.uid})
        )
        await asyncio.wait_for(entered[1].wait(), timeout=3)
        assert not set(inputs[0]) & set(inputs[1])
        release[0].set()
        await asyncio.wait_for(old, timeout=3)
        assert not any(Path(path).exists() for path in inputs[0])
        assert all(Path(path).is_file() for path in inputs[1])
        assert not new.done()
        release[1].set()
        await asyncio.wait_for(new, timeout=3)
        saved = await store.get(record.uid)
        assert saved is not None
        assert saved.manual_description == "new manual"
        assert saved.auto_description == "generated description"
        assert vectors.records[record.uid] == saved
        assert gif.is_file()
        assert not list(Path(config.preview_dir).glob("*_f*.png"))
    finally:
        for event in release:
            event.set()
        await asyncio.gather(old, *([new] if new else []), return_exceptions=True)


@pytest.mark.asyncio
async def test_cancelled_gif_frame_creation_waits_for_thread_before_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ai = _ControlledAI()
    service, store, _vectors, original = await _fixture(tmp_path, ai)
    gif = tmp_path / "meme.gif"
    image = Image.new("RGBA", (2, 2), "red")
    image.save(gif, format="GIF")
    image.close()
    record = await store.upsert_record(
        replace(original, blob_path=str(gif), preview_path=None, is_animated=True)
    )
    config = _config(tmp_path)
    config.gif_analysis_mode = "multi"
    service._config_getter = lambda: config
    entered = threading.Event()
    release = threading.Event()

    def controlled_extract(source: Path, frames: int) -> list[Image.Image]:
        entered.set()
        assert release.wait(timeout=5)
        return extract_gif_frames(source, frames)

    monkeypatch.setattr(
        "Undefined.memes.service._extract_gif_frames", controlled_extract
    )
    task = asyncio.create_task(
        service.process_job({"kind": "reanalyze", "uid": record.uid})
    )
    try:
        assert await asyncio.to_thread(entered.wait, 3)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=3)
        assert await store.get(record.uid) == record
        assert gif.is_file()
        assert not list(Path(config.preview_dir).glob("*_f*.png"))
        assert not ai.entered.is_set()
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("is_meme", [True, False])
async def test_current_reanalysis_applies_positive_or_negative_result(
    tmp_path: Path, is_meme: bool
) -> None:
    ai = _ControlledAI(is_meme=is_meme)
    ai.release.set()
    service, store, vectors, original = await _fixture(tmp_path, ai)
    await service.process_job({"kind": "reanalyze", "uid": original.uid})
    saved = await store.get(original.uid)
    if is_meme:
        assert saved is not None and saved.auto_description == "generated description"
        assert vectors.records[original.uid] == saved
    else:
        assert saved is None
        assert original.uid not in vectors.records
        assert not Path(original.blob_path).exists()
