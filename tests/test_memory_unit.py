"""MemoryStorage 单元测试"""

from __future__ import annotations

from dataclasses import asdict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from Undefined.memory import Memory, MemoryStorage


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_storage(
    initial_data: list[dict[str, str]] | None = None,
    max_memories: int = 500,
) -> MemoryStorage:
    """构造 MemoryStorage 并跳过真实文件 I/O。"""
    with patch("Undefined.memory.MEMORY_FILE_PATH") as mock_path:
        if initial_data is not None:
            import io as _io
            import json

            mock_path.exists.return_value = True
            mock_file = _io.StringIO(json.dumps(initial_data))
            mock_open = MagicMock(return_value=mock_file)
            with patch("builtins.open", mock_open):
                storage = MemoryStorage(max_memories=max_memories)
        else:
            mock_path.exists.return_value = False
            storage = MemoryStorage(max_memories=max_memories)
    return storage


_WRITE_JSON = "Undefined.utils.io.write_json"


# ---------------------------------------------------------------------------
# Memory dataclass
# ---------------------------------------------------------------------------


class TestMemoryDataclass:
    def test_fields(self) -> None:
        m = Memory(uuid="u1", fact="hello", created_at="2025-01-01")
        assert m.uuid == "u1"
        assert m.fact == "hello"
        assert m.created_at == "2025-01-01"

    def test_asdict(self) -> None:
        m = Memory(uuid="u1", fact="hello", created_at="2025-01-01")
        d = asdict(m)
        assert d == {"uuid": "u1", "fact": "hello", "created_at": "2025-01-01"}


# ---------------------------------------------------------------------------
# MemoryStorage
# ---------------------------------------------------------------------------


class TestMemoryStorageInit:
    def test_empty_init(self) -> None:
        storage = _make_storage()
        assert storage.count() == 0
        assert storage.get_all() == []

    def test_init_with_data(self) -> None:
        data = [
            {"uuid": "u1", "fact": "fact1", "created_at": "2025-01-01"},
            {"uuid": "u2", "fact": "fact2", "created_at": "2025-01-02"},
        ]
        storage = _make_storage(initial_data=data)
        assert storage.count() == 2

    def test_init_with_legacy_data_without_uuid(self) -> None:
        """旧格式记录不含 uuid，应自动生成。"""
        data: list[dict[str, str]] = [
            {"fact": "old fact", "created_at": "2024-01-01"},
        ]
        storage = _make_storage(initial_data=data)
        assert storage.count() == 1
        memories = storage.get_all()
        assert memories[0].fact == "old fact"
        assert memories[0].uuid  # 自动生成了 UUID


class TestMemoryStorageAdd:
    @pytest.mark.asyncio
    async def test_add_returns_uuid(self) -> None:
        storage = _make_storage()
        with patch(_WRITE_JSON, new_callable=AsyncMock):
            result = await storage.add("new fact")
        assert result is not None
        assert storage.count() == 1

    @pytest.mark.asyncio
    async def test_add_strips_whitespace(self) -> None:
        storage = _make_storage()
        with patch(_WRITE_JSON, new_callable=AsyncMock):
            await storage.add("  spaced fact  ")
        assert storage.get_all()[0].fact == "spaced fact"

    @pytest.mark.asyncio
    async def test_add_empty_returns_none(self) -> None:
        storage = _make_storage()
        result = await storage.add("")
        assert result is None
        assert storage.count() == 0

    @pytest.mark.asyncio
    async def test_add_whitespace_only_returns_none(self) -> None:
        storage = _make_storage()
        result = await storage.add("   ")
        assert result is None
        assert storage.count() == 0

    @pytest.mark.asyncio
    async def test_add_duplicate_returns_existing_uuid(self) -> None:
        storage = _make_storage()
        with patch(_WRITE_JSON, new_callable=AsyncMock):
            uuid1 = await storage.add("duplicate fact")
            uuid2 = await storage.add("duplicate fact")
        assert uuid1 == uuid2
        assert storage.count() == 1

    @pytest.mark.asyncio
    async def test_add_max_memories_evicts_oldest(self) -> None:
        storage = _make_storage(max_memories=3)
        with patch(_WRITE_JSON, new_callable=AsyncMock):
            await storage.add("fact1")
            await storage.add("fact2")
            await storage.add("fact3")
            assert storage.count() == 3
            await storage.add("fact4")
        assert storage.count() == 3
        facts = [m.fact for m in storage.get_all()]
        assert "fact1" not in facts
        assert "fact4" in facts

    @pytest.mark.asyncio
    async def test_add_calls_save(self) -> None:
        storage = _make_storage()
        with patch(_WRITE_JSON, new_callable=AsyncMock) as mock_write:
            await storage.add("fact")
            mock_write.assert_awaited_once()


class TestMemoryStorageUpdate:
    @pytest.mark.asyncio
    async def test_update_existing(self) -> None:
        storage = _make_storage()
        with patch(_WRITE_JSON, new_callable=AsyncMock):
            uid = await storage.add("old")
            assert uid is not None
            result = await storage.update(uid, "new")
        assert result is True
        assert storage.get_all()[0].fact == "new"

    @pytest.mark.asyncio
    async def test_update_nonexistent_returns_false(self) -> None:
        storage = _make_storage()
        with patch(_WRITE_JSON, new_callable=AsyncMock):
            result = await storage.update("nonexistent-uuid", "new")
        assert result is False

    @pytest.mark.asyncio
    async def test_update_strips_whitespace(self) -> None:
        storage = _make_storage()
        with patch(_WRITE_JSON, new_callable=AsyncMock):
            uid = await storage.add("old")
            assert uid is not None
            await storage.update(uid, "  updated  ")
        assert storage.get_all()[0].fact == "updated"


class TestMemoryStorageDelete:
    @pytest.mark.asyncio
    async def test_delete_existing(self) -> None:
        storage = _make_storage()
        with patch(_WRITE_JSON, new_callable=AsyncMock):
            uid = await storage.add("to delete")
            assert uid is not None
            result = await storage.delete(uid)
        assert result is True
        assert storage.count() == 0

    @pytest.mark.asyncio
    async def test_delete_nonexistent_returns_false(self) -> None:
        storage = _make_storage()
        with patch(_WRITE_JSON, new_callable=AsyncMock):
            result = await storage.delete("nonexistent-uuid")
        assert result is False


class TestMemoryStorageGetAll:
    def test_get_all_returns_copy(self) -> None:
        data = [{"uuid": "u1", "fact": "fact1", "created_at": "2025-01-01"}]
        storage = _make_storage(initial_data=data)
        list1 = storage.get_all()
        list2 = storage.get_all()
        assert list1 is not list2
        assert list1 == list2


class TestMemoryStorageClear:
    @pytest.mark.asyncio
    async def test_clear(self) -> None:
        data = [{"uuid": "u1", "fact": "fact1", "created_at": "2025-01-01"}]
        storage = _make_storage(initial_data=data)
        with patch(_WRITE_JSON, new_callable=AsyncMock):
            await storage.clear()
        assert storage.count() == 0
        assert storage.get_all() == []


class TestMemoryStorageCount:
    @pytest.mark.asyncio
    async def test_count_tracks_additions(self) -> None:
        storage = _make_storage()
        assert storage.count() == 0
        with patch(_WRITE_JSON, new_callable=AsyncMock):
            await storage.add("a")
            assert storage.count() == 1
            await storage.add("b")
            assert storage.count() == 2
