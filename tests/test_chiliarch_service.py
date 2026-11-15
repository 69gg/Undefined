from __future__ import annotations

import asyncio
import base64
import hashlib
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from Undefined.api import RuntimeAPIContext
from Undefined.api.webchat_store import WebChatConversationStore
from Undefined.attachments import AttachmentRegistry
from Undefined.chiliarch import ChiliarchService
from Undefined.chiliarch.service import capture_origin
from Undefined.config import Config
from Undefined.config.models import ChiliarchConfig
from Undefined.context import RequestContext
from Undefined.utils import io

native = pytest.importorskip(
    "chiliarch.client", reason="原生渠道测试需要 uv sync --extra chiliarch"
)
protocol = pytest.importorskip("chiliarch.protocol")


class FakeAI:
    def __init__(self) -> None:
        self.runtime_config = Config.from_mapping({}, strict=False)
        self.attachment_registry: Any = None
        self.calls: list[dict[str, Any]] = []
        self.handler: Callable[[str, dict[str, Any]], Awaitable[str]] | None = None

    async def ask(self, question: str, **kwargs: Any) -> str:
        ctx = RequestContext.require()
        self.calls.append(
            {
                "question": question,
                "context": kwargs["extra_context"],
                "user_id": ctx.user_id,
                "sender_id": ctx.sender_id,
                "identity": ctx.logical_identity,
            }
        )
        if self.handler is not None:
            return await self.handler(question, kwargs)
        return "已处理"


async def eventually(predicate: Callable[[], bool]) -> None:
    async with asyncio.timeout(5):
        while not predicate():
            await asyncio.sleep(0.01)


@pytest.fixture
async def channel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[ChiliarchService]:
    async def transport(client: Any) -> None:
        while not client.stop_event.is_set():
            await client._schedule()
            await asyncio.sleep(0.01)

    monkeypatch.setattr(native.AgentClient, "_ws", transport)
    state = tmp_path / "paired.db"
    store = native.ClientStore(state)
    await store.open()
    await store.save_identity(
        {
            "server_url": "http://example.invalid",
            "credential": "test-only",
            "agent_id": "agent-test",
        }
    )
    await store.close()
    ai = FakeAI()
    runtime = RuntimeAPIContext(
        config_getter=lambda: ai.runtime_config,
        onebot=SimpleNamespace(),
        ai=ai,
        command_dispatcher=None,
        queue_manager=None,
        history_manager=None,
        sender=SimpleNamespace(send_address_message=AsyncMock()),
        scheduler=None,
    )
    service = ChiliarchService(
        ChiliarchConfig(enabled=True, state_path=str(state)), runtime
    )
    runtime.chiliarch_service = service
    await service.start()
    assert service.status()["mailbox_ready"]
    try:
        yield service
    finally:
        await service.stop()


async def deliver(
    service: ChiliarchService, kind: str, payload: dict[str, Any], **kwargs: Any
) -> Any:
    envelope = protocol.Envelope(type=kind, payload=payload, **kwargs)
    await service.client._accept(envelope, AsyncMock())
    return envelope


async def test_disabled_and_unpaired_are_isolated(tmp_path: Path) -> None:
    runtime = SimpleNamespace()
    disabled = ChiliarchService(
        ChiliarchConfig(state_path=str(tmp_path / "off.db")), runtime
    )
    await disabled.start()
    assert disabled.status()["state"] == "disabled"
    assert not disabled.directory.exists()
    missing = ChiliarchService(
        ChiliarchConfig(enabled=True, state_path=str(tmp_path / "missing.db")), runtime
    )
    await missing.start()
    assert missing.status()["state"] == "unavailable"
    assert not missing.status()["mailbox_ready"]
    await missing.stop()


async def test_plain_supervisor_message_uses_normal_identity_once(
    channel: ChiliarchService,
) -> None:
    envelope = await deliver(channel, "agent.message", {"message": "你好"})
    await eventually(lambda: len(channel.runtime.ai.calls) == 1)
    await eventually(
        lambda: channel.journal.data["events"][envelope.id]["state"] == "completed"
    )
    call = channel.runtime.ai.calls[0]
    assert call["identity"] == "chiliarch_main"
    assert call["user_id"] is None and call["sender_id"] is None
    assert not call["context"].get("webui_session")
    await channel.client._accept(envelope, AsyncMock())
    await asyncio.sleep(0.05)
    assert len(channel.runtime.ai.calls) == 1
    history = await channel.history.get_conversation("main")
    assert history is not None
    assert [m["message"] for m in history["messages"]] == ["你好", "已处理"]
    outgoing = await channel.client.store.pending()
    assert any(
        e.type == "agent.contact" and e.correlation_id == envelope.id for e in outgoing
    )


