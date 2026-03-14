"""NagaStore 单元测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from Undefined.api.naga_store import NagaStore, generate_bind_uuid, mask_token


@pytest.fixture
def store(tmp_path: Path) -> NagaStore:
    return NagaStore(data_file=tmp_path / "naga_bindings.json")


async def test_submit_binding_creates_pending_with_bind_uuid(store: NagaStore) -> None:
    ok, msg, pending = await store.submit_binding(
        "alice",
        qq_id=123,
        group_id=456,
        bind_uuid="uuid_a",
        request_context={"group_name": "Test"},
    )
    assert ok is True
    assert "已提交" in msg
    assert pending is not None
    assert pending.bind_uuid == "uuid_a"
    assert pending.request_context["group_name"] == "Test"


async def test_submit_binding_generates_uuid_by_default(store: NagaStore) -> None:
    ok, _, pending = await store.submit_binding("alice", qq_id=123, group_id=456)
    assert ok is True
    assert pending is not None
    assert pending.bind_uuid


async def test_submit_duplicate_pending(store: NagaStore) -> None:
    await store.submit_binding("alice", qq_id=123, group_id=456)
    ok, msg, pending = await store.submit_binding("alice", qq_id=789, group_id=456)
    assert ok is False
    assert "处理中" in msg
    assert pending is None


async def test_submit_already_bound(store: NagaStore) -> None:
    await store.submit_binding("alice", qq_id=123, group_id=456, bind_uuid="uuid_a")
    binding, created, err = await store.activate_binding(
        bind_uuid="uuid_a",
        naga_id="alice",
        delivery_signature="sig_1",
    )
    assert binding is not None
    assert created is True
    assert err == ""

    ok, msg, pending = await store.submit_binding("alice", qq_id=789, group_id=456)
    assert ok is False
    assert "已绑定" in msg
    assert pending is None


async def test_activate_binding(store: NagaStore) -> None:
    await store.submit_binding("alice", qq_id=123, group_id=456, bind_uuid="uuid_a")
    binding, created, err = await store.activate_binding(
        bind_uuid="uuid_a",
        naga_id="alice",
        delivery_signature="sig_1",
    )
    assert binding is not None
    assert created is True
    assert err == ""
    assert binding.naga_id == "alice"
    assert binding.bind_uuid == "uuid_a"
    assert binding.delivery_signature == "sig_1"
    assert store.list_pending() == []


async def test_activate_binding_is_idempotent(store: NagaStore) -> None:
    await store.submit_binding("alice", qq_id=123, group_id=456, bind_uuid="uuid_a")
    first, created, _ = await store.activate_binding(
        bind_uuid="uuid_a",
        naga_id="alice",
        delivery_signature="sig_1",
    )
    second, created2, err2 = await store.activate_binding(
        bind_uuid="uuid_a",
        naga_id="alice",
        delivery_signature="sig_1",
    )
    assert first is not None
    assert second is not None
    assert created is True
    assert created2 is False
    assert err2 == ""


async def test_reject_binding(store: NagaStore) -> None:
    await store.submit_binding("alice", qq_id=123, group_id=456, bind_uuid="uuid_a")
    pending, removed, err = await store.reject_binding(
        bind_uuid="uuid_a",
        naga_id="alice",
    )
    assert pending is not None
    assert pending.qq_id == 123
    assert removed is True
    assert err == ""
    assert store.list_pending() == []


async def test_cancel_pending(store: NagaStore) -> None:
    await store.submit_binding("alice", qq_id=123, group_id=456, bind_uuid="uuid_a")
    pending = await store.cancel_pending("alice", bind_uuid="uuid_a")
    assert pending is not None
    assert store.list_pending() == []


async def test_revoke(store: NagaStore) -> None:
    await store.submit_binding("alice", qq_id=123, group_id=456, bind_uuid="uuid_a")
    await store.activate_binding(
        bind_uuid="uuid_a",
        naga_id="alice",
        delivery_signature="sig_1",
    )
    ok = await store.revoke("alice")
    assert ok is True
    binding = store.get_binding("alice")
    assert binding is not None
    assert binding.revoked is True


async def test_verify_delivery_valid(store: NagaStore) -> None:
    await store.submit_binding("alice", qq_id=123, group_id=456, bind_uuid="uuid_a")
    await store.activate_binding(
        bind_uuid="uuid_a",
        naga_id="alice",
        delivery_signature="sig_1",
    )
    binding, err = store.verify_delivery(
        naga_id="alice",
        bind_uuid="uuid_a",
        delivery_signature="sig_1",
    )
    assert binding is not None
    assert err == ""


async def test_verify_delivery_wrong_signature(store: NagaStore) -> None:
    await store.submit_binding("alice", qq_id=123, group_id=456, bind_uuid="uuid_a")
    await store.activate_binding(
        bind_uuid="uuid_a",
        naga_id="alice",
        delivery_signature="sig_1",
    )
    binding, err = store.verify_delivery(
        naga_id="alice",
        bind_uuid="uuid_a",
        delivery_signature="sig_wrong",
    )
    assert binding is None
    assert "delivery_signature" in err


async def test_verify_delivery_wrong_bind_uuid(store: NagaStore) -> None:
    await store.submit_binding("alice", qq_id=123, group_id=456, bind_uuid="uuid_a")
    await store.activate_binding(
        bind_uuid="uuid_a",
        naga_id="alice",
        delivery_signature="sig_1",
    )
    binding, err = store.verify_delivery(
        naga_id="alice",
        bind_uuid="uuid_b",
        delivery_signature="sig_1",
    )
    assert binding is None
    assert "bind_uuid" in err


async def test_verify_delivery_revoked(store: NagaStore) -> None:
    await store.submit_binding("alice", qq_id=123, group_id=456, bind_uuid="uuid_a")
    await store.activate_binding(
        bind_uuid="uuid_a",
        naga_id="alice",
        delivery_signature="sig_1",
    )
    await store.revoke("alice")
    binding, err = store.verify_delivery(
        naga_id="alice",
        bind_uuid="uuid_a",
        delivery_signature="sig_1",
    )
    assert binding is None
    assert "吊销" in err


async def test_record_usage(store: NagaStore) -> None:
    await store.submit_binding("alice", qq_id=123, group_id=456, bind_uuid="uuid_a")
    await store.activate_binding(
        bind_uuid="uuid_a",
        naga_id="alice",
        delivery_signature="sig_1",
    )
    await store.record_usage("alice")
    binding = store.get_binding("alice")
    assert binding is not None
    assert binding.use_count == 1
    assert binding.last_used_at is not None


async def test_persistence(tmp_path: Path) -> None:
    data_file = tmp_path / "naga_bindings.json"
    store1 = NagaStore(data_file=data_file)
    await store1.submit_binding("alice", qq_id=123, group_id=456, bind_uuid="uuid_a")
    binding, _, _ = await store1.activate_binding(
        bind_uuid="uuid_a",
        naga_id="alice",
        delivery_signature="sig_1",
    )
    assert binding is not None
    await store1.submit_binding("bob", qq_id=789, group_id=456, bind_uuid="uuid_b")

    store2 = NagaStore(data_file=data_file)
    await store2.load()
    reloaded = store2.get_binding("alice")
    assert reloaded is not None
    assert reloaded.delivery_signature == binding.delivery_signature
    assert len(store2.list_pending()) == 1


async def test_submit_after_revoke_allows_rebind(store: NagaStore) -> None:
    await store.submit_binding("alice", qq_id=123, group_id=456, bind_uuid="uuid_a")
    await store.activate_binding(
        bind_uuid="uuid_a",
        naga_id="alice",
        delivery_signature="sig_1",
    )
    await store.revoke("alice")
    ok, _, pending = await store.submit_binding("alice", qq_id=789, group_id=456)
    assert ok is True
    assert pending is not None


def test_generate_bind_uuid() -> None:
    first = generate_bind_uuid()
    second = generate_bind_uuid()
    assert first
    assert second
    assert first != second


def test_mask_token() -> None:
    assert mask_token("sig_a1b2c3d4e5f6g7h8") == "sig_a1b2c3d4..."
    assert mask_token("short") == "short"
