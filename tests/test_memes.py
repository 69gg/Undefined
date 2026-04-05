from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from PIL import Image

from Undefined.attachments import (
    AttachmentRecord,
    AttachmentRegistry,
    render_message_with_pic_placeholders,
)
from Undefined.memes import MemeService, MemeStore, MemeVectorStore
from Undefined.memes.models import MemeRecord


def _meme_config(tmp_path: Path) -> Any:
    return SimpleNamespace(
        enabled=True,
        query_default_mode="hybrid",
        blob_dir=str(tmp_path / "blobs"),
        preview_dir=str(tmp_path / "previews"),
        db_path=str(tmp_path / "memes.sqlite3"),
        vector_store_path=str(tmp_path / "chromadb"),
        queue_path=str(tmp_path / "queues"),
        max_items=10000,
        max_total_bytes=5 * 1024 * 1024 * 1024,
        allow_gif=True,
        auto_ingest_group=True,
        auto_ingest_private=True,
        max_source_image_bytes=1024 * 1024,
        keyword_top_k=30,
        semantic_top_k=30,
        rerank_top_k=20,
    )


def _write_test_png(path: Path) -> None:
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + bytes.fromhex(
            "0000000d49484452000000010000000108060000001f15c489"
            "0000000a49444154789c6360000000020001e221bc330000000049454e44ae426082"
        )
    )


def _write_test_gif(path: Path) -> None:
    first = Image.new("RGBA", (1, 1), (255, 0, 0, 255))
    second = Image.new("RGBA", (1, 1), (0, 255, 0, 255))
    first.save(
        path,
        format="GIF",
        save_all=True,
        append_images=[second],
        loop=0,
        duration=100,
    )


@pytest.mark.asyncio
async def test_render_message_with_global_meme_uid_supports_subtype(
    tmp_path: Path,
) -> None:
    blob = tmp_path / "meme.png"
    blob.write_bytes(b"\x89PNG\r\n\x1a\n")
    registry = AttachmentRegistry(
        registry_path=tmp_path / "attachment_registry.json",
        cache_dir=tmp_path / "attachments",
    )
    registry.set_global_image_resolver(
        lambda uid: (
            AttachmentRecord(
                uid=uid,
                scope_key="",
                kind="image",
                media_type="image",
                display_name="meme.png",
                source_kind="meme_library",
                source_ref=blob.resolve().as_uri(),
                local_path=str(blob),
                mime_type="image/png",
                sha256="deadbeef",
                created_at="2026-04-03T12:00:00",
                segment_data={"subType": "1"},
            )
            if uid == "pic_global01"
            else None
        )
    )

    rendered = await render_message_with_pic_placeholders(
        'hello\n<pic uid="pic_global01"/>',
        registry=registry,
        scope_key="group:123",
        strict=True,
    )

    assert (
        rendered.delivery_text
        == f"hello\n[CQ:image,file={blob.resolve().as_uri()},subType=1]"
    )
    assert rendered.history_text == "hello\n[图片 uid=pic_global01 name=meme.png]"


