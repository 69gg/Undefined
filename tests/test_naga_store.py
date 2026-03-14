"""NagaStore 单元测试"""

from __future__ import annotations

from pathlib import Path

import pytest

from Undefined.api.naga_store import NagaStore, mask_token


@pytest.fixture
def store(tmp_path: Path) -> NagaStore:
    return NagaStore(data_file=tmp_path / "naga_bindings.json")


async def test_submit_binding(store: NagaStore) -> None:
    ok, msg = await store.submit_binding("alice", qq_id=123, group_id=456)
    assert ok is True
    assert "已提交" in msg


async def test_submit_duplicate_pending(store: NagaStore) -> None:
    await store.submit_binding("alice", qq_id=123, group_id=456)
    ok, msg = await store.submit_binding("alice", qq_id=789, group_id=456)
    assert ok is False
    assert "审核队列" in msg


async def test_submit_already_bound(store: NagaStore) -> None:
    await store.submit_binding("alice", qq_id=123, group_id=456)
    await store.approve("alice")
    ok, msg = await store.submit_binding("alice", qq_id=789, group_id=456)
    assert ok is False
    assert "已绑定" in msg


async def test_approve(store: NagaStore) -> None:
    await store.submit_binding("alice", qq_id=123, group_id=456)
    binding = await store.approve("alice")
    assert binding is not None
    assert binding.naga_id == "alice"
    assert binding.qq_id == 123
    assert binding.group_id == 456
    assert binding.token.startswith("udf_")
    assert len(binding.token) == 4 + 48  # "udf_" + 48 hex


async def test_approve_nonexistent(store: NagaStore) -> None:
    result = await store.approve("nonexistent")
    assert result is None


async def test_reject(store: NagaStore) -> None:
    await store.submit_binding("alice", qq_id=123, group_id=456)
    ok = await store.reject("alice")
    assert ok is True
    assert store.list_pending() == []


async def test_reject_nonexistent(store: NagaStore) -> None:
    ok = await store.reject("nonexistent")
    assert ok is False


async def test_revoke(store: NagaStore) -> None:
    await store.submit_binding("alice", qq_id=123, group_id=456)
    await store.approve("alice")
    ok = await store.revoke("alice")
    assert ok is True
    binding = store.get_binding("alice")
    assert binding is not None
    assert binding.revoked is True


async def test_revoke_nonexistent(store: NagaStore) -> None:
    ok = await store.revoke("nonexistent")
    assert ok is False


async def test_revoke_already_revoked(store: NagaStore) -> None:
    await store.submit_binding("alice", qq_id=123, group_id=456)
    await store.approve("alice")
    await store.revoke("alice")
    ok = await store.revoke("alice")
    assert ok is False


async def test_verify_valid(store: NagaStore) -> None:
    await store.submit_binding("alice", qq_id=123, group_id=456)
    binding = await store.approve("alice")
    assert binding is not None
    valid, err = store.verify("alice", binding.token)
    assert valid is True
    assert err == ""


async def test_verify_wrong_token(store: NagaStore) -> None:
    await store.submit_binding("alice", qq_id=123, group_id=456)
    await store.approve("alice")
    valid, err = store.verify("alice", "udf_wrong")
    assert valid is False
    assert "不匹配" in err


async def test_verify_revoked(store: NagaStore) -> None:
    await store.submit_binding("alice", qq_id=123, group_id=456)
    binding = await store.approve("alice")
    assert binding is not None
    await store.revoke("alice")
    valid, err = store.verify("alice", binding.token)
    assert valid is False
    assert "吊销" in err


async def test_verify_nonexistent(store: NagaStore) -> None:
    valid, err = store.verify("nonexistent", "udf_xxx")
    assert valid is False
    assert "未绑定" in err


async def test_list_bindings(store: NagaStore) -> None:
    await store.submit_binding("alice", qq_id=123, group_id=456)
    await store.approve("alice")
    await store.submit_binding("bob", qq_id=789, group_id=456)
    await store.approve("bob")

    bindings = store.list_bindings()
    assert len(bindings) == 2
    ids = {b.naga_id for b in bindings}
    assert ids == {"alice", "bob"}


async def test_list_bindings_excludes_revoked(store: NagaStore) -> None:
    await store.submit_binding("alice", qq_id=123, group_id=456)
    await store.approve("alice")
    await store.revoke("alice")

    bindings = store.list_bindings()
    assert len(bindings) == 0


async def test_list_pending(store: NagaStore) -> None:
    await store.submit_binding("alice", qq_id=123, group_id=456)
    await store.submit_binding("bob", qq_id=789, group_id=456)

    pending = store.list_pending()
    assert len(pending) == 2


async def test_record_usage(store: NagaStore) -> None:
    await store.submit_binding("alice", qq_id=123, group_id=456)
    await store.approve("alice")
    await store.record_usage("alice")

    binding = store.get_binding("alice")
    assert binding is not None
    assert binding.use_count == 1
    assert binding.last_used_at is not None


async def test_persistence(tmp_path: Path) -> None:
    """测试保存后重新加载数据一致性"""
    data_file = tmp_path / "naga_bindings.json"

    store1 = NagaStore(data_file=data_file)
    await store1.submit_binding("alice", qq_id=123, group_id=456)
    binding = await store1.approve("alice")
    assert binding is not None

    await store1.submit_binding("bob", qq_id=789, group_id=456)

    # 重新加载
    store2 = NagaStore(data_file=data_file)
    await store2.load()

    assert store2.get_binding("alice") is not None
    assert store2.get_binding("alice").token == binding.token  # type: ignore[union-attr]
    assert len(store2.list_pending()) == 1


async def test_submit_after_revoke_allows_rebind(store: NagaStore) -> None:
    """吊销后可以重新提交绑定"""
    await store.submit_binding("alice", qq_id=123, group_id=456)
    await store.approve("alice")
    await store.revoke("alice")
    ok, _ = await store.submit_binding("alice", qq_id=789, group_id=456)
    assert ok is True


def test_mask_token() -> None:
    assert mask_token("udf_a1b2c3d4e5f6g7h8") == "udf_a1b2c3d4..."
    assert mask_token("short") == "short"
    assert mask_token("udf_12345678") == "udf_12345678"
    assert mask_token("udf_123456789") == "udf_12345678..."
