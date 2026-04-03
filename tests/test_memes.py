from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

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
async def test_meme_ingest_pipeline_uses_two_stage_llm_and_skips_on_judge_failure(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.png"
    source.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + bytes.fromhex(
            "0000000d49484452000000010000000108060000001f15c489"
            "0000000a49444154789c6360000000020001e221bc330000000049454e44ae426082"
        )
    )
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
    source.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + bytes.fromhex(
            "0000000d49484452000000010000000108060000001f15c489"
            "0000000a49444154789c6360000000020001e221bc330000000049454e44ae426082"
        )
    )
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
