from __future__ import annotations

from typing import Any
from types import SimpleNamespace

import pytest

from Undefined.context import RequestContext
from Undefined.skills.tools.end.handler import execute
from Undefined.utils.message_turn import mark_message_sent_this_turn


@pytest.mark.asyncio
async def test_end_accepts_force_string_true_case_insensitive() -> None:
    context: dict[str, Any] = {"request_id": "req-force-true"}

    result = await execute(
        {"memo": "已发送消息", "force": "TrUe"},
        context,
    )

    assert result == "对话已结束"
    assert context["conversation_ended"] is True


@pytest.mark.asyncio
async def test_end_rejects_when_force_string_false_and_no_message_sent() -> None:
    context: dict[str, Any] = {"request_id": "req-force-false"}

    result = await execute(
        {"memo": "已发送消息", "force": "FaLsE"},
        context,
    )

    assert result.startswith("拒绝结束对话")
    assert context.get("conversation_ended") is not True


@pytest.mark.asyncio
async def test_end_accepts_message_sent_flag_from_context_string_true() -> None:
    context: dict[str, Any] = {
        "request_id": "req-message-flag",
        "message_sent_this_turn": "TRUE",
    }

    result = await execute({"memo": "已发送消息"}, context)

    assert result == "对话已结束"
    assert context["conversation_ended"] is True


@pytest.mark.asyncio
async def test_end_accepts_message_sent_flag_from_request_context_string_true() -> None:
    context: dict[str, Any] = {"request_id": "req-request-context-flag"}

    async with RequestContext(request_type="group", group_id=1, sender_id=2) as req_ctx:
        req_ctx.set_resource("message_sent_this_turn", "YeS")
        result = await execute({"memo": "已发送消息"}, context)

    assert result == "对话已结束"
    assert context["conversation_ended"] is True


@pytest.mark.asyncio
async def test_end_accepts_message_sent_flag_from_copied_tool_context() -> None:
    send_context: dict[str, Any] = {"request_id": "req-send-copy"}
    end_context: dict[str, Any] = {"request_id": "req-end-copy"}

    async with RequestContext(request_type="private", user_id=42):
        mark_message_sent_this_turn(send_context)
        result = await execute({"memo": "已发送消息"}, end_context)

    assert send_context["message_sent_this_turn"] is True
    assert "message_sent_this_turn" not in end_context
    assert result == "对话已结束"
    assert end_context["conversation_ended"] is True


class _FakeHistoryManager:
    def get_recent(
        self, chat_id: str, msg_type: str, start: int, end: int
    ) -> list[dict[str, Any]]:
        assert chat_id == "1082837821"
        assert msg_type == "group"
        return [
            {
                "timestamp": "2026-02-23 19:02:11",
                "display_name": "洛泫",
                "user_id": "120218451",
                "message": "Null 说这个是竞态问题",
            }
        ]


class _FakeCognitiveService:
    def __init__(self) -> None:
        self.last_context: dict[str, Any] | None = None
        self.last_force: bool | None = None
        self.last_memo = ""
        self.last_observations: list[str] = []

    async def enqueue_job(
        self,
        memo: str,
        observations: list[str],
        context: dict[str, Any],
        *,
        force: bool = False,
    ) -> str:
        self.last_context = dict(context)
        self.last_force = bool(force)
        self.last_memo = memo
        self.last_observations = list(observations)
        return "job-test"


@pytest.mark.asyncio
async def test_end_ignores_removed_legacy_param_names() -> None:
    cognitive_service = _FakeCognitiveService()
    context: dict[str, Any] = {
        "request_id": "req-removed-compat",
        "cognitive_service": cognitive_service,
    }

    result = await execute(
        {
            "action_summary": "旧字段不应写入 memo",
            "summary": "旧摘要字段不应写入 memo",
            "new_info": ["旧字段不应写入 observations"],
            "force": True,
        },
        context,
    )

    assert result == "对话已结束"
    assert context["conversation_ended"] is True
    assert cognitive_service.last_context is None


