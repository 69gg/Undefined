"""知识库模块测试"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from chromadb.errors import NotFoundError
from Undefined.knowledge.chunker import chunk_lines
from Undefined.knowledge.embedder import Embedder
from Undefined.knowledge.manager import KnowledgeManager
from Undefined.knowledge.reranker import Reranker
from Undefined.knowledge.store import KnowledgeStore


# ── chunker ──────────────────────────────────────────────────────────────────


def test_chunk_lines_basic() -> None:
    text = "l1\nl2\nl3\nl4\nl5"
    chunks = chunk_lines(text, window=3, overlap=1)  # step=2
    assert chunks == ["l1\nl2\nl3", "l3\nl4\nl5", "l5"]


def test_chunk_lines_ignores_empty() -> None:
    text = "l1\n\nl2\n  \nl3"
    chunks = chunk_lines(text, window=3, overlap=0)
    assert chunks == ["l1\nl2\nl3"]


def test_chunk_lines_empty_text() -> None:
    assert chunk_lines("") == []
    assert chunk_lines("   \n\n  ") == []


def test_chunk_lines_overlap() -> None:
    text = "\n".join(f"l{i}" for i in range(1, 8))  # l1..l7
    chunks = chunk_lines(text, window=4, overlap=1)  # step=3
    assert chunks[0] == "l1\nl2\nl3\nl4"
    assert chunks[1] == "l4\nl5\nl6\nl7"


def test_chunk_lines_smaller_than_window() -> None:
    text = "l1\nl2"
    assert chunk_lines(text, window=10, overlap=2) == ["l1\nl2"]


def test_store_content_hash_includes_source() -> None:
    store = KnowledgeStore.__new__(KnowledgeStore)
    h1 = store._chunk_id("texts/a.txt", 0, "same chunk")
    h2 = store._chunk_id("texts/b.txt", 0, "same chunk")
    h3 = store._chunk_id("texts/a.txt", 1, "same chunk")
    assert h1 != h2
    assert h1 != h3


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


# ── reranker ────────────────────────────────────────────────────────────────


def _make_reranker() -> tuple[Reranker, MagicMock]:
    requester = MagicMock()
    config = MagicMock()
    config.queue_interval_seconds = 0.0
    reranker = Reranker(requester, config)
    return reranker, requester


async def test_reranker_queue_serializes() -> None:
    reranker, requester = _make_reranker()
    order: list[str] = []

    async def fake_rerank(
        model_config: Any,
        query: str,
        documents: list[str],
        top_n: int | None = None,
    ) -> list[dict[str, Any]]:
        order.append(query)
        return [{"index": 0, "relevance_score": 0.9, "document": documents[0]}]

    requester.rerank = fake_rerank
    reranker.start()

    results = await asyncio.gather(
        reranker.rerank("q1", ["a"]),
        reranker.rerank("q2", ["b"]),
        reranker.rerank("q3", ["c"]),
    )
    assert len(results) == 3
    assert sorted(order) == ["q1", "q2", "q3"]


# ── manager ──────────────────────────────────────────────────────────────────


def _make_manager(tmp_path: Path) -> tuple[KnowledgeManager, MagicMock]:
    embedder = MagicMock(spec=Embedder)
    embedder.embed = AsyncMock(return_value=[[0.1, 0.2]])
    embedder._config = MagicMock(document_instruction="")
    manager = KnowledgeManager(base_dir=tmp_path, embedder=embedder, default_top_k=3)
    return manager, embedder


def _make_kb(tmp_path: Path, name: str, files: dict[str, str]) -> Path:
    kb_dir = tmp_path / name
    texts_dir = kb_dir / "texts"
    texts_dir.mkdir(parents=True)
    for fname, content in files.items():
        file_path = texts_dir / fname
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, "utf-8")
    return kb_dir


def test_list_knowledge_bases(tmp_path: Path) -> None:
    manager, _ = _make_manager(tmp_path)
    assert manager.list_knowledge_bases() == []

    _make_kb(tmp_path, "kb1", {"a.txt": "hello"})
    _make_kb(tmp_path, "kb2", {"b.txt": "world"})
    assert manager.list_knowledge_bases() == ["kb1", "kb2"]


def test_list_knowledge_bases_supports_texts_subdirs(tmp_path: Path) -> None:
    manager, _ = _make_manager(tmp_path)
    _make_kb(tmp_path, "kb1", {"docs/readme.md": "hello"})
    _make_kb(tmp_path, "kb2", {"a.txt": "world"})
    assert manager.list_knowledge_bases() == ["kb1", "kb2"]


def test_get_existing_store_uses_read_only_collection(tmp_path: Path) -> None:
    manager, _ = _make_manager(tmp_path)
    _make_kb(tmp_path, "kb1", {"a.txt": "hello"})
    chroma_dir = tmp_path / "kb1" / "chroma"
    chroma_dir.mkdir(parents=True)

    with patch("Undefined.knowledge.manager.KnowledgeStore") as mock_store_cls:
        store = MagicMock()
        mock_store_cls.return_value = store
        result = manager._get_existing_store("kb1")

    assert result is store
    mock_store_cls.assert_called_once_with("kb1", chroma_dir, create_if_missing=False)


def test_get_existing_store_returns_none_when_collection_missing(
    tmp_path: Path,
) -> None:
    manager, _ = _make_manager(tmp_path)
    _make_kb(tmp_path, "kb1", {"a.txt": "hello"})
    (tmp_path / "kb1" / "chroma").mkdir(parents=True)

    with patch(
        "Undefined.knowledge.manager.KnowledgeStore",
        side_effect=NotFoundError("not found"),
    ):
        assert manager._get_existing_store("kb1") is None


def test_collection_name_fallback_for_invalid_kb_name(tmp_path: Path) -> None:
    manager, _ = _make_manager(tmp_path)
    collection_name = manager._collection_name_for_kb("foo/bar")
    assert collection_name.startswith("kb_")
    assert len(collection_name) == 27


def test_list_knowledge_base_infos(tmp_path: Path) -> None:
    manager, _ = _make_manager(tmp_path)
    _make_kb(tmp_path, "kb1", {"a.txt": "hello"})
    _make_kb(tmp_path, "kb2", {"b.txt": "world"})
    (tmp_path / "kb1" / "intro.md").write_text("这个知识库用于心脏医学研究。", "utf-8")

    infos = manager.list_knowledge_base_infos(only_ready=False)
    assert infos == [
        {"name": "kb1", "intro": "这个知识库用于心脏医学研究。", "has_intro": True},
        {"name": "kb2", "intro": "", "has_intro": False},
    ]

    ready_infos = manager.list_knowledge_base_infos(only_ready=True)
    assert ready_infos == [
        {"name": "kb1", "intro": "这个知识库用于心脏医学研究。", "has_intro": True}
    ]


def test_read_knowledge_base_intro_truncates(tmp_path: Path) -> None:
    manager, _ = _make_manager(tmp_path)
    _make_kb(tmp_path, "kb1", {"a.txt": "hello"})
    (tmp_path / "kb1" / "intro.md").write_text("abcdefg", "utf-8")

    assert manager.read_knowledge_base_intro("kb1", max_chars=5) == "abcd…"


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


def test_text_search_case_sensitive(tmp_path: Path) -> None:
    manager, _ = _make_manager(tmp_path)
    _make_kb(tmp_path, "kb1", {"doc.txt": "Hello World\nhello world"})

    results = manager.text_search("kb1", "hello", case_sensitive=True)
    assert len(results) == 1
    assert results[0]["line"] == 2


def test_text_search_source_keyword_filter(tmp_path: Path) -> None:
    manager, _ = _make_manager(tmp_path)
    _make_kb(
        tmp_path,
        "kb1",
        {
            "docs/a.md": "重置密码说明",
            "faq/b.txt": "重置密码入口",
        },
    )

    results = manager.text_search("kb1", "重置密码", source_keyword="docs/")
    assert len(results) == 1
    assert results[0]["source"] == "texts/docs/a.md"


def test_text_search_supports_md_and_html(tmp_path: Path) -> None:
    manager, _ = _make_manager(tmp_path)
    _make_kb(
        tmp_path,
        "kb1",
        {
            "guide.md": "如何重置密码\n请先验证邮箱",
            "docs/page.html": "<h1>重置密码步骤</h1>",
        },
    )

    results = manager.text_search("kb1", "重置密码")
    sources = {item["source"] for item in results}
    assert "texts/guide.md" in sources
    assert "texts/docs/page.html" in sources


def test_text_search_missing_kb(tmp_path: Path) -> None:
    manager, _ = _make_manager(tmp_path)
    assert manager.text_search("nonexistent", "keyword") == []


def test_text_search_invalid_kb_name(tmp_path: Path) -> None:
    manager, _ = _make_manager(tmp_path)
    assert manager.text_search("../escape", "keyword") == []


async def test_embed_knowledge_base(tmp_path: Path) -> None:
    manager, embedder = _make_manager(tmp_path)
    embedder.embed = AsyncMock(return_value=[[0.1, 0.2]])

    _make_kb(tmp_path, "kb1", {"doc.txt": "line one\nline two\n\nline three"})

    with patch.object(manager, "_get_store") as mock_store:
        store = AsyncMock()
        store.add_chunks = AsyncMock(return_value=1)
        mock_store.return_value = store

        added = await manager.embed_knowledge_base("kb1")

    assert added == 1
    embedder.embed.assert_called_once()
    # 默认 window=10，3行合并为1个块
    called_chunks = embedder.embed.call_args[0][0]
    assert called_chunks == ["line one\nline two\nline three"]


async def test_embed_knowledge_base_invalid_kb_name(tmp_path: Path) -> None:
    manager, embedder = _make_manager(tmp_path)
    added = await manager.embed_knowledge_base("../escape")
    assert added == 0
    embedder.embed.assert_not_called()


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


async def test_embed_scans_common_text_formats(tmp_path: Path) -> None:
    manager, embedder = _make_manager(tmp_path)
    embedder.embed = AsyncMock(return_value=[[0.1]])

    _make_kb(
        tmp_path,
        "kb1",
        {
            "chapters/1.md": "第一章",
            "faq.txt": "常见问题",
            "web/page.htm": "<p>页面内容</p>",
            "chroma/ignored.txt": "应被忽略",
            "image.png": "not text",
        },
    )
    (tmp_path / "kb1" / "intro.md").write_text("知识库简介，不用于向量化", "utf-8")

    with patch.object(manager, "_get_store") as mock_store:
        store = AsyncMock()
        store.add_chunks = AsyncMock(return_value=1)
        mock_store.return_value = store

        added = await manager.embed_knowledge_base("kb1")

    assert added == 3
    assert embedder.embed.call_count == 3


async def test_embed_removes_deleted_sources(tmp_path: Path) -> None:
    manager, _ = _make_manager(tmp_path)
    kb_dir = _make_kb(tmp_path, "kb1", {})
    manifest_path = kb_dir / ".manifest.json"
    manifest_path.write_text('{"texts/old.txt":"deadbeef"}', "utf-8")

    with patch.object(manager, "_get_store") as mock_store:
        store = AsyncMock()
        mock_store.return_value = store
        added = await manager.embed_knowledge_base("kb1")

    assert added == 0
    store.delete_by_source.assert_awaited_once_with("texts/old.txt")
    assert json.loads(manifest_path.read_text("utf-8")) == {}


async def test_embed_replaces_changed_file_chunks(tmp_path: Path) -> None:
    manager, embedder = _make_manager(tmp_path)
    embedder.embed = AsyncMock(return_value=[[0.1]])
    kb_dir = _make_kb(tmp_path, "kb1", {"doc.txt": "hello"})
    manifest_path = kb_dir / ".manifest.json"
    manifest_path.write_text('{"texts/doc.txt":"outdated"}', "utf-8")

    with patch.object(manager, "_get_store") as mock_store:
        store = AsyncMock()
        store.add_chunks = AsyncMock(return_value=1)
        mock_store.return_value = store
        added = await manager.embed_knowledge_base("kb1")

    assert added == 1
    store.delete_by_source.assert_awaited_once_with("texts/doc.txt")
    assert "texts/doc.txt" in json.loads(manifest_path.read_text("utf-8"))


async def test_semantic_search_missing_kb_does_not_create_store(tmp_path: Path) -> None:
    manager, embedder = _make_manager(tmp_path)
    results = await manager.semantic_search("missing", "hello")
    assert results == []
    embedder.embed.assert_not_called()
    assert not (tmp_path / "missing" / "chroma").exists()


async def test_semantic_search_invalid_kb_name(tmp_path: Path) -> None:
    manager, embedder = _make_manager(tmp_path)
    results = await manager.semantic_search("../escape", "hello")
    assert results == []
    embedder.embed.assert_not_called()


async def test_semantic_search_without_index_returns_empty(tmp_path: Path) -> None:
    manager, embedder = _make_manager(tmp_path)
    _make_kb(tmp_path, "kb1", {"doc.txt": "hello"})

    results = await manager.semantic_search("kb1", "hello")
    assert results == []
    embedder.embed.assert_not_called()
    assert not (tmp_path / "kb1" / "chroma").exists()


async def test_semantic_search_with_rerank(tmp_path: Path) -> None:
    embedder = MagicMock(spec=Embedder)
    embedder.embed = AsyncMock(return_value=[[0.1, 0.2]])
    embedder._config = MagicMock(query_instruction="")

    reranker = MagicMock(spec=Reranker)
    reranker.rerank = AsyncMock(
        return_value=[
            {"index": 1, "relevance_score": 0.91},
            {"index": 0, "relevance_score": 0.84},
        ]
    )

    manager = KnowledgeManager(
        base_dir=tmp_path,
        embedder=embedder,
        reranker=reranker,
        default_top_k=3,
        rerank_enabled=True,
        rerank_top_k=2,
    )
    _make_kb(tmp_path, "kb1", {"doc.txt": "hello"})

    with patch.object(manager, "_get_existing_store") as mock_store:
        store = AsyncMock()
        store.query = AsyncMock(
            return_value=[
                {"content": "a", "metadata": {"source": "a.txt"}, "distance": 0.2},
                {"content": "b", "metadata": {"source": "b.txt"}, "distance": 0.1},
                {"content": "c", "metadata": {"source": "c.txt"}, "distance": 0.3},
            ]
        )
        mock_store.return_value = store

        results = await manager.semantic_search("kb1", "hello")

    assert [item["content"] for item in results] == ["b", "a"]
    assert results[0]["rerank_score"] == 0.91
    reranker.rerank.assert_called_once()


async def test_semantic_search_rerank_override_disabled(tmp_path: Path) -> None:
    embedder = MagicMock(spec=Embedder)
    embedder.embed = AsyncMock(return_value=[[0.1, 0.2]])
    embedder._config = MagicMock(query_instruction="")

    reranker = MagicMock(spec=Reranker)
    reranker.rerank = AsyncMock(return_value=[])

    manager = KnowledgeManager(
        base_dir=tmp_path,
        embedder=embedder,
        reranker=reranker,
        default_top_k=3,
        rerank_enabled=True,
        rerank_top_k=2,
    )
    _make_kb(tmp_path, "kb1", {"doc.txt": "hello"})

    with patch.object(manager, "_get_existing_store") as mock_store:
        store = AsyncMock()
        store.query = AsyncMock(
            return_value=[
                {"content": "a", "metadata": {}, "distance": 0.2},
                {"content": "b", "metadata": {}, "distance": 0.1},
            ]
        )
        mock_store.return_value = store

        results = await manager.semantic_search("kb1", "hello", enable_rerank=False)

    assert [item["content"] for item in results] == ["a", "b"]
    reranker.rerank.assert_not_called()


async def test_semantic_search_rerank_top_k_must_be_smaller(tmp_path: Path) -> None:
    embedder = MagicMock(spec=Embedder)
    embedder.embed = AsyncMock(return_value=[[0.1, 0.2]])
    embedder._config = MagicMock(query_instruction="")

    reranker = MagicMock(spec=Reranker)
    reranker.rerank = AsyncMock(return_value=[{"index": 1, "relevance_score": 0.99}])

    manager = KnowledgeManager(
        base_dir=tmp_path,
        embedder=embedder,
        reranker=reranker,
        default_top_k=3,
        rerank_enabled=True,
        rerank_top_k=3,
    )
    _make_kb(tmp_path, "kb1", {"doc.txt": "hello"})

    with patch.object(manager, "_get_existing_store") as mock_store:
        store = AsyncMock()
        store.query = AsyncMock(
            return_value=[
                {"content": "a", "metadata": {}, "distance": 0.2},
                {"content": "b", "metadata": {}, "distance": 0.1},
            ]
        )
        mock_store.return_value = store

        results = await manager.semantic_search("kb1", "hello", top_k=2, rerank_top_k=2)

    assert len(results) == 1
    assert results[0]["content"] == "b"


async def test_semantic_search_fallback_when_rerank_fails(tmp_path: Path) -> None:
    embedder = MagicMock(spec=Embedder)
    embedder.embed = AsyncMock(return_value=[[0.1, 0.2]])
    embedder._config = MagicMock(query_instruction="")

    reranker = MagicMock(spec=Reranker)
    reranker.rerank = AsyncMock(
        side_effect=ValueError("not enough values to unpack (expected 2, got 0)")
    )

    manager = KnowledgeManager(
        base_dir=tmp_path,
        embedder=embedder,
        reranker=reranker,
        default_top_k=3,
        rerank_enabled=True,
        rerank_top_k=2,
    )
    _make_kb(tmp_path, "kb1", {"doc.txt": "hello"})

    with patch.object(manager, "_get_existing_store") as mock_store:
        store = AsyncMock()
        store.query = AsyncMock(
            return_value=[
                {"content": "a", "metadata": {"source": "a.txt"}, "distance": 0.2},
                {"content": "b", "metadata": {"source": "b.txt"}, "distance": 0.1},
            ]
        )
        mock_store.return_value = store

        results = await manager.semantic_search("kb1", "hello")

    assert [item["content"] for item in results] == ["a", "b"]
    assert all("rerank_score" not in item for item in results)


async def test_manager_stop_stops_background_components(tmp_path: Path) -> None:
    embedder = MagicMock(spec=Embedder)
    embedder.stop = AsyncMock()
    embedder._config = MagicMock()
    reranker = MagicMock(spec=Reranker)
    reranker.stop = AsyncMock()
    manager = KnowledgeManager(base_dir=tmp_path, embedder=embedder, reranker=reranker)

    manager.start_auto_scan(interval=3600)
    scan_task = manager._scan_task
    assert scan_task is not None

    await manager.stop()

    assert manager._scan_task is None
    assert scan_task.cancelled() or scan_task.done()
    embedder.stop.assert_awaited_once()
    reranker.stop.assert_awaited_once()
