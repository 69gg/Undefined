"""知识库模块测试"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from Undefined.knowledge.chunker import split_lines
from Undefined.knowledge.embedder import Embedder
from Undefined.knowledge.manager import KnowledgeManager


# ── chunker ──────────────────────────────────────────────────────────────────


def test_split_lines_basic() -> None:
    text = "line1\nline2\nline3"
    assert split_lines(text) == ["line1", "line2", "line3"]


def test_split_lines_ignores_empty() -> None:
    text = "line1\n\n\nline2\n  \nline3"
    assert split_lines(text) == ["line1", "line2", "line3"]


def test_split_lines_empty_text() -> None:
    assert split_lines("") == []
    assert split_lines("   \n\n  ") == []


# ── embedder ─────────────────────────────────────────────────────────────────


def _make_embedder(batch_size: int = 3) -> tuple[Embedder, MagicMock]:
    requester = MagicMock()
    config = MagicMock()
    config.queue_interval_seconds = 0.0
    embedder = Embedder(requester, config, batch_size=batch_size)
    return embedder, requester


async def test_embedder_empty() -> None:
    embedder, _ = _make_embedder()
    result = await embedder.embed([])
    assert result == []


async def test_embedder_batching() -> None:
    embedder, requester = _make_embedder(batch_size=2)
    fake_vecs = [[float(i)] for i in range(5)]

    call_count = 0

    async def fake_embed(config: Any, texts: list[str]) -> list[list[float]]:
        nonlocal call_count
        start = call_count * 2
        result = fake_vecs[start : start + len(texts)]
        call_count += 1
        return result

    requester.embed = fake_embed
    embedder.start()

    result = await embedder.embed(["a", "b", "c", "d", "e"])
    assert len(result) == 5
    assert call_count == 3  # batches: [a,b], [c,d], [e]


async def test_embedder_queue_serializes() -> None:
    """多个并发 embed 调用应串行通过队列。"""
    embedder, requester = _make_embedder(batch_size=10)
    order: list[int] = []

    async def fake_embed(config: Any, texts: list[str]) -> list[list[float]]:
        order.append(int(texts[0]))
        return [[float(texts[0])]]

    requester.embed = fake_embed
    embedder.start()

    results = await asyncio.gather(
        embedder.embed(["1"]),
        embedder.embed(["2"]),
        embedder.embed(["3"]),
    )
    assert len(results) == 3
    assert sorted(order) == [1, 2, 3]


# ── manager ──────────────────────────────────────────────────────────────────


def _make_manager(tmp_path: Path) -> tuple[KnowledgeManager, MagicMock]:
    embedder = MagicMock(spec=Embedder)
    embedder.embed = AsyncMock(return_value=[[0.1, 0.2]])
    manager = KnowledgeManager(base_dir=tmp_path, embedder=embedder, default_top_k=3)
    return manager, embedder


def _make_kb(tmp_path: Path, name: str, files: dict[str, str]) -> Path:
    kb_dir = tmp_path / name
    texts_dir = kb_dir / "texts"
    texts_dir.mkdir(parents=True)
    for fname, content in files.items():
        (texts_dir / fname).write_text(content, "utf-8")
    return kb_dir


def test_list_knowledge_bases(tmp_path: Path) -> None:
    manager, _ = _make_manager(tmp_path)
    assert manager.list_knowledge_bases() == []

    _make_kb(tmp_path, "kb1", {"a.txt": "hello"})
    _make_kb(tmp_path, "kb2", {"b.txt": "world"})
    assert manager.list_knowledge_bases() == ["kb1", "kb2"]


def test_text_search_basic(tmp_path: Path) -> None:
    manager, _ = _make_manager(tmp_path)
    _make_kb(tmp_path, "kb1", {"doc.txt": "hello world\nfoo bar\nhello again"})

    results = manager.text_search("kb1", "hello")
    assert len(results) == 2
    assert results[0]["content"] == "hello world"
    assert results[1]["content"] == "hello again"


def test_text_search_max_lines(tmp_path: Path) -> None:
    manager, _ = _make_manager(tmp_path)
    content = "\n".join(f"match line {i}" for i in range(10))
    _make_kb(tmp_path, "kb1", {"doc.txt": content})

    results = manager.text_search("kb1", "match", max_lines=3)
    assert len(results) == 3


def test_text_search_max_chars(tmp_path: Path) -> None:
    manager, _ = _make_manager(tmp_path)
    content = "\n".join("x" * 100 for _ in range(10))
    _make_kb(tmp_path, "kb1", {"doc.txt": content})

    results = manager.text_search("kb1", "x", max_chars=250)
    assert len(results) <= 3  # 每行100字符，最多2-3行


def test_text_search_case_insensitive(tmp_path: Path) -> None:
    manager, _ = _make_manager(tmp_path)
    _make_kb(tmp_path, "kb1", {"doc.txt": "Hello World\nfoo bar"})

    results = manager.text_search("kb1", "hello")
    assert len(results) == 1


def test_text_search_missing_kb(tmp_path: Path) -> None:
    manager, _ = _make_manager(tmp_path)
    assert manager.text_search("nonexistent", "keyword") == []


async def test_embed_knowledge_base(tmp_path: Path) -> None:
    manager, embedder = _make_manager(tmp_path)
    embedder.embed = AsyncMock(return_value=[[0.1, 0.2], [0.3, 0.4]])

    _make_kb(tmp_path, "kb1", {"doc.txt": "line one\nline two\n\nline three"})

    with patch.object(manager, "_get_store") as mock_store:
        store = AsyncMock()
        store.add_chunks = AsyncMock(return_value=3)
        mock_store.return_value = store

        added = await manager.embed_knowledge_base("kb1")

    assert added == 3
    embedder.embed.assert_called_once()
    called_lines = embedder.embed.call_args[0][0]
    assert called_lines == ["line one", "line two", "line three"]


async def test_embed_skips_unchanged_files(tmp_path: Path) -> None:
    manager, embedder = _make_manager(tmp_path)
    embedder.embed = AsyncMock(return_value=[[0.1]])

    _make_kb(tmp_path, "kb1", {"doc.txt": "hello"})

    with patch.object(manager, "_get_store") as mock_store:
        store = AsyncMock()
        store.add_chunks = AsyncMock(return_value=1)
        mock_store.return_value = store

        await manager.embed_knowledge_base("kb1")
        first_call_count = embedder.embed.call_count

        # 第二次扫描，文件未变，不应再次嵌入
        await manager.embed_knowledge_base("kb1")
        assert embedder.embed.call_count == first_call_count
