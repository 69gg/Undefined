from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import chromadb
import pytest


def _load_script_module() -> ModuleType:
    script_path = (
        Path(__file__).resolve().parent.parent / "scripts" / "reembed_cognitive.py"
    )
    spec = importlib.util.spec_from_file_location(
        "reembed_cognitive_script", script_path
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FixedDimEmbedder:
    """返回固定维度的假嵌入器。"""

    def __init__(self, dimension: int) -> None:
        self._dimension = dimension
        self.calls: list[list[str]] = []

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return [[0.1] * self._dimension for _ in texts]


def _seed_collection(client: Any, name: str, dimension: int, count: int = 3) -> Any:
    collection = client.get_or_create_collection(
        name, metadata={"hnsw:space": "cosine"}
    )
    collection.add(
        ids=[f"id-{i}" for i in range(count)],
        documents=[f"doc-{i}" for i in range(count)],
        embeddings=[[0.2] * dimension for i in range(count)],
        metadatas=[{"idx": i} for i in range(count)],
    )
    return collection


@pytest.mark.asyncio
async def test_reembed_rebuilds_collection_on_dimension_change(
    tmp_path: Path,
) -> None:
    module = _load_script_module()
    client = chromadb.PersistentClient(path=str(tmp_path))
    collection = _seed_collection(client, "cognitive_events", dimension=3)

    processed = await module._reembed_collection(
        collection,
        "cognitive_events",
        _FixedDimEmbedder(5),
        batch_size=2,
        dry_run=False,
        client=client,
    )

    assert processed == 3
    rebuilt = client.get_or_create_collection("cognitive_events")
    assert rebuilt.count() == 3
    sample = cast(
        Any,
        rebuilt.get(limit=1, include=["embeddings", "documents", "metadatas"]),
    )
    assert len(sample["embeddings"][0]) == 5
    assert sample["documents"][0].startswith("doc-")
    assert sample["metadatas"][0]["idx"] in {0, 1, 2}


@pytest.mark.asyncio
async def test_reembed_keeps_collection_when_dimension_matches(
    tmp_path: Path,
) -> None:
    module = _load_script_module()
    client = chromadb.PersistentClient(path=str(tmp_path))
    collection = _seed_collection(client, "cognitive_profiles", dimension=4)

    await module._reembed_collection(
        collection,
        "cognitive_profiles",
        _FixedDimEmbedder(4),
        batch_size=4,
        dry_run=False,
        client=client,
    )

    stored = client.get_collection("cognitive_profiles")
    assert stored.count() == 3
    stored_sample = cast(Any, stored.get(limit=1, include=["embeddings"]))
    assert len(stored_sample["embeddings"][0]) == 4


@pytest.mark.asyncio
async def test_reembed_dry_run_reports_dimension_change_without_writing(
    tmp_path: Path,
) -> None:
    module = _load_script_module()
    client = chromadb.PersistentClient(path=str(tmp_path))
    collection = _seed_collection(client, "cognitive_events", dimension=3)

    await module._reembed_collection(
        collection,
        "cognitive_events",
        _FixedDimEmbedder(7),
        batch_size=2,
        dry_run=True,
        client=client,
    )

    # 原 collection 未被删除，维度保持 3
    unchanged = client.get_collection("cognitive_events")
    assert unchanged.count() == 3
    unchanged_sample = cast(Any, unchanged.get(limit=1, include=["embeddings"]))
    assert len(unchanged_sample["embeddings"][0]) == 3


@pytest.mark.asyncio
async def test_reembed_migration_leaves_no_staging_collection(
    tmp_path: Path,
) -> None:
    module = _load_script_module()
    client = chromadb.PersistentClient(path=str(tmp_path))
    collection = _seed_collection(client, "cognitive_events", dimension=3)

    await module._reembed_collection(
        collection,
        "cognitive_events",
        _FixedDimEmbedder(5),
        batch_size=2,
        dry_run=False,
        client=client,
    )

    names = {c.name for c in client.list_collections()}
    assert names == {"cognitive_events"}
    migrated = client.get_collection("cognitive_events")
    assert migrated.count() == 3
    sample = cast(Any, migrated.get(limit=1, include=["embeddings"]))
    assert len(sample["embeddings"][0]) == 5


def test_recover_stale_staging_deletes_residue_when_original_intact(
    tmp_path: Path,
) -> None:
    module = _load_script_module()
    client = chromadb.PersistentClient(path=str(tmp_path))
    _seed_collection(client, "cognitive_events", dimension=3, count=2)
    _seed_collection(client, "cognitive_events__rebuild_tmp", dimension=5, count=2)

    module._recover_stale_staging(client, "cognitive_events")

    names = {c.name for c in client.list_collections()}
    assert names == {"cognitive_events"}
    assert client.get_collection("cognitive_events").count() == 2


def test_recover_stale_staging_renames_back_when_original_missing(
    tmp_path: Path,
) -> None:
    module = _load_script_module()
    client = chromadb.PersistentClient(path=str(tmp_path))
    # 模拟「删了原库、还没换名」的中断现场：全量数据只在临时库里
    _seed_collection(client, "cognitive_events__rebuild_tmp", dimension=5, count=2)

    module._recover_stale_staging(client, "cognitive_events")

    names = {c.name for c in client.list_collections()}
    assert names == {"cognitive_events"}
    restored = client.get_collection("cognitive_events")
    assert restored.count() == 2
    sample = cast(Any, restored.get(limit=1, include=["embeddings"]))
    assert len(sample["embeddings"][0]) == 5


@pytest.mark.asyncio
async def test_reembed_empty_collection_is_skipped(tmp_path: Path) -> None:
    module = _load_script_module()
    client = chromadb.PersistentClient(path=str(tmp_path))
    collection = client.get_or_create_collection(
        "cognitive_events", metadata={"hnsw:space": "cosine"}
    )
    embedder = _FixedDimEmbedder(3)

    processed = await module._reembed_collection(
        collection,
        "cognitive_events",
        embedder,
        batch_size=2,
        dry_run=False,
        client=client,
    )

    assert processed == 0
    assert embedder.calls == []