@pytest.mark.asyncio
async def test_meme_service_search_and_send(tmp_path: Path) -> None:
    blob = tmp_path / "pic_deadbeef.png"
    blob.write_bytes(b"\x89PNG\r\n\x1a\n")
    config = _meme_config(tmp_path)
    store = MemeStore(config.db_path)
    vector_store = MemeVectorStore(config.vector_store_path, None)
    service = MemeService(
        config_getter=lambda: config,
        store=store,
        vector_store=vector_store,
    )
    await store.upsert_record(
        MemeRecord(
            uid="pic_deadbeef",
            content_sha256="sha256",
            blob_path=str(blob),
            preview_path=str(blob),
            mime_type="image/png",
            file_size=blob.stat().st_size,
            width=100,
            height=100,
            is_animated=False,
            enabled=True,
            pinned=False,
            auto_description="一只无语的猫猫表情包",
            manual_description="",
            ocr_text="无语",
            tags=["无语", "猫猫"],
            aliases=["猫咪无语"],
            search_text="一只无语的猫猫表情包 无语 猫猫 猫咪无语",
            use_count=0,
            last_used_at="",
            created_at="2026-04-03T12:00:00",
            updated_at="2026-04-03T12:00:00",
            status="ready",
            segment_data={"subType": "1"},
        )
    )

    search_payload = await service.search_memes("无语 猫猫", top_k=5)
    assert search_payload["count"] == 1
    assert search_payload["items"][0]["uid"] == "pic_deadbeef"

    sender = SimpleNamespace(
        send_group_message=AsyncMock(return_value=778899),
        send_private_message=AsyncMock(),
    )
    result = await service.send_meme_by_uid(
        "pic_deadbeef",
        {
            "request_type": "group",
            "group_id": 12345,
            "sender": sender,
        },
    )

    assert result == "表情包已发送（message_id=778899）"
    sender.send_group_message.assert_awaited_once()
    sent_message = sender.send_group_message.await_args.args[1]
    assert sent_message == f"[CQ:image,file={blob.resolve().as_uri()},subType=1]"


@pytest.mark.asyncio
async def test_search_memes_keyword_mode_skips_semantic_query(tmp_path: Path) -> None:
    config = _meme_config(tmp_path)
    record = MemeRecord(
        uid="pic_keyword01",
        content_sha256="sha256",
        blob_path=str(tmp_path / "blob.png"),
        preview_path=None,
        mime_type="image/png",
        file_size=1,
        width=1,
        height=1,
        is_animated=False,
        enabled=True,
        pinned=False,
        auto_description="无语猫猫",
        manual_description="",
        ocr_text="",
        tags=["无语"],
        aliases=["猫猫"],
        search_text="无语猫猫 无语 猫猫",
        use_count=0,
        last_used_at="",
        created_at="2026-04-03T12:00:00",
        updated_at="2026-04-03T12:00:00",
        status="ready",
        segment_data={"subType": "1"},
    )
    fake_store = SimpleNamespace(
        search_keyword=AsyncMock(
            return_value=[{"record": record, "keyword_score": 0.9}]
        ),
        get=AsyncMock(return_value=record),
    )
    fake_vector = SimpleNamespace(query=AsyncMock(return_value=[]))
    service = MemeService(
        config_getter=lambda: config,
        store=cast(Any, fake_store),
        vector_store=cast(Any, fake_vector),
    )

    payload = await service.search_memes(
        "",
        query_mode="keyword",
        keyword_query="无语",
        top_k=5,
    )

    assert payload["query_mode"] == "keyword"
    assert payload["count"] == 1
    fake_store.search_keyword.assert_awaited_once()
    fake_vector.query.assert_not_awaited()


@pytest.mark.asyncio
async def test_search_memes_semantic_mode_skips_keyword_query(tmp_path: Path) -> None:
    config = _meme_config(tmp_path)
    record = MemeRecord(
        uid="pic_semantic01",
        content_sha256="sha256",
        blob_path=str(tmp_path / "blob.png"),
        preview_path=None,
        mime_type="image/png",
        file_size=1,
        width=1,
        height=1,
        is_animated=False,
        enabled=True,
        pinned=False,
        auto_description="震惊猫猫",
        manual_description="",
        ocr_text="",
        tags=["震惊"],
        aliases=[],
        search_text="震惊猫猫 震惊",
        use_count=0,
        last_used_at="",
        created_at="2026-04-03T12:00:00",
        updated_at="2026-04-03T12:00:00",
        status="ready",
        segment_data={"subType": "1"},
    )
    fake_store = SimpleNamespace(
        search_keyword=AsyncMock(return_value=[]),
        get=AsyncMock(return_value=record),
    )
    fake_vector = SimpleNamespace(
        query=AsyncMock(
            return_value=[
                {
                    "uid": "pic_semantic01",
                    "document": "震惊猫猫 震惊",
                    "metadata": {"uid": "pic_semantic01"},
                    "distance": 0.1,
                    "semantic_score": 0.9,
                }
            ]
        )
    )
    service = MemeService(
        config_getter=lambda: config,
        store=cast(Any, fake_store),
        vector_store=cast(Any, fake_vector),
    )

    payload = await service.search_memes(
        "",
        query_mode="semantic",
        semantic_query="很震惊的猫猫反应图",
        top_k=5,
    )

    assert payload["query_mode"] == "semantic"
    assert payload["count"] == 1
    fake_vector.query.assert_awaited_once()
    fake_store.search_keyword.assert_not_awaited()


