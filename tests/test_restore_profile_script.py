from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import chromadb
import pytest

from Undefined.cognitive.profile_storage import ProfileStorage
from Undefined.cognitive.service.helpers import _serialize_profile_markdown
from Undefined.config.loader import Config


def _load_script() -> ModuleType:
    path = Path(__file__).resolve().parent.parent / "scripts" / "restore_profile.py"
    spec = importlib.util.spec_from_file_location("restore_profile_script", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Embedder:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[list[str]] = []
        self.stopped = False

    async def embed(self, documents: list[str]) -> list[list[float]]:
        self.calls.append(documents)
        if self.fail:
            raise RuntimeError("embedding unavailable")
        return [[1.0, 0.0, 0.0] for _ in documents]

    async def stop(self) -> None:
        self.stopped = True


def _args(
    revision: str, *, action: str = "restore", dry_run: bool = False
) -> argparse.Namespace:
    return argparse.Namespace(
        action=action,
        entity_type="user",
        entity_id="123",
        revision=revision,
        profiles_path="",
        db_path="",
        dry_run=dry_run,
    )


async def _seed_profiles(tmp_path: Path) -> tuple[Config, ProfileStorage, str, str]:
    config = Config.from_mapping(
        {
            "cognitive": {
                "vector_store": {"path": str(tmp_path / "chroma")},
                "profile": {"path": str(tmp_path / "profiles"), "revision_keep": 1},
            }
        },
        strict=False,
    )
    assert Path(config.cognitive.profiles_path).resolve().is_relative_to(tmp_path)
    assert Path(config.cognitive.vector_store_path).resolve().is_relative_to(tmp_path)
    assert (
        (Path(config.cognitive.profiles_path) / "history")
        .resolve()
        .is_relative_to(tmp_path)
    )
    storage = ProfileStorage(config.cognitive.profiles_path, revision_keep=1)
    recovered = _serialize_profile_markdown(
        {
            "entity_type": "user",
            "entity_id": "123",
            "nickname": "恢复的名称",
            "tags": ["原标签"],
        },
        "GOOD recovered profile",
        evaluation="恢复的评价",
        roast="恢复的锐评",
    )
    await storage.write_profile("user", "123", recovered)
    await storage.write_profile("user", "123", "BAD mistaken profile")
    revision = (await storage.list_revisions("user", "123"))[0]
    return config, storage, revision, recovered


def _seed_vectors(config: Config, tmp_path: Path) -> Any:
    assert Path(config.cognitive.vector_store_path).resolve().is_relative_to(tmp_path)
    client: Any = chromadb.PersistentClient(path=config.cognitive.vector_store_path)
    collection = client.get_or_create_collection(
        "cognitive_profiles", metadata={"hnsw:space": "cosine"}
    )
    collection.upsert(
        ids=["user:123", "group:999"],
        documents=["BAD mistaken profile", "unrelated profile"],
        embeddings=[[0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
        metadatas=[
            {"entity_type": "user", "entity_id": "123", "nickname": "错误名称"},
            {"entity_type": "group", "entity_id": "999"},
        ],
    )
    return collection


def _files(path: Path) -> dict[Path, bytes]:
    return {
        file.relative_to(path): file.read_bytes()
        for file in path.rglob("*")
        if file.is_file()
    }


@pytest.fixture(autouse=True)
def _isolate_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)


@pytest.mark.asyncio
async def test_restore_syncs_actual_markdown_and_vectors_without_touching_other_entities(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_script()
    config, storage, revision, recovered = await _seed_profiles(tmp_path)
    collection = _seed_vectors(config, tmp_path)
    embedder = _Embedder()
    monkeypatch.setattr(module.Config, "load", lambda **kwargs: config)
    monkeypatch.setattr(module, "_build_embedder", lambda cfg: embedder)

    await module._main(_args(revision))

    assert await storage.read_profile("user", "123") == recovered
    result = collection.get(
        ids=["user:123"], include=["documents", "embeddings", "metadatas"]
    )
    document = result["documents"][0]
    assert "GOOD recovered profile" in document
    assert "BAD mistaken profile" not in document
    assert "恢复的评价" in document and "恢复的锐评" in document
    assert "原标签" in document
    assert embedder.calls == [[document]]
    assert list(result["embeddings"][0]) == [1.0, 0.0, 0.0]
    assert result["metadatas"][0]["nickname"] == "恢复的名称"
    other = collection.get(ids=["group:999"], include=["documents", "embeddings"])
    assert other["documents"] == ["unrelated profile"]
    assert list(other["embeddings"][0]) == [0.0, 0.0, 1.0]
    assert embedder.stopped


@pytest.mark.asyncio
async def test_restore_dry_run_does_not_open_chroma_or_call_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _load_script()
    config, storage, revision, recovered = await _seed_profiles(tmp_path)
    before = _files(tmp_path)
    monkeypatch.setattr(module.Config, "load", lambda **kwargs: config)

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("dry-run must not construct a client or model")

    monkeypatch.setattr(module, "_open_chroma", forbidden)
    monkeypatch.setattr(module, "_build_embedder", forbidden)
    await module._main(_args(revision, dry_run=True))

    assert _files(tmp_path) == before
    assert await storage.read_profile("user", "123") == "BAD mistaken profile"
    assert recovered in capsys.readouterr().out
    assert not Path(config.cognitive.vector_store_path).exists()


@pytest.mark.asyncio
async def test_embedding_failure_leaves_files_and_vectors_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_script()
    config, _, revision, _ = await _seed_profiles(tmp_path)
    _seed_vectors(config, tmp_path)
    before = _files(tmp_path)
    embedder = _Embedder(fail=True)
    monkeypatch.setattr(module.Config, "load", lambda **kwargs: config)
    monkeypatch.setattr(module, "_build_embedder", lambda cfg: embedder)

    with pytest.raises(RuntimeError, match="embedding unavailable"):
        await module._main(_args(revision))

    assert _files(tmp_path) == before
    assert embedder.stopped


@pytest.mark.asyncio
async def test_sync_retries_vector_failure_after_revision_was_pruned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _load_script()
    config, storage, revision, recovered = await _seed_profiles(tmp_path)
    collection = _seed_vectors(config, tmp_path)
    embedder = _Embedder()
    monkeypatch.setattr(module.Config, "load", lambda **kwargs: config)
    monkeypatch.setattr(module, "_build_embedder", lambda cfg: embedder)
    original_upsert = type(collection).upsert
    fail_next = True

    def upsert_once(self: Any, *args: Any, **kwargs: Any) -> None:
        nonlocal fail_next
        if fail_next:
            fail_next = False
            raise RuntimeError("Chroma temporarily unavailable")
        original_upsert(self, *args, **kwargs)

    monkeypatch.setattr(type(collection), "upsert", upsert_once)
    with pytest.raises(RuntimeError, match="使用 sync 动作重试"):
        await module._main(_args(revision))

    assert "已同步" not in capsys.readouterr().out
    assert await storage.read_profile("user", "123") == recovered
    assert revision not in await storage.list_revisions("user", "123")
    assert collection.get(ids=["user:123"])["documents"] == ["BAD mistaken profile"]
    history_before = _files(tmp_path / "profiles" / "history")

    await module._main(_args("", action="sync"))

    result = collection.get(ids=["user:123"], include=["documents", "embeddings"])
    assert "GOOD recovered profile" in result["documents"][0]
    assert list(result["embeddings"][0]) == [1.0, 0.0, 0.0]
    assert _files(tmp_path / "profiles" / "history") == history_before
