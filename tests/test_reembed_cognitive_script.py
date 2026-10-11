from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType, SimpleNamespace
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
        self.stopped = False

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return [[0.1] * self._dimension for _ in texts]

    async def stop(self) -> None:
        self.stopped = True


class _DriftingDimEmbedder:
    """首批返回 dim_a、之后返回 dim_b 的假嵌入器，模拟模型输出漂移。"""

    def __init__(self, dim_a: int, dim_b: int) -> None:
        self._dims = [dim_a, dim_b]
        self._calls = 0

    async def embed(self, texts: list[str]) -> list[list[float]]:
        dim = self._dims[0] if self._calls == 0 else self._dims[1]
        self._calls += 1
        return [[0.1] * dim for _ in texts]


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
@pytest.mark.parametrize("name", ["cognitive_events", "cognitive_profiles"])
@pytest.mark.parametrize("scenario", ["formal_and_staging", "only_staging", "missing"])
async def test_main_dry_run_preserves_collections_and_source_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str, scenario: str
) -> None:
    module = _load_script_module()
    db_path = tmp_path / "db"
    persistent_client = chromadb.PersistentClient
    source_client = persistent_client(path=str(db_path))
    staging_name = f"{name}__rebuild_tmp"
    if scenario == "formal_and_staging":
        _seed_collection(source_client, name, dimension=3, count=2)
    if scenario != "missing":
        _seed_collection(source_client, staging_name, dimension=3, count=2)
    names_before = {collection.name for collection in source_client.list_collections()}
    files_before = {
        path.relative_to(db_path): path.read_bytes()
        for path in db_path.rglob("*")
        if path.is_file()
    }
    opened_paths: list[Path] = []

    class _ReadOnlyClient:
        def __init__(self, client: Any) -> None:
            self._client = client

        def list_collections(self) -> list[Any]:
            return cast(list[Any], self._client.list_collections())

        def get_collection(self, collection_name: str) -> Any:
            return self._client.get_collection(collection_name)

        def get_or_create_collection(self, *args: Any, **kwargs: Any) -> Any:
            raise AssertionError("dry-run 不能创建 collection")

        def delete_collection(self, *args: Any, **kwargs: Any) -> None:
            raise AssertionError("dry-run 不能删除 collection")

    def _open_preview(*, path: str) -> _ReadOnlyClient:
        preview_path = Path(path)
        assert preview_path != db_path
        opened_paths.append(preview_path)
        return _ReadOnlyClient(persistent_client(path=path))

    def _unexpected_recovery(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("dry-run 不能清理或换名 staging")

    config = SimpleNamespace(
        cognitive=SimpleNamespace(vector_store_path=str(db_path)),
        resolve_embedding_model=lambda _feature: SimpleNamespace(
            model_name="fake-embedding", dimensions=5
        ),
    )
    embedder = _FixedDimEmbedder(5)
    monkeypatch.setattr(module, "Config", SimpleNamespace(load=lambda **kwargs: config))
    monkeypatch.setattr(module, "_build_embedder", lambda _config: embedder)
    monkeypatch.setattr(module, "_recover_stale_staging", _unexpected_recovery)
    monkeypatch.setattr(module.chromadb, "PersistentClient", _open_preview)
    args = SimpleNamespace(
        db_path=None,
        events_only=name == "cognitive_events",
        profiles_only=name == "cognitive_profiles",
        batch_size=2,
        dry_run=True,
    )
    await module._main(args)

    assert {
        path.relative_to(db_path): path.read_bytes()
        for path in db_path.rglob("*")
        if path.is_file()
    } == files_before
    assert {
        collection.name for collection in source_client.list_collections()
    } == names_before
    assert embedder.stopped
    assert len(embedder.calls) == (0 if scenario == "missing" else 1)
    assert len(opened_paths) == 1
    assert not opened_paths[0].exists()


@pytest.mark.asyncio
async def test_main_dry_run_does_not_initialize_an_empty_source_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_script_module()
    db_path = tmp_path / "empty-db"
    db_path.mkdir()
    config = SimpleNamespace(
        cognitive=SimpleNamespace(vector_store_path=str(db_path)),
        resolve_embedding_model=lambda _feature: SimpleNamespace(
            model_name="fake-embedding", dimensions=5
        ),
    )
    embedder = _FixedDimEmbedder(5)
    monkeypatch.setattr(module, "Config", SimpleNamespace(load=lambda **kwargs: config))
    monkeypatch.setattr(module, "_build_embedder", lambda _config: embedder)
    await module._main(
        SimpleNamespace(
            db_path=None,
            events_only=False,
            profiles_only=False,
            batch_size=2,
            dry_run=True,
        )
    )
    assert list(db_path.iterdir()) == []
    assert embedder.calls == []
    assert embedder.stopped


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


@pytest.mark.asyncio
async def test_reembed_aborts_on_batch_dimension_drift(tmp_path: Path) -> None:
    """迁移期间某批次维度异常时立即中止，原库保持完好。"""
    module = _load_script_module()
    client = chromadb.PersistentClient(path=str(tmp_path))
    collection = _seed_collection(client, "cognitive_events", dimension=3)

    with pytest.raises(RuntimeError, match="维度漂移"):
        await module._reembed_collection(
            collection,
            "cognitive_events",
            _DriftingDimEmbedder(5, 6),
            batch_size=2,
            dry_run=False,
            client=client,
        )

    # 原库未被替换，仍是旧维度与全量记录
    original = client.get_collection("cognitive_events")
    assert original.count() == 3
    sample = cast(Any, original.get(limit=1, include=["embeddings"]))
    assert len(sample["embeddings"][0]) == 3


@pytest.mark.asyncio
async def test_reembed_aborts_on_batch_dimension_drift_without_migration(
    tmp_path: Path,
) -> None:
    """维度与原库一致（不触发迁移）时，批次漂移同样必须中止而不是写坏原库。"""
    module = _load_script_module()
    client = chromadb.PersistentClient(path=str(tmp_path))
    collection = _seed_collection(client, "cognitive_events", dimension=3)

    with pytest.raises(RuntimeError, match="批次向量维度漂移"):
        await module._reembed_collection(
            collection,
            "cognitive_events",
            _DriftingDimEmbedder(3, 5),
            batch_size=2,
            dry_run=False,
            client=client,
        )

    original = client.get_collection("cognitive_events")
    assert original.count() == 3
    sample = cast(Any, original.get(limit=1, include=["embeddings"]))
    assert len(sample["embeddings"][0]) == 3


@pytest.mark.asyncio
async def test_reembed_checks_drift_when_current_dimension_unknown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """读不到原维度（返回 0）时同样校验批次漂移，不能静默写坏原库。"""
    module = _load_script_module()
    client = chromadb.PersistentClient(path=str(tmp_path))
    collection = _seed_collection(client, "cognitive_events", dimension=3)
    monkeypatch.setattr(module, "_collection_dimension", lambda _c: 0)

    with pytest.raises(RuntimeError, match="批次向量维度漂移"):
        await module._reembed_collection(
            collection,
            "cognitive_events",
            _DriftingDimEmbedder(3, 5),
            batch_size=2,
            dry_run=False,
            client=client,
        )

    original = client.get_collection("cognitive_events")
    assert original.count() == 3


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