async def test_tasks_continue_and_reject_workdir(channel: ChiliarchService) -> None:
    await deliver(channel, "task.dispatch", {"task_id": "first", "instruction": "做事"})
    await eventually(lambda: len(channel.runtime.ai.calls) == 1)
    await eventually(lambda: not channel._active)
    await deliver(
        channel,
        "task.dispatch",
        {
            "task_id": "second",
            "instruction": "继续",
            "parameters": {"chiliarch_context": {"continue_task_id": "first"}},
        },
    )
    await eventually(lambda: len(channel.runtime.ai.calls) == 2)
    assert (
        channel.journal.data["tasks"]["first"]
        == channel.journal.data["tasks"]["second"]
    )
    await deliver(
        channel,
        "task.dispatch",
        {"task_id": "wrong-dir", "instruction": "做事", "workdir": "/tmp"},
    )

    async def failed() -> bool:
        return any(
            s == "failed" and e.payload["task_id"] == "wrong-dir"
            for s, e in await channel.client.store.tasks()
        )

    async with asyncio.timeout(5):
        while not await failed():
            await asyncio.sleep(0.01)
    assert len(channel.runtime.ai.calls) == 2
    assert channel.runtime_metadata()["supports_task_workdir"] is False


async def test_cancel_before_dispatch_and_inflight_cleanup(
    channel: ChiliarchService,
) -> None:
    await deliver(channel, "task.cancel", {"task_id": "early"})
    await deliver(
        channel, "task.dispatch", {"task_id": "early", "instruction": "不能执行"}
    )
    entered = asyncio.Event()
    cleanup = asyncio.Event()

    async def slow(question: str, kwargs: dict[str, Any]) -> str:
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleanup.set()
        return "unreachable"

    channel.runtime.ai.handler = slow
    envelope = await deliver(
        channel, "task.dispatch", {"task_id": "slow", "instruction": "等待"}
    )
    await entered.wait()
    await deliver(channel, "task.cancel", {"task_id": "slow"})
    await eventually(lambda: not channel._active)
    states = {
        e.payload["task_id"]: state for state, e in await channel.client.store.tasks()
    }
    assert states["early"] == "cancelled"
    async with asyncio.timeout(5):
        while states.get("slow") != "cancelled":
            await asyncio.sleep(0.01)
            states = {
                e.payload["task_id"]: state
                for state, e in await channel.client.store.tasks()
            }
    assert cleanup.is_set()
    assert len(channel.runtime.ai.calls) == 1
    await channel.client._accept(envelope, AsyncMock())
    assert len(channel.runtime.ai.calls) == 1