@pytest.mark.asyncio
async def test_meme_store_search_keyword_supports_chinese_fts_queries(
    tmp_path: Path,
) -> None:
    store = MemeStore(tmp_path / "memes.sqlite3")
    await store.upsert_record(
        MemeRecord(
            uid="pic_keyword_zh",
            content_sha256="sha256-zh",
            blob_path=str(tmp_path / "blob.png"),
            preview_path=None,
            mime_type="image/png",
            file_size=1,
            width=1,
            height=1,
            is_animated=False,
            enabled=True,
            pinned=False,
            auto_description="无语，猫猫",
            manual_description="",
            ocr_text="",
            tags=[],
            aliases=[],
            search_text="无语，猫猫",
            use_count=0,
            last_used_at="",
            created_at="2026-04-03T12:00:00",
            updated_at="2026-04-03T12:00:00",
            status="ready",
            segment_data={"subType": "1"},
        )
    )

    hits = await store.search_keyword("无语 猫猫", limit=5)

    assert [item["record"].uid for item in hits] == ["pic_keyword_zh"]


@pytest.mark.asyncio
async def test_meme_store_list_memes_escapes_like_wildcards(
    tmp_path: Path,
) -> None:
    store = MemeStore(tmp_path / "memes.sqlite3")
    await store.upsert_record(
        MemeRecord(
            uid="pic_literal_percent",
            content_sha256="sha256-literal",
            blob_path=str(tmp_path / "literal.png"),
            preview_path=None,
            mime_type="image/png",
            file_size=1,
            width=1,
            height=1,
            is_animated=False,
            enabled=True,
            pinned=False,
            auto_description="命中 100% 的猫猫",
            manual_description="",
            ocr_text="",
            tags=[],
            aliases=[],
            search_text="命中 100% 的猫猫",
            use_count=0,
            last_used_at="",
            created_at="2026-04-03T12:00:00",
            updated_at="2026-04-03T12:00:00",
            status="ready",
            segment_data={"subType": "1"},
        )
    )
    await store.upsert_record(
        MemeRecord(
            uid="pic_wildcard_other",
            content_sha256="sha256-other",
            blob_path=str(tmp_path / "other.png"),
            preview_path=None,
            mime_type="image/png",
            file_size=1,
            width=1,
            height=1,
            is_animated=False,
            enabled=True,
            pinned=False,
            auto_description="命中 1000 的猫猫",
            manual_description="",
            ocr_text="",
            tags=[],
            aliases=[],
            search_text="命中 1000 的猫猫",
            use_count=0,
            last_used_at="",
            created_at="2026-04-03T12:00:00",
            updated_at="2026-04-03T12:00:00",
            status="ready",
            segment_data={"subType": "1"},
        )
    )

    items, total = await store.list_memes(query="100%")

    assert total == 1
    assert [item.uid for item in items] == ["pic_literal_percent"]


