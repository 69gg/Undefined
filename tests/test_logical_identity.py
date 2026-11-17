from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from Undefined.api.webchat_store import WebChatConversationStore
from Undefined.attachments import scope_from_context
from Undefined.channels.session import run_logical_chat
from Undefined.cognitive.historian import HistorianWorker
from Undefined.cognitive.profile_storage import ProfileStorage
from Undefined.cognitive.service import CognitiveService
from Undefined.config import Config
from Undefined.context import RequestContext
from Undefined.skills.tools.end.handler import execute as end
from Undefined.skills.toolsets.messages.send_message.handler import execute as send


@pytest.mark.parametrize("history_fails", [False, True])
async def test_logical_chat_uses_normal_end_and_independent_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, history_fails: bool
) -> None:
    queue = SimpleNamespace(enqueue=AsyncMock(return_value="job"))
    cognitive = CognitiveService(
        config_getter=lambda: SimpleNamespace(enabled=True, bot_name="Undefined"),
        vector_store=None,
        job_queue=queue,
        profile_storage=None,
        reranker=None,
    )
    cfg = Config.from_mapping({"core": {"superadmin_qq": 123}}, strict=False)
    store = WebChatConversationStore(
        directory=tmp_path / "chat",
        user_id="chiliarch_main",
        user_name="总管",
        migrate_legacy=False,
    )
    await store.ensure_ready()
    await store.create_conversation(conversation_id="one")
    await store.append_message(
        "one",
        role="user",
        text_content="之前的事实",
        display_name="总管",
        user_name="总管",
    )
    output = AsyncMock()
    if history_fails:
        append = store.append_message

        async def append_with_failed_bot_history(
            conversation_id: str, **kwargs: Any
        ) -> dict[str, Any]:
            if kwargs["role"] == "bot":
                raise OSError("history unavailable after delivery")
            return await append(conversation_id, **kwargs)

        monkeypatch.setattr(store, "append_message", append_with_failed_bot_history)

    async def ask(question: str, **kwargs: Any) -> str:
        ctx = RequestContext.require()
        assert ctx.user_id is None and ctx.sender_id is None
        assert ctx.logical_identity == "chiliarch_main"
        context = {
            **ctx.get_resources(),
            **kwargs["extra_context"],
            "current_question": question,
        }
        assert context["queue_lane"] == "private"
        assert not context.get("webui_session")
        assert "之前的事实" in str(kwargs["recent_messages_snapshot"])
        assert await send({"message": "记住了"}, context) == "消息已排队"
        assert ctx.get_resources()["message_sent_this_turn"] is True
        assert (
            await end({"observations": ["chiliarch_main 正在协调项目"]}, context)
            == "对话已结束"
        )
        assert context["conversation_ended"] is True
        return ""

    runtime = SimpleNamespace(
        ai=SimpleNamespace(ask=ask, runtime_config=cfg),
        onebot=SimpleNamespace(),
        sender=SimpleNamespace(),
        scheduler=None,
        cognitive_service=cognitive,
    )
    try:
        result = await run_logical_chat(
            runtime,
            store=store,
            identity="chiliarch_main",
            display_name="总管",
            conversation_id="one",
            text="正在协调项目",
            send_output=output,
        )
        assert result == "记住了"
        output.assert_awaited_once_with("记住了")
        job = queue.enqueue.call_args.args[0]
        assert job["sender_id"] == "chiliarch_main"
        assert job["profile_targets"] == [
            {
                "entity_type": "user",
                "entity_id": "chiliarch_main",
                "perspective": "sender",
                "preferred_name": "总管",
            }
        ]
        assert "之前的事实" in str(job["recent_messages"])
        assert "正在协调项目" in job["source_message"]
        await store.create_conversation(conversation_id="two")
        assert store.adapter("two").get_recent("chiliarch_main", "private", 0, 20) == []
        assert store.adapter("one").get_recent("42", "private", 0, 20) == []
    finally:
        await store.stop()


@pytest.mark.parametrize("address", ["qq:123", "wechat:123", "group:123"])
async def test_explicit_physical_address_still_checks_acl(address: str) -> None:
    output = AsyncMock()
    sender = SimpleNamespace(send_address_message=AsyncMock())
    cfg = Config.from_mapping(
        {
            "access": {
                "mode": "blacklist",
                "blocked_private_ids": [123],
                "blocked_group_ids": [123],
            }
        },
        strict=False,
    )
    result = await send(
        {"message": "你好", "address": address},
        {
            "logical_identity": "chiliarch_main",
            "session_send_callback": output,
            "runtime_config": cfg,
            "sender": sender,
        },
    )
    assert "访问控制" in result
    output.assert_not_awaited()
    sender.send_address_message.assert_not_awaited()