async def test_contact_persists_origin_before_native_outbox_and_idempotent(
    channel: ChiliarchService, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = channel.client.store.enqueue

    async def checked(envelope: Any) -> None:
        disk = await io.read_json(channel.journal.path)
        assert isinstance(disk, dict)
        assert disk["routes"][envelope.id]["origin"]["address"] == "qq:123"
        await original(envelope)

    monkeypatch.setattr(channel.client.store, "enqueue", checked)
    context = {"user_id": 123, "request_type": "private"}
    args = {"message": "询问", "client_request_id": "stable"}
    first = await channel.invoke("contact", args, context)
    again = await channel.invoke("contact", args, context)
    assert first == again
    assert (
        len(
            [
                e
                for e in await channel.client.store.pending()
                if e.type == "agent.contact"
            ]
        )
        == 1
    )
    with pytest.raises(ValueError):
        await channel.invoke("contact", {**args, "message": "变更"}, context)
    await deliver(
        channel,
        "agent.message",
        {"message": "已收到"},
        correlation_id=first["message_id"],
    )
    await eventually(
        lambda: channel.runtime.sender.send_address_message.await_count == 1
    )
    address = channel.runtime.sender.send_address_message.call_args.args[0]
    assert address.canonical == "qq:123"
    assert len(channel.runtime.ai.calls) == 0


@pytest.mark.parametrize("address", ["qq:123", "wechat:123", "group:123"])
async def test_reply_returns_to_origin_after_journal_reload(
    channel: ChiliarchService, address: str
) -> None:
    result = await channel.invoke(
        "contact",
        {"message": "询问", "client_request_id": address},
        {"address": address},
    )
    await channel.journal.open()
    await deliver(
        channel,
        "agent.message",
        {"message": "迟到回复"},
        correlation_id=result["message_id"],
    )
    await eventually(
        lambda: channel.runtime.sender.send_address_message.await_count == 1
    )
    assert (
        channel.runtime.sender.send_address_message.call_args.args[0].canonical
        == address
    )
    assert not channel.runtime.ai.calls


async def test_webui_reply_targets_exact_conversation(
    channel: ChiliarchService, tmp_path: Path
) -> None:
    store = WebChatConversationStore(
        directory=tmp_path / "webchat", migrate_legacy=False
    )
    channel.runtime.webchat_store = store
    await store.ensure_ready()
    await store.create_conversation(conversation_id="source")
    await store.create_conversation(conversation_id="other")
    response = await channel.invoke(
        "contact",
        {"message": "询问", "client_request_id": "webui"},
        {"webui_session": True, "webchat_conversation_id": "source"},
    )
    await deliver(
        channel,
        "agent.message",
        {"message": "回信"},
        correlation_id=response["message_id"],
    )
    await eventually(
        lambda: any(
            e.get("delivery") == "delivered"
            for e in channel.journal.data["events"].values()
        )
    )
    source, other = (
        await store.get_conversation("source"),
        await store.get_conversation("other"),
    )
    assert source and len(source["messages"]) == 1
    assert other and not other["messages"]
    await store.stop()


async def test_request_pending_keeps_id_and_origin_scope(
    channel: ChiliarchService,
) -> None:
    origin = {"address": "qq:123"}
    result = await channel.invoke(
        "request",
        {"operation": "list_agents", "arguments": {}, "client_request_id": "discover"},
        origin,
    )
    assert result["status"] == "pending"
    rid = result["request_id"]
    with pytest.raises(ValueError):
        await channel.invoke("get_result", {"request_id": rid}, {"address": "qq:456"})
    await deliver(
        channel,
        "request.resolved",
        {"request_id": rid, "status": "approved", "result": {"agents": []}},
        correlation_id=rid,
    )
    resolved = await channel.invoke("get_result", {"request_id": rid}, origin)
    assert resolved["status"] == "approved"
    assert resolved["request_id"] == rid


async def test_peer_message_does_not_wake_local_ai(channel: ChiliarchService) -> None:
    await deliver(
        channel,
        "collaboration.message",
        {
            "message_id": "peer-msg",
            "sender_agent_id": "peer",
            "sender_role": "agent",
            "recipient_agent_id": "agent-test",
            "message": "我的情况",
            "wake": True,
            "sequence": 1,
        },
    )
    await eventually(lambda: bool(channel.journal.data["events"]))
    await asyncio.sleep(0.05)
    assert not channel.runtime.ai.calls
    history = await channel.history.get_conversation("main")
    assert history and "peer" in history["messages"][0]["message"]


async def test_restart_marks_running_work_interrupted_and_owner_exclusive(
    channel: ChiliarchService,
) -> None:
    second = ChiliarchService(channel.config, channel.runtime)
    await second.start()
    assert second.status()["state"] == "unavailable"
    await second.stop()
    entered = asyncio.Event()

    async def slow(question: str, kwargs: dict[str, Any]) -> str:
        entered.set()
        await asyncio.Event().wait()
        return "unreachable"

    channel.runtime.ai.handler = slow
    await deliver(
        channel, "task.dispatch", {"task_id": "running", "instruction": "等待"}
    )
    await entered.wait()
    await channel.stop()
    channel.runtime.ai.handler = None
    await channel.start()
    states = {
        e.payload["task_id"]: state for state, e in await channel.client.store.tasks()
    }
    assert states["running"] == "interrupted"
    assert len(channel.runtime.ai.calls) == 1


async def test_task_and_plain_chat_share_capacity(channel: ChiliarchService) -> None:
    entered = asyncio.Event()
    release = asyncio.Event()

    async def slow(question: str, kwargs: dict[str, Any]) -> str:
        entered.set()
        await release.wait()
        return "done"

    channel.runtime.ai.handler = slow
    await deliver(channel, "task.dispatch", {"task_id": "busy", "instruction": "任务"})
    await entered.wait()
    await deliver(channel, "agent.message", {"message": "普通消息"})
    await asyncio.sleep(0.05)
    assert len(channel.runtime.ai.calls) == 1
    heartbeat = await channel.client.heartbeat()
    assert heartbeat.payload["metadata"]["local_active_sessions"] == 1
    assert heartbeat.payload["metadata"]["state"] == "busy"
    release.set()
    await eventually(lambda: len(channel.runtime.ai.calls) == 2)


async def test_native_transport_falls_back_and_revocation_clears_ready(
    channel: ChiliarchService, monkeypatch: pytest.MonkeyPatch
) -> None:
    await channel.stop()
    calls: list[str] = []

    async def ws(client: Any) -> None:
        calls.append("ws")
        raise OSError("blocked")

    async def sse(client: Any) -> None:
        calls.append("sse")
        raise OSError("blocked")

    async def poll(client: Any) -> None:
        calls.append("poll")
        raise native.CredentialRejected("revoked-secret-must-not-appear")

    monkeypatch.setattr(native.AgentClient, "_ws", ws)
    monkeypatch.setattr(native.AgentClient, "_sse", sse)
    monkeypatch.setattr(native.AgentClient, "_poll", poll)
    options = native.TransportSettings(
        reconnect_base_seconds=0.001, reconnect_max_seconds=0.001
    )
    original = native.AgentClient.from_state

    async def factory(*args: Any, **kwargs: Any) -> Any:
        kwargs["options"] = options
        return await original(*args, **kwargs)

    monkeypatch.setattr(native.AgentClient, "from_state", factory)
    await channel.start()
    await eventually(lambda: channel.status()["state"] == "unavailable")
    assert calls == ["ws", "sse", "poll"]
    assert channel.status()["reason"] == "CredentialRejected"
    assert "secret" not in json.dumps(channel.status())
    await eventually(lambda: not channel.status()["mailbox_ready"])


def test_capture_origin_does_not_reinterpret_internal_identity() -> None:
    assert (
        capture_origin(
            {"logical_identity": "chiliarch_main", "logical_conversation_id": "room"}
        )["kind"]
        == "logical"
    )
    with pytest.raises(ValueError):
        capture_origin({})


async def test_file_roundtrip_native_checks_cache_and_scope(
    channel: ChiliarchService, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    content = b"native transfer data with several chunks"
    uploaded: dict[int, bytes] = {}
    reads: list[int] = []
    artifact = {
        "id": "shared",
        "name": "example.txt",
        "state": "ready",
        "size": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
        "chunk_bytes": 8,
    }
    original = channel.client.store.enqueue_request

    async def platform(envelope: Any, client_request_id: str | None = None) -> str:
        rid = await original(envelope, client_request_id)
        op, args = envelope.payload["operation"], envelope.payload["arguments"]
        result: dict[str, Any]
        if op == "list_artifacts":
            result = {"limits": {"max_artifact_bytes": 1000}}
        elif op == "begin_artifact_upload":
            result = {"upload_id": "upload"}
        elif op == "get_artifact":
            result = {
                "artifact": {
                    **artifact,
                    "state": "uploading"
                    if args["artifact_id"] == "upload"
                    else "ready",
                },
                "uploaded_chunks": sorted(uploaded),
            }
        elif op == "put_artifact_chunk":
            uploaded[args["index"]] = base64.b64decode(args["data_base64"])
            result = {}
        elif op == "finish_artifact_upload":
            assert b"".join(uploaded[i] for i in sorted(uploaded)) == content
            result = {"artifact": artifact}
        else:
            assert op == "read_artifact_chunk"
            index = args["index"]
            reads.append(index)
            chunk = content[index * 8 : (index + 1) * 8]
            result = {
                "data_base64": base64.b64encode(chunk).decode(),
                "sha256": hashlib.sha256(chunk).hexdigest(),
            }
        await deliver(
            channel,
            "request.resolved",
            {"request_id": rid, "status": "approved", "result": result},
            correlation_id=rid,
        )
        return str(rid)

    monkeypatch.setattr(channel.client.store, "enqueue_request", platform)
    registry = AttachmentRegistry(
        registry_path=tmp_path / "registry.json", cache_dir=tmp_path / "cache"
    )
    channel.runtime.ai.attachment_registry = registry
    source = tmp_path / "source.txt"
    await io.write_bytes(source, content)
    context = {"address": "qq:123", "user_id": 123, "request_type": "private"}
    uploaded_result = await channel.invoke(
        "upload_artifact",
        {"path": str(source), "members": [], "client_request_id": "file-1"},
        context,
    )
    assert uploaded_result["status"] == "completed"
    result = await channel.invoke(
        "download_artifact", {"artifact_id": "shared"}, context
    )
    assert result["status"] == "completed" and result["attachment"].startswith(
        "<attachment"
    )
    assert "data_base64" not in json.dumps(result)
    record = await registry.resolve_async(result["uid"], "private:123")
    assert record and record.local_path
    assert await io.read_bytes(record.local_path) == content
    assert await registry.resolve_async(result["uid"], "private:456") is None
    count = len(reads)
    cached = await channel.invoke(
        "download_artifact", {"artifact_id": "shared"}, context
    )
    assert cached["uid"] == result["uid"] and len(reads) == count
    await io.write_bytes(result["destination"], b"corrupt")
    with pytest.raises(ValueError, match="校验失败"):
        await channel.invoke("download_artifact", {"artifact_id": "shared"}, context)


async def test_queued_chat_survives_stop_without_replaying_running_work(
    channel: ChiliarchService,
) -> None:
    entered = asyncio.Event()

    async def blocked(question: str, kwargs: dict[str, Any]) -> str:
        entered.set()
        await asyncio.Event().wait()
        return "unreachable"

    channel.runtime.ai.handler = blocked
    first = await deliver(channel, "agent.message", {"message": "第一条"})
    await entered.wait()
    second = await deliver(channel, "agent.message", {"message": "第二条"})
    await eventually(lambda: second.id in channel.journal.data["events"])
    await channel.stop()
    assert channel.journal.data["events"][first.id]["state"] == "interrupted"
    assert channel.journal.data["events"][second.id]["state"] == "queued"
    channel.runtime.ai.handler = None
    await channel.start()
    await eventually(
        lambda: channel.journal.data["events"][second.id]["state"] == "completed"
    )
    assert len(channel.runtime.ai.calls) == 2


async def test_peer_receipts_waits_and_message_cursor(
    channel: ChiliarchService,
) -> None:
    origin = {"address": "wechat:123"}
    operations: list[tuple[str, dict[str, Any]]] = [
        ("send_peer_message", {"recipient_agent_id": "peer", "message": "协作"}),
        (
            "acknowledge_peer_message",
            {"message_id": "peer-message", "state": "processed"},
        ),
        ("wait_for_tasks", {"waiting_for": ["peer-task"], "reason": "依赖"}),
    ]
    for action, args in operations:
        response = await channel.invoke(
            action, {**args, "client_request_id": action}, origin
        )
        assert response["status"] == "pending"
        outgoing = (await channel.client.store.pending())[-1]
        assert outgoing.payload["operation"] == action
        if action == "send_peer_message":
            assert outgoing.payload["arguments"]["wake"] is False
        await deliver(
            channel,
            "request.resolved",
            {"request_id": response["request_id"], "status": "approved", "result": {}},
            correlation_id=response["request_id"],
        )
    inbox = await channel.invoke("read_messages", {}, origin)
    assert len(inbox["messages"]) == 3
    assert not (await channel.invoke("read_messages", {}, {"address": "qq:456"}))[
        "messages"
    ]
    await channel.invoke("acknowledge_messages", {"cursor": inbox["cursor"]}, origin)
    assert not (await channel.invoke("read_messages", {}, origin))["messages"]


async def test_managed_progress_and_result_keep_current_task(
    channel: ChiliarchService,
) -> None:
    async def perform(question: str, kwargs: dict[str, Any]) -> str:
        context = kwargs["extra_context"]
        assert context["chiliarch_task_id"] == "managed"
        await channel.invoke(
            "progress", {"progress": 0.5, "message": "进行中"}, context
        )
        await kwargs["send_message_callback"]("阶段输出")
        return "最终结果"

    channel.runtime.ai.handler = perform
    await deliver(
        channel, "task.dispatch", {"task_id": "managed", "instruction": "汇报进度"}
    )
    async with asyncio.timeout(5):
        while True:
            states = {
                command.payload["task_id"]: state
                for state, command in await channel.client.store.tasks()
            }
            if states.get("managed") == "completed":
                break
            await asyncio.sleep(0.01)
    outgoing = await channel.client.store.pending()
    assert any(
        e.type == "task.status" and e.payload.get("progress") == 0.5 for e in outgoing
    )
    result = next(
        e
        for e in outgoing
        if e.type == "task.status" and e.payload["status"] == "completed"
    )
    assert result.payload["result"]["reply"] == "阶段输出\n最终结果"
    origin = {
        "logical_identity": "chiliarch_main",
        "logical_conversation_id": channel.journal.data["tasks"]["managed"],
        "chiliarch_task_id": "managed",
    }
    with pytest.raises(ValueError, match="已停止"):
        await channel.invoke(
            "contact", {"message": "不能发", "client_request_id": "stopped"}, origin
        )