@pytest.mark.asyncio
async def test_meme_ingest_pipeline_uses_two_stage_llm_and_skips_on_judge_failure(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.png"
    _write_test_png(source)
    config = _meme_config(tmp_path)
    store = MemeStore(config.db_path)
    vector_store = MemeVectorStore(config.vector_store_path, None)
    attachment_registry = AttachmentRegistry(
        registry_path=tmp_path / "attachment_registry.json",
        cache_dir=tmp_path / "attachments",
    )
    await attachment_registry.register_local_file(
        "group:10001",
        source,
        kind="image",
        source_kind="test",
        display_name="source.png",
    )
    attachment = next(iter(attachment_registry._records.values()))

    ai_client = SimpleNamespace(
        judge_meme_image=AsyncMock(side_effect=RuntimeError("judge boom")),
        describe_meme_image=AsyncMock(),
    )
    service = MemeService(
        config_getter=lambda: config,
        store=store,
        vector_store=vector_store,
        ai_client=ai_client,
        attachment_registry=attachment_registry,
    )

    await service.process_job(
        {
            "kind": "ingest",
            "attachment_uid": attachment.uid,
            "scope_key": "group:10001",
            "chat_type": "group",
            "chat_id": "10001",
            "sender_id": "20002",
            "message_id": "30003",
        }
    )

    payload = await store.list_memes()
    assert payload[1] == 0
    ai_client.describe_meme_image.assert_not_awaited()


@pytest.mark.asyncio
async def test_meme_ingest_pipeline_describes_only_after_positive_judge(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.png"
    _write_test_png(source)
    config = _meme_config(tmp_path)
    store = MemeStore(config.db_path)
    vector_store = MemeVectorStore(config.vector_store_path, None)
    attachment_registry = AttachmentRegistry(
        registry_path=tmp_path / "attachment_registry.json",
        cache_dir=tmp_path / "attachments",
    )
    await attachment_registry.register_local_file(
        "group:10001",
        source,
        kind="image",
        source_kind="test",
        display_name="source.png",
    )
    attachment = next(iter(attachment_registry._records.values()))

    ai_client = SimpleNamespace(
        judge_meme_image=AsyncMock(
            return_value={"is_meme": True, "confidence": 0.98, "reason": "反应图"}
        ),
        describe_meme_image=AsyncMock(
            return_value={"description": "无语猫猫反应图", "tags": ["无语", "猫猫"]}
        ),
    )
    service = MemeService(
        config_getter=lambda: config,
        store=store,
        vector_store=vector_store,
        ai_client=ai_client,
        attachment_registry=attachment_registry,
    )

    await service.process_job(
        {
            "kind": "ingest",
            "attachment_uid": attachment.uid,
            "scope_key": "group:10001",
            "chat_type": "group",
            "chat_id": "10001",
            "sender_id": "20002",
            "message_id": "30003",
        }
    )

    items, total = await store.list_memes()
    assert total == 1
    assert items[0].auto_description == "无语猫猫反应图"
    assert items[0].tags == ["无语", "猫猫"]
    assert items[0].ocr_text == ""


@pytest.mark.asyncio
async def test_meme_ingest_rolls_back_record_when_vector_upsert_fails(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.png"
    _write_test_png(source)
    config = _meme_config(tmp_path)
    store = MemeStore(config.db_path)
    attachment_registry = AttachmentRegistry(
        registry_path=tmp_path / "attachment_registry.json",
        cache_dir=tmp_path / "attachments",
    )
    await attachment_registry.register_local_file(
        "group:10001",
        source,
        kind="image",
        source_kind="test",
        display_name="source.png",
    )
    attachment = next(iter(attachment_registry._records.values()))

    ai_client = SimpleNamespace(
        judge_meme_image=AsyncMock(return_value={"is_meme": True}),
        describe_meme_image=AsyncMock(
            return_value={"description": "无语猫猫反应图", "tags": ["无语", "猫猫"]}
        ),
    )
    vector_store = SimpleNamespace(
        upsert=AsyncMock(side_effect=[RuntimeError("vector boom"), None]),
        delete=AsyncMock(return_value=None),
    )
    service = MemeService(
        config_getter=lambda: config,
        store=store,
        vector_store=cast(Any, vector_store),
        ai_client=ai_client,
        attachment_registry=attachment_registry,
    )
    job = {
        "kind": "ingest",
        "attachment_uid": attachment.uid,
        "scope_key": "group:10001",
        "chat_type": "group",
        "chat_id": "10001",
        "sender_id": "20002",
        "message_id": "30003",
    }

    with pytest.raises(RuntimeError, match="vector boom"):
        await service.process_job(job)

    first_pass_items, first_pass_total = await store.list_memes()
    assert first_pass_total == 0
    assert first_pass_items == []
    vector_store.delete.assert_awaited_once()

    await service.process_job(job)

    second_pass_items, second_pass_total = await store.list_memes()
    assert second_pass_total == 1
    assert second_pass_items[0].auto_description == "无语猫猫反应图"
    assert Path(second_pass_items[0].blob_path).is_file()


@pytest.mark.asyncio
async def test_meme_ingest_serializes_same_sha256_jobs(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.png"
    _write_test_png(source)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    config = _meme_config(tmp_path)
    store = MemeStore(config.db_path)
    attachment_registry = AttachmentRegistry(
        registry_path=tmp_path / "attachment_registry.json",
        cache_dir=tmp_path / "attachments",
    )
    await attachment_registry.register_local_file(
        "group:10001",
        source,
        kind="image",
        source_kind="test",
        display_name="source.png",
    )
    attachment = next(iter(attachment_registry._records.values()))
    first_judge_started = asyncio.Event()
    release_first_judge = asyncio.Event()
    judge_call_count = 0

    async def _judge_image(_path: str) -> dict[str, bool]:
        nonlocal judge_call_count
        judge_call_count += 1
        if judge_call_count == 1:
            first_judge_started.set()
            await release_first_judge.wait()
        return {"is_meme": True}

    ai_client = SimpleNamespace(
        judge_meme_image=AsyncMock(side_effect=_judge_image),
        describe_meme_image=AsyncMock(
            return_value={"description": "无语猫猫反应图", "tags": ["无语", "猫猫"]}
        ),
    )
    vector_store = SimpleNamespace(
        upsert=AsyncMock(return_value=None),
        delete=AsyncMock(return_value=None),
    )
    service = MemeService(
        config_getter=lambda: config,
        store=store,
        vector_store=cast(Any, vector_store),
        ai_client=ai_client,
        attachment_registry=attachment_registry,
    )
    job = {
        "kind": "ingest",
        "attachment_uid": attachment.uid,
        "scope_key": "group:10001",
        "chat_type": "group",
        "chat_id": "10001",
        "sender_id": "20002",
        "message_id": "30003",
    }

    first_task = asyncio.create_task(service.process_job(job))
    await first_judge_started.wait()
    second_task = asyncio.create_task(service.process_job(job))
    await asyncio.sleep(0.05)

    assert judge_call_count == 1

    release_first_judge.set()
    await asyncio.gather(first_task, second_task)

    items, total = await store.list_memes()
    assert total == 1
    assert items[0].auto_description == "无语猫猫反应图"
    assert ai_client.describe_meme_image.await_count == 1
    assert digest not in service._ingest_digest_locks


@pytest.mark.asyncio
async def test_meme_ingest_replaces_orphaned_sha256_record(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.png"
    _write_test_png(source)
    config = _meme_config(tmp_path)
    store = MemeStore(config.db_path)
    attachment_registry = AttachmentRegistry(
        registry_path=tmp_path / "attachment_registry.json",
        cache_dir=tmp_path / "attachments",
    )
    await attachment_registry.register_local_file(
        "group:10001",
        source,
        kind="image",
        source_kind="test",
        display_name="source.png",
    )
    attachment = next(iter(attachment_registry._records.values()))
    orphan_blob = tmp_path / "missing.png"
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    await store.upsert_record(
        MemeRecord(
            uid="pic_orphan01",
            content_sha256=digest,
            blob_path=str(orphan_blob),
            preview_path=None,
            mime_type="image/png",
            file_size=1,
            width=1,
            height=1,
            is_animated=False,
            enabled=True,
            pinned=False,
            auto_description="旧记录",
            manual_description="",
            ocr_text="",
            tags=["旧"],
            aliases=[],
            search_text="旧记录",
            use_count=0,
            last_used_at="",
            created_at="2026-04-03T12:00:00",
            updated_at="2026-04-03T12:00:00",
            status="ready",
            segment_data={"subType": "1"},
        )
    )

    ai_client = SimpleNamespace(
        judge_meme_image=AsyncMock(return_value={"is_meme": True}),
        describe_meme_image=AsyncMock(
            return_value={"description": "无语猫猫反应图", "tags": ["无语", "猫猫"]}
        ),
    )
    vector_store = SimpleNamespace(
        upsert=AsyncMock(return_value=None),
        delete=AsyncMock(return_value=None),
    )
    service = MemeService(
        config_getter=lambda: config,
        store=store,
        vector_store=cast(Any, vector_store),
        ai_client=ai_client,
        attachment_registry=attachment_registry,
    )

    await service.process_job(
        {
            "kind": "ingest",
            "attachment_uid": attachment.uid,
            "scope_key": "group:10001",
            "chat_type": "group",
            "chat_id": "10001",
            "sender_id": "20002",
            "message_id": "30003",
        }
    )

    items, total = await store.list_memes()
    assert total == 1
    assert items[0].uid != "pic_orphan01"
    assert items[0].auto_description == "无语猫猫反应图"
    assert Path(items[0].blob_path).is_file()
    assert await store.get("pic_orphan01") is None
    vector_store.delete.assert_awaited_once_with("pic_orphan01")


@pytest.mark.asyncio
async def test_meme_ingest_cleans_partial_files_on_prepare_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.gif"
    _write_test_gif(source)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    config = _meme_config(tmp_path)
    store = MemeStore(config.db_path)
    vector_store = SimpleNamespace(
        upsert=AsyncMock(return_value=None),
        delete=AsyncMock(return_value=None),
    )
    attachment_registry = AttachmentRegistry(
        registry_path=tmp_path / "attachment_registry.json",
        cache_dir=tmp_path / "attachments",
    )
    await attachment_registry.register_local_file(
        "group:10001",
        source,
        kind="image",
        source_kind="test",
        display_name="source.gif",
    )
    attachment = next(iter(attachment_registry._records.values()))
    ai_client = SimpleNamespace(
        judge_meme_image=AsyncMock(return_value={"is_meme": True}),
        describe_meme_image=AsyncMock(
            return_value={"description": "无语猫猫反应图", "tags": ["无语", "猫猫"]}
        ),
    )
    service = MemeService(
        config_getter=lambda: config,
        store=store,
        vector_store=cast(Any, vector_store),
        ai_client=ai_client,
        attachment_registry=attachment_registry,
    )

    async def _broken_prepare(
        *,
        source_path: Path,
        target_uid: str,
        suffix: str,
        is_animated: bool,
    ) -> Path | None:
        blob_path = Path(config.blob_dir) / f"{target_uid}{suffix}"
        preview_path = Path(config.preview_dir) / f"{target_uid}.png"
        blob_path.parent.mkdir(parents=True, exist_ok=True)
        preview_path.parent.mkdir(parents=True, exist_ok=True)
        blob_path.write_bytes(source_path.read_bytes())
        preview_path.write_bytes(b"partial-preview")
        raise RuntimeError("prepare boom")

    monkeypatch.setattr(service, "_prepare_blob_and_preview", _broken_prepare)

    with pytest.raises(RuntimeError, match="prepare boom"):
        await service.process_job(
            {
                "kind": "ingest",
                "attachment_uid": attachment.uid,
                "scope_key": "group:10001",
                "chat_type": "group",
                "chat_id": "10001",
                "sender_id": "20002",
                "message_id": "30003",
            }
        )

    items, total = await store.list_memes()
    assert total == 0
    assert items == []
    assert list((tmp_path / "blobs").glob("*")) == []
    assert list((tmp_path / "previews").glob("*")) == []
    assert digest not in service._ingest_digest_locks