@pytest.mark.asyncio
async def test_end_normalizes_undefined_project_name_misspellings() -> None:
    cognitive_service = _FakeCognitiveService()
    context: dict[str, Any] = {
        "request_id": "req-normalize-project-name",
        "cognitive_service": cognitive_service,
    }

    result = await execute(
        {
            "memo": "已解释 Unfined 的记忆架构",
            "observations": [
                "QQ号42（昵称system）在 WebUI 询问 Unfined 是否了解自身记忆架构",
                "QQ号42（昵称system）提到 Undefind 的分层架构",
                "QQ号42（昵称system）继续讨论 undefind",
            ],
            "force": True,
        },
        context,
    )

    assert result == "对话已结束"
    assert cognitive_service.last_memo == "已解释 Undefined 的记忆架构"
    assert cognitive_service.last_observations == [
        "QQ号42（昵称system）在 WebUI 询问 Undefined 是否了解自身记忆架构",
        "QQ号42（昵称system）提到 Undefined 的分层架构",
        "QQ号42（昵称system）继续讨论 Undefined",
    ]


@pytest.mark.asyncio
async def test_end_enriches_historian_reference_context() -> None:
    cognitive_service = _FakeCognitiveService()
    context: dict[str, Any] = {
        "request_id": "req-historian-context",
        "request_type": "group",
        "group_id": "1082837821",
        "user_id": "120218451",
        "sender_id": "120218451",
        "history_manager": _FakeHistoryManager(),
        "cognitive_service": cognitive_service,
        "current_question": (
            '<message sender="洛泫" sender_id="120218451" group_id="1082837821" '
            'group_name="bot测试群" location="bot测试群" time="2026-02-23 19:02:12">'
            "<content>Null(1708213363)说发现了一个竞态问题</content></message>"
        ),
    }

    result = await execute(
        {"observations": ["Null(1708213363)说发现了一个竞态问题"], "force": True},
        context,
    )

    assert result == "对话已结束"
    assert context["conversation_ended"] is True
    assert (
        context.get("historian_source_message")
        == "Null(1708213363)说发现了一个竞态问题"
    )
    assert context.get("historian_recent_messages")
    assert cognitive_service.last_context is not None
    assert cognitive_service.last_context.get("historian_source_message")
    assert cognitive_service.last_context.get("historian_recent_messages")
    assert cognitive_service.last_force is True


@pytest.mark.asyncio
async def test_end_historian_source_decodes_wechat_cdata() -> None:
    cognitive_service = _FakeCognitiveService()
    context: dict[str, Any] = {
        "request_id": "req-historian-wechat-cdata",
        "request_type": "private",
        "user_id": "12345",
        "sender_id": "12345",
        "cognitive_service": cognitive_service,
        "current_question": (
            '<message message_id="wechat-1" sender="微信用户" sender_id="12345" '
            'channel="wechat" address="wechat:12345" location="微信私聊">'
            "<content><![CDATA[比较 1 < 2 & 3 > 2，保留 ]]]]><![CDATA[> 字符]]>"
            "</content></message>"
        ),
    }

    result = await execute(
        {"observations": ["QQ号12345通过微信讨论特殊字符"], "force": True},
        context,
    )

    assert result == "对话已结束"
    assert context["historian_source_message"] == ("比较 1 < 2 & 3 > 2，保留 ]]> 字符")


@pytest.mark.asyncio
async def test_end_historian_source_message_includes_batched_messages() -> None:
    cognitive_service = _FakeCognitiveService()
    context: dict[str, Any] = {
        "request_id": "req-historian-batch",
        "request_type": "group",
        "group_id": "1082837821",
        "user_id": "120218451",
        "sender_id": "120218451",
        "cognitive_service": cognitive_service,
        "current_question": (
            '<message message_id="101" sender="洛泫" sender_id="120218451" '
            'group_id="1082837821" group_name="bot测试群" '
            'location="bot测试群" time="2026-02-23 19:02:12">'
            "<content>我周三要发版</content></message>"
            '<message message_id="102" sender="洛泫" sender_id="120218451" '
            'group_id="1082837821" group_name="bot测试群" '
            'location="bot测试群" time="2026-02-23 19:02:14">'
            "<content>补充：是后端服务发版</content></message>"
            "\n\n 【连续消息说明】以上 2 条 <message> 共同构成【当前输入批次】"
        ),
    }

    result = await execute(
        {"observations": ["洛泫周三要进行后端服务发版"], "force": True},
        context,
    )

    assert result == "对话已结束"
    source = str(context.get("historian_source_message", ""))
    assert "[1]" in source
    assert "[2]" in source
    assert "message_id=101" in source
    assert "message_id=102" in source
    assert "我周三要发版" in source
    assert "补充：是后端服务发版" in source
    assert cognitive_service.last_context is not None
    assert cognitive_service.last_context.get("historian_source_message") == source