def test_logical_attachment_scope_isolates_identity_and_conversation() -> None:
    base = {"logical_identity": "chiliarch_main", "logical_conversation_id": "one"}
    scopes = {
        scope_from_context(base),
        scope_from_context({**base, "logical_conversation_id": "two"}),
        scope_from_context({**base, "logical_identity": "other"}),
        scope_from_context({"webui_session": True}),
        scope_from_context({"user_id": 42}),
    }
    assert len(scopes) == 5 and None not in scopes


@pytest.mark.parametrize(
    "identity,field", [("chiliarch_main", "identity"), ("123", "qq")]
)
async def test_historian_profile_keeps_real_identity(
    tmp_path: Path, identity: str, field: str
) -> None:
    storage = ProfileStorage(tmp_path)
    worker = HistorianWorker(
        ai_client=cast(Any, SimpleNamespace()),
        config_getter=lambda: SimpleNamespace(enabled=True),
        vector_store=SimpleNamespace(upsert_profile=AsyncMock()),
        job_queue=cast(Any, SimpleNamespace()),
        profile_storage=storage,
    )
    await worker._write_profile(
        entity_type="user",
        entity_id=identity,
        effective_name="名称",
        tags=[],
        summary="事实",
        evaluation="评价",
        roast="",
        event_id="event",
        perspective="sender",
    )
    content = await storage.read_profile("user", identity)
    assert content and f"{field}:" in content
    if field == "identity":
        assert "qq:" not in content


@pytest.mark.parametrize("identity", ["chiliarch_main", "agent-with.dots"])
@pytest.mark.parametrize("explicit_target", [False, True])
async def test_historian_merge_accepts_storage_ids_and_keeps_target_boundary(
    tmp_path: Path, identity: str, explicit_target: bool
) -> None:
    storage = ProfileStorage(tmp_path)
    snapshot = "目标旧侧写"
    await storage.write_profile("user", identity, snapshot)
    await storage.write_profile("user", "other_peer", "其他用户侧写")

    def tool(call_id: str, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": call_id,
            "function": {"name": name, "arguments": json.dumps(arguments)},
        }

    update: dict[str, Any] = {
        "summary": "已合并的新事实",
        "evaluation": "协作有序",
        "roast": "总在安排下一件事",
    }
    if explicit_target:
        update.update(entity_type="user", entity_id=identity)
    reads = [
        tool("self", "read_profile", {"entity_type": "user", "entity_id": identity}),
        tool(
            "peer", "read_profile", {"entity_type": "user", "entity_id": "other_peer"}
        ),
        tool(
            "bad-read",
            "read_profile",
            {"entity_type": "user", "entity_id": "../escape"},
        ),
        tool(
            "bad-write",
            "update_profile",
            {"entity_type": "user", "entity_id": "../escape"},
        ),
        tool(
            "wrong-target",
            "update_profile",
            {"entity_type": "user", "entity_id": "other_peer"},
        ),
    ]
    submit = AsyncMock(
        side_effect=[
            {"choices": [{"message": {"tool_calls": reads}}]},
            {
                "choices": [
                    {
                        "message": {
                            "tool_calls": [tool("update", "update_profile", update)]
                        }
                    }
                ]
            },
        ]
    )
    worker = HistorianWorker(
        ai_client=cast(
            Any,
            SimpleNamespace(agent_config=object(), submit_background_llm_call=submit),
        ),
        config_getter=lambda: SimpleNamespace(),
        vector_store=SimpleNamespace(
            embed_query=AsyncMock(return_value=[0.1]),
            query_events=AsyncMock(return_value=[]),
            upsert_profile=AsyncMock(),
        ),
        job_queue=None,
        profile_storage=storage,
    )
    assert await worker._merge_profile_target(
        job={
            "observations": ["协作事实"],
            "request_type": "private",
            "sender_id": identity,
        },
        canonical="协作事实",
        event_id="merge",
        target={
            "entity_type": "user",
            "entity_id": identity,
            "perspective": "sender",
            "preferred_name": "总管",
        },
        target_index=1,
        target_count=1,
    )
    results = {
        message["tool_call_id"]: message["content"]
        for message in submit.call_args_list[1].kwargs["messages"]
        if message.get("role") == "tool"
    }
    assert results["self"] == snapshot
    assert results["peer"] == "其他用户侧写"
    assert "无效" in results["bad-read"]
    assert "无效" in results["bad-write"]
    assert "只能更新本次目标实体" in results["wrong-target"]
    content = await storage.read_profile("user", identity)
    assert content and "已合并的新事实" in content
    assert "identity:" in content and "qq:" not in content
    assert await storage.read_profile("user", "other_peer") == "其他用户侧写"
