"""测试 handlers.py 中的表情包自动匹配功能"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from Undefined.attachments import AttachmentRecord, AttachmentRegistry


@pytest.mark.asyncio
async def test_annotate_meme_descriptions_success(tmp_path: Path) -> None:
    """测试成功匹配表情包时添加描述"""
    # 创建 mock handler
    handler = MagicMock()

    # 设置 attachment registry
    registry_path = tmp_path / "registry.json"
    cache_dir = tmp_path / "cache"
    attachment_registry = AttachmentRegistry(
        registry_path=registry_path, cache_dir=cache_dir
    )

    # 添加一个附件记录
    test_sha256 = "abc123def456"
    attachment_record = AttachmentRecord(
        uid="pic_001",
        scope_key="group:10001",
        kind="image",
        media_type="image/png",
        display_name="test.png",
        source_kind="test",
        source_ref="",
        local_path=None,
        mime_type="image/png",
        sha256=test_sha256,
        created_at="2024-01-01T00:00:00Z",
        segment_data={},
    )
    attachment_registry._records["pic_001"] = attachment_record

    # 设置 meme service mock
    mock_meme_record = MagicMock()
    mock_meme_record.description = "可爱的猫猫"

    mock_meme_store = MagicMock()
    mock_meme_store.find_by_sha256 = AsyncMock(return_value=mock_meme_record)

    mock_meme_service = MagicMock()
    mock_meme_service.enabled = True
    mock_meme_service._store = mock_meme_store

    ai = MagicMock()
    ai.attachment_registry = attachment_registry
    ai._meme_service = mock_meme_service

    handler.ai = ai

    # 导入实现
    from Undefined.handlers import MessageHandler

    # 测试输入
    input_attachments = [
        {"uid": "pic_001", "kind": "image"},
        {"uid": "file_002", "kind": "file"},
    ]

    # 调用函数
    result = await MessageHandler._annotate_meme_descriptions(
        handler, input_attachments, "group:10001"
    )

    # 验证结果
    assert len(result) == 2
    # 第一个附件应该有表情包描述
    assert result[0]["uid"] == "pic_001"
    assert result[0]["description"] == "[表情包] 可爱的猫猫"
    # 第二个附件不应该被修改
    assert result[1]["uid"] == "file_002"
    assert "description" not in result[1]


@pytest.mark.asyncio
async def test_annotate_meme_descriptions_no_match(tmp_path: Path) -> None:
    """测试没有匹配表情包时返回原始列表"""
    handler = MagicMock()

    registry_path = tmp_path / "registry.json"
    cache_dir = tmp_path / "cache"
    attachment_registry = AttachmentRegistry(
        registry_path=registry_path, cache_dir=cache_dir
    )

    test_sha256 = "xyz789"
    attachment_record = AttachmentRecord(
        uid="pic_001",
        scope_key="group:10001",
        kind="image",
        media_type="image/png",
        display_name="test.png",
        source_kind="test",
        source_ref="",
        local_path=None,
        mime_type="image/png",
        sha256=test_sha256,
        created_at="2024-01-01T00:00:00Z",
        segment_data={},
    )
    attachment_registry._records["pic_001"] = attachment_record

    # meme store 返回 None（没找到）
    mock_meme_store = MagicMock()
    mock_meme_store.find_by_sha256 = AsyncMock(return_value=None)

    mock_meme_service = MagicMock()
    mock_meme_service.enabled = True
    mock_meme_service._store = mock_meme_store

    ai = MagicMock()
    ai.attachment_registry = attachment_registry
    ai._meme_service = mock_meme_service

    handler.ai = ai

    from Undefined.handlers import MessageHandler

    input_attachments = [{"uid": "pic_001", "kind": "image"}]

    result = await MessageHandler._annotate_meme_descriptions(
        handler, input_attachments, "group:10001"
    )

    # 应该返回原始列表
    assert len(result) == 1
    assert result[0]["uid"] == "pic_001"
    assert "description" not in result[0]


@pytest.mark.asyncio
async def test_annotate_meme_descriptions_meme_disabled() -> None:
    """测试 meme service 禁用时返回原始列表"""
    handler = MagicMock()

    # meme service 禁用
    mock_meme_service = MagicMock()
    mock_meme_service.enabled = False

    ai = MagicMock()
    ai._meme_service = mock_meme_service

    handler.ai = ai

    from Undefined.handlers import MessageHandler

    input_attachments = [{"uid": "pic_001", "kind": "image"}]

    result = await MessageHandler._annotate_meme_descriptions(
        handler, input_attachments, "group:10001"
    )

    # 应该返回原始列表
    assert result == input_attachments


@pytest.mark.asyncio
async def test_annotate_meme_descriptions_error_handling() -> None:
    """测试异常处理：失败时返回原始列表"""
    handler = MagicMock()

    # 设置会抛出异常的 attachment registry
    mock_attachment_registry = MagicMock()
    mock_attachment_registry.resolve = MagicMock(
        side_effect=Exception("Registry error")
    )

    # 设置 meme service
    mock_meme_store = MagicMock()
    mock_meme_store.find_by_sha256 = AsyncMock(side_effect=Exception("Database error"))

    mock_meme_service = MagicMock()
    mock_meme_service.enabled = True
    mock_meme_service._store = mock_meme_store

    ai = MagicMock()
    ai.attachment_registry = mock_attachment_registry
    ai._meme_service = mock_meme_service

    handler.ai = ai

    from Undefined.handlers import MessageHandler

    input_attachments = [{"uid": "pic_001", "kind": "image"}]

    result = await MessageHandler._annotate_meme_descriptions(
        handler, input_attachments, "group:10001"
    )

    # 应该返回原始列表（异常被捕获）
    assert result == input_attachments


@pytest.mark.asyncio
async def test_annotate_meme_descriptions_batch_query(tmp_path: Path) -> None:
    """测试批量查询：多个附件共享同一个哈希值"""
    handler = MagicMock()

    registry_path = tmp_path / "registry.json"
    cache_dir = tmp_path / "cache"
    attachment_registry = AttachmentRegistry(
        registry_path=registry_path, cache_dir=cache_dir
    )

    # 两个附件，相同的 SHA256
    shared_sha256 = "shared123"
    for uid in ["pic_001", "pic_002"]:
        record = AttachmentRecord(
            uid=uid,
            scope_key="group:10001",
            kind="image",
            media_type="image/png",
            display_name=f"{uid}.png",
            source_kind="test",
            source_ref="",
            local_path=None,
            mime_type="image/png",
            sha256=shared_sha256,
            created_at="2024-01-01T00:00:00Z",
            segment_data={},
        )
        attachment_registry._records[uid] = record

    # 记录 find_by_sha256 被调用的次数
    call_count = 0

    async def mock_find_by_sha256(sha: str) -> Any:
        nonlocal call_count
        call_count += 1
        if sha == shared_sha256:
            meme = MagicMock()
            meme.description = "共享表情包"
            return meme
        return None

    mock_meme_store = MagicMock()
    mock_meme_store.find_by_sha256 = mock_find_by_sha256

    mock_meme_service = MagicMock()
    mock_meme_service.enabled = True
    mock_meme_service._store = mock_meme_store

    ai = MagicMock()
    ai.attachment_registry = attachment_registry
    ai._meme_service = mock_meme_service

    handler.ai = ai

    from Undefined.handlers import MessageHandler

    input_attachments = [
        {"uid": "pic_001", "kind": "image"},
        {"uid": "pic_002", "kind": "image"},
    ]

    result = await MessageHandler._annotate_meme_descriptions(
        handler, input_attachments, "group:10001"
    )

    # 验证结果
    assert len(result) == 2
    assert result[0]["description"] == "[表情包] 共享表情包"
    assert result[1]["description"] == "[表情包] 共享表情包"

    # 验证 find_by_sha256 只被调用一次（批量查询去重）
    assert call_count == 1