class _ManyHistoryManager:
    def get_recent(
        self, chat_id: str, msg_type: str, start: int, end: int
    ) -> list[dict[str, Any]]:
        return [
            {
                "timestamp": "2026-02-23 19:02:11",
                "display_name": "洛泫",
                "user_id": "120218451",
                "message": f"line-{i}-" + ("x" * 200),
            }
            for i in range(20)
        ]


class _DuplicateCurrentBatchHistoryManager:
    def get_recent(
        self, chat_id: str, msg_type: str, start: int, end: int
    ) -> list[dict[str, Any]]:
        _ = chat_id, msg_type, start, end
        return [
            {
                "type": "group",
                "message_id": "100",
                "timestamp": "2026-02-23 19:01:00",
                "display_name": "旁观者",
                "user_id": "99999",
                "chat_id": "1082837821",
                "chat_name": "bot测试群",
                "message": "保留的旧历史",
            },
            {
                "type": "group",
                "message_id": "101",
                "timestamp": "2026-02-23 19:02:12",
                "display_name": "洛泫",
                "user_id": "120218451",
                "chat_id": "1082837821",
                "chat_name": "bot测试群",
                "message": "我周三要发版",
            },
            {
                "type": "group",
                "message_id": "102",
                "timestamp": "2026-02-23 19:02:14",
                "display_name": "洛泫",
                "user_id": "120218451",
                "chat_id": "1082837821",
                "chat_name": "bot测试群",
                "message": "补充：是后端服务发版",
            },
        ]


@pytest.mark.asyncio
async def test_end_historian_recent_messages_drops_current_batch_duplicates() -> None:
    cognitive_service = _FakeCognitiveService()
    context: dict[str, Any] = {
        "request_id": "req-historian-drop-current-batch",
        "request_type": "group",
        "group_id": "1082837821",
        "user_id": "120218451",
        "sender_id": "120218451",
        "history_manager": _DuplicateCurrentBatchHistoryManager(),
        "cognitive_service": cognitive_service,
        "current_question": (
            '<message message_id="101" sender="洛泫" sender_id="120218451" '
            'group_id="1082837821" group_name="bot测试群" '
            'location="bot测试群" time="2026-02-23 19:02:12">'
            "<content>我周三要发版</content></message>"
            '<message message_id="102" sender="洛泫" sender_id="120218451" '
            'group_id="1082837821" group_name="bot测试群" '
            'location="bot测试群" time="2026-02-23 19:02:14">'
            "<content>补充：是后端服务发版</content></message>"
            "\n\n 【连续消息说明】以上 2 条 <message> 共同构成【当前输入批次】"
        ),
    }

    result = await execute(
        {"observations": ["洛泫周三要进行后端服务发版"], "force": True},
        context,
    )

    assert result == "对话已结束"
    recent = context.get("historian_recent_messages", [])
    assert isinstance(recent, list)
    recent_text = "\n".join(str(item) for item in recent)
    assert "保留的旧历史" in recent_text
    assert "我周三要发版" not in recent_text
    assert "补充：是后端服务发版" not in recent_text
    assert cognitive_service.last_context is not None
    assert cognitive_service.last_context.get("historian_recent_messages") == recent


@pytest.mark.asyncio
async def test_end_uses_runtime_config_for_historian_reference_limits() -> None:
    cognitive_service = _FakeCognitiveService()
    runtime_config = SimpleNamespace(
        cognitive=SimpleNamespace(
            historian_source_message_max_len=40,
        ),
        get_context_recent_messages_limit=lambda: 2,
    )
    long_content = "A" * 300
    context: dict[str, Any] = {
        "request_id": "req-historian-limits",
        "request_type": "group",
        "group_id": "1082837821",
        "user_id": "120218451",
        "sender_id": "120218451",
        "history_manager": _ManyHistoryManager(),
        "cognitive_service": cognitive_service,
        "runtime_config": runtime_config,
        "current_question": (
            '<message sender="洛泫" sender_id="120218451" group_id="1082837821" '
            'group_name="bot测试群" location="bot测试群" time="2026-02-23 19:02:12">'
            f"<content>{long_content}</content></message>"
        ),
    }

    await execute({"observations": ["测试"], "force": True}, context)

    source = str(context.get("historian_source_message", ""))
    recent = context.get("historian_recent_messages", [])
    assert len(source) <= 40
    assert isinstance(recent, list)
    assert len(recent) == 2
    # Recent messages now use XML format (same as main AI)
    for line in recent:
        assert "<message" in str(line)
        assert "<content>" in str(line)
