from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from Undefined.automations.address import (
    resolve_live_event_address,
    resolve_task_address,
)
from Undefined.automations.constants import SELF_CALL_TOOL_NAME
from Undefined.automations.match import AutomationEvent
from Undefined.automations.service import AutomationService
from Undefined.automations.validate import AutomationValidationError
from Undefined.utils import io as async_io


class _DummyStorage:
    def load_tasks(self) -> dict[str, Any]:
        return {}

    async def save_all(self, _tasks: dict[str, Any]) -> None:
        return None


def _make_service(
    *,
    ai: Any | None = None,
    sender: Any | None = None,
    onebot: Any | None = None,
) -> AutomationService:
    return AutomationService(
        ai
        or SimpleNamespace(
            ask=AsyncMock(),
            memory_storage=SimpleNamespace(),
            runtime_config=SimpleNamespace(),
        ),
        sender
        or SimpleNamespace(
            send_group_message=AsyncMock(),
            send_private_message=AsyncMock(),
        ),
        onebot
        or SimpleNamespace(
            send_like=AsyncMock(),
            get_image=AsyncMock(return_value=None),
            get_forward_msg=AsyncMock(return_value=[]),
        ),
        SimpleNamespace(),
        storage=cast(Any, _DummyStorage()),
    )


def test_resolve_task_address_rejects_conflicting_legacy_target() -> None:
    with pytest.raises(ValueError, match="address 与旧目标参数指向不同会话"):
        resolve_task_address("wechat:12345", 12345, "private")


def test_resolve_task_address_preserves_address_and_legacy_only_paths() -> None:
    address_only = resolve_task_address("wechat:12345", None, "private")
    legacy_only = resolve_task_address(None, 12345, "private")
    matching_targets = resolve_task_address("group:12345", 12345, "group")

    assert address_only is not None
    assert address_only.canonical == "wechat:12345"
    assert legacy_only is not None
    assert legacy_only.canonical == "qq:12345"
    assert matching_targets is not None
    assert matching_targets.canonical == "group:12345"


def test_resolve_live_event_address_prefers_event_session() -> None:
    group = resolve_live_event_address(
        address="group:1017148870",
        channel="group",
        group_id=1017148870,
        user_id=2608261902,
    )
    wechat = resolve_live_event_address(
        address="wechat:12345",
        channel="wechat",
        user_id=12345,
    )
    private = resolve_live_event_address(
        address="",
        channel="private",
        user_id=10001,
    )
    assert group is not None
    assert group.canonical == "group:1017148870"
    assert wechat is not None
    assert wechat.canonical == "wechat:12345"
    assert private is not None
    assert private.canonical == "qq:10001"


@pytest.mark.asyncio
async def test_execute_tool_injects_cognitive_service() -> None:
    captured: list[Any] = []
    cognitive = SimpleNamespace(enabled=True)

    async def execute_tool(
        name: str, args: dict[str, Any], context: dict[str, Any]
    ) -> str:
        _ = name, args
        captured.append(context.get("cognitive_service"))
        return "ok"

    ai = SimpleNamespace(
        tool_manager=SimpleNamespace(execute_tool=execute_tool),
        _cognitive_service=cognitive,
        memory_storage=SimpleNamespace(),
        runtime_config=SimpleNamespace(),
    )
    service = _make_service(ai=ai)
    try:
        result = await service._execute_tool("cognitive.get_profile", {}, {})
    finally:
        service.shutdown()

    assert result == "ok"
    assert captured == [cognitive]


@pytest.mark.asyncio
async def test_execute_tool_keeps_explicit_cognitive_service() -> None:
    captured: list[Any] = []
    injected = SimpleNamespace(enabled=True, source="context")
    owned = SimpleNamespace(enabled=True, source="ai")

    async def execute_tool(
        name: str, args: dict[str, Any], context: dict[str, Any]
    ) -> str:
        _ = name, args
        captured.append(context.get("cognitive_service"))
        return "ok"

    ai = SimpleNamespace(
        tool_manager=SimpleNamespace(execute_tool=execute_tool),
        _cognitive_service=owned,
        memory_storage=SimpleNamespace(),
        runtime_config=SimpleNamespace(),
    )
    service = _make_service(ai=ai)
    try:
        await service._execute_tool(
            "cognitive.get_profile",
            {},
            {"cognitive_service": injected},
        )
    finally:
        service.shutdown()

    assert captured == [injected]


@pytest.mark.asyncio
async def test_event_workflow_injects_live_session_into_tool_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[dict[str, Any]] = []

    async def execute_tool(
        name: str, args: dict[str, Any], context: dict[str, Any]
    ) -> str:
        _ = name, args
        captured.append(
            {
                "group_id": context.get("group_id"),
                "user_id": context.get("user_id"),
                "sender_id": context.get("sender_id"),
                "address": context.get("address"),
                "request_type": context.get("request_type"),
                "channel": context.get("channel"),
            }
        )
        return "ok"

    monkeypatch.setattr(
        "Undefined.automations.service.collect_context_resources",
        lambda values: {
            key: values[key]
            for key in (
                "send_message_callback",
                "sender",
                "history_manager",
                "onebot_client",
            )
            if key in values
        },
    )
    ai = SimpleNamespace(
        tool_manager=SimpleNamespace(
            execute_tool=execute_tool,
            get_openai_tools=lambda: [],
        ),
        memory_storage=SimpleNamespace(),
        runtime_config=SimpleNamespace(),
        ask=AsyncMock(return_value=""),
        submit_queued_llm_call=AsyncMock(return_value={"choices": []}),
        agent_config=SimpleNamespace(max_tokens=16),
    )
    sender = SimpleNamespace(
        send_group_message=AsyncMock(),
        send_private_message=AsyncMock(),
        send_address_message=AsyncMock(),
    )
    service = _make_service(ai=ai, sender=sender)
    service.tasks["testtoviolet"] = {
        "task_id": "testtoviolet",
        "task_name": "测试群祸害紫罗兰",
        "enabled": True,
        "consume_ai_loop": True,
        "auto_send_final": False,
        "address": "qq:999",
        "nodes": [
            {
                "id": "start",
                "type": "start",
                "kind": "message",
                "channels": ["group"],
                "group_ids": [1017148870],
                "text": "",
            },
            {
                "id": "tool_1",
                "type": "tool",
                "tool_name": "cognitive.get_profile",
                "args": {"entity_id": "2608261902"},
            },
        ],
        "edges": [{"from": "start", "to": "tool_1"}],
    }
    try:
        consumed = await service.handle_event(
            AutomationEvent(
                kind="message",
                channel="group",
                text="hi",
                sender_id=2608261902,
                group_id=1017148870,
                address="group:1017148870",
            )
        )
    finally:
        service.shutdown()

    assert consumed is True
    assert captured == [
        {
            "group_id": 1017148870,
            "user_id": 2608261902,
            "sender_id": 2608261902,
            "address": "group:1017148870",
            "request_type": "group",
            "channel": "group",
        }
    ]


@pytest.mark.asyncio
async def test_automation_service_execute_self_call_invokes_ai_and_sends_result() -> (
    None
):
    ai = SimpleNamespace(
        ask=AsyncMock(return_value="未来指令已执行"),
        memory_storage=SimpleNamespace(),
        runtime_config=SimpleNamespace(),
    )
    sender = SimpleNamespace(
        send_group_message=AsyncMock(),
        send_private_message=AsyncMock(),
    )
    service = _make_service(ai=ai, sender=sender)

    sent_messages: list[str] = []

    async def _send_message(message: str) -> None:
        sent_messages.append(message)

    try:
        result = await service._execute_tool(
            SELF_CALL_TOOL_NAME,
            {"prompt": "请在触发时复盘并提醒我明天重点。"},
            {
                "send_message_callback": _send_message,
                "scheduled_task_id": "task_self_abc",
                "scheduled_task_name": "future-review",
            },
        )
    finally:
        service.shutdown()

    assert result == "已执行向未来自己的指令"
    ai.ask.assert_awaited_once()
    ask_call = ai.ask.await_args
    assert ask_call.args[0] == "请在触发时复盘并提醒我明天重点。"
    assert ask_call.kwargs["scheduler"] is service
    assert ask_call.kwargs["extra_context"]["scheduled_self_call"] is True
    assert ask_call.kwargs["extra_context"]["scheduled_task_id"] == "task_self_abc"
    assert ask_call.kwargs["extra_context"]["scheduled_task_name"] == "future-review"
    assert sent_messages == ["未来指令已执行"]


@pytest.mark.asyncio
async def test_upsert_automation_refreshes_job_args() -> None:
    service = _make_service()

    try:
        created = await service.upsert_automation(
            "task_edit_args",
            {
                "task_name": "edit",
                "tool_name": "get_current_time",
                "tool_args": {"format": "iso"},
                "cron": "0 9 * * *",
                "target_id": 10001,
                "target_type": "group",
            },
        )
        updated = await service.upsert_automation(
            "task_edit_args",
            {
                "task_name": "edit",
                "tool_name": "messages.send_message",
                "tool_args": {"message": "updated"},
                "cron": "0 9 * * *",
                "address": "qq:10002",
            },
        )
        job = service._apscheduler.get_job("task_edit_args")
    finally:
        service.shutdown()

    assert created is True
    assert updated is True
    assert job is not None
    assert list(job.args) == ["task_edit_args"]
    stored = service.list_tasks()["task_edit_args"]
    assert stored["address"] == "qq:10002"
    assert stored["target_type"] == "private"


@pytest.mark.asyncio
async def test_disabled_time_automation_removes_and_restores_job() -> None:
    service = _make_service()
    try:
        await service.upsert_automation(
            "task_toggle",
            {
                "task_name": "toggle",
                "tool_name": "get_current_time",
                "tool_args": {},
                "cron": "0 9 * * *",
                "target_id": 10001,
                "target_type": "group",
                "enabled": False,
            },
        )
        assert service._apscheduler.get_job("task_toggle") is None
        assert service.next_run_iso("task_toggle") is None

        assert await service.set_enabled("task_toggle", True) is True
        assert service._apscheduler.get_job("task_toggle") is not None

        assert await service.set_enabled("task_toggle", False) is True
        assert service._apscheduler.get_job("task_toggle") is None
        assert service.next_run_iso("task_toggle") is None
    finally:
        service.shutdown()


@pytest.mark.asyncio
async def test_invalid_cron_is_rejected_before_storage_or_scheduler_update() -> None:
    service = _make_service()
    try:
        with pytest.raises(AutomationValidationError):
            await service.upsert_automation(
                "task_invalid_cron",
                {
                    "tool_name": "get_current_time",
                    "tool_args": {},
                    "cron": "invalid cron",
                    "target_id": 10001,
                    "target_type": "group",
                },
            )
        assert "task_invalid_cron" not in service.tasks
        assert service._apscheduler.get_job("task_invalid_cron") is None
    finally:
        service.shutdown()


@pytest.mark.asyncio
async def test_invalid_legacy_automation_can_disable_but_not_enable() -> None:
    service = _make_service()
    service.tasks["legacy_invalid"] = {
        "enabled": False,
        "nodes": [
            {
                "id": "start",
                "type": "start",
                "kind": "cron",
                "cron": "invalid cron",
            },
            {"id": "done", "type": "template", "template": "ok"},
        ],
        "edges": [{"from": "start", "to": "done"}],
    }
    try:
        assert await service.set_enabled("legacy_invalid", False) is True
        with pytest.raises(AutomationValidationError):
            await service.set_enabled("legacy_invalid", True)
        assert service.tasks["legacy_invalid"]["enabled"] is False
        assert service._apscheduler.get_job("legacy_invalid") is None
    finally:
        service.shutdown()


@pytest.mark.asyncio
async def test_recovery_skips_disabled_time_jobs() -> None:
    class _LoadedStorage(_DummyStorage):
        def load_tasks(self) -> dict[str, Any]:
            return {
                "enabled": {
                    "enabled": True,
                    "nodes": [
                        {
                            "id": "start",
                            "type": "start",
                            "kind": "cron",
                            "cron": "0 9 * * *",
                        },
                        {"id": "done", "type": "template", "template": "ok"},
                    ],
                    "edges": [{"from": "start", "to": "done"}],
                },
                "disabled": {
                    "enabled": False,
                    "nodes": [
                        {
                            "id": "start",
                            "type": "start",
                            "kind": "cron",
                            "cron": "0 10 * * *",
                        },
                        {"id": "done", "type": "template", "template": "ok"},
                    ],
                    "edges": [{"from": "start", "to": "done"}],
                },
            }

    service = AutomationService(
        SimpleNamespace(
            ask=AsyncMock(),
            memory_storage=SimpleNamespace(),
            runtime_config=SimpleNamespace(),
        ),
        SimpleNamespace(
            send_group_message=AsyncMock(),
            send_private_message=AsyncMock(),
        ),
        SimpleNamespace(
            send_like=AsyncMock(),
            get_image=AsyncMock(return_value=None),
            get_forward_msg=AsyncMock(return_value=[]),
        ),
        SimpleNamespace(),
        storage=cast(Any, _LoadedStorage()),
    )
    try:
        assert service._apscheduler.get_job("enabled") is not None
        assert service._apscheduler.get_job("disabled") is None
    finally:
        service.shutdown()


@pytest.mark.asyncio
async def test_time_fire_routes_wechat_result_by_canonical_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "Undefined.automations.service.collect_context_resources",
        lambda values: {
            key: values[key]
            for key in (
                "send_message_callback",
                "get_recent_messages_callback",
                "get_image_url_callback",
                "get_forward_msg_callback",
                "send_like_callback",
                "sender",
                "history_manager",
                "onebot_client",
            )
            if key in values
        },
    )
    ai = SimpleNamespace(
        ask=AsyncMock(return_value="微信提醒"),
        memory_storage=SimpleNamespace(),
        runtime_config=SimpleNamespace(),
    )
    sender = SimpleNamespace(
        send_group_message=AsyncMock(),
        send_private_message=AsyncMock(),
        send_address_message=AsyncMock(),
    )
    service = _make_service(ai=ai, sender=sender)
    service.tasks["task_wechat"] = {
        "task_id": "task_wechat",
        "tool_name": SELF_CALL_TOOL_NAME,
        "tool_args": {"prompt": "提醒我"},
        "cron": "0 9 * * *",
        "target_id": None,
        "target_type": "private",
        "address": "wechat:12345",
    }

    try:
        await service._on_time_fire("task_wechat")
    finally:
        service.shutdown()

    sender.send_address_message.assert_awaited_once()
    address = sender.send_address_message.await_args.args[0]
    assert address.canonical == "wechat:12345"
    assert sender.send_address_message.await_args.args[1] == "微信提醒"
    sender.send_private_message.assert_not_awaited()


@pytest.mark.parametrize(
    ("suffix", "expected_kind"),
    [(".png", "image"), (".ogg", "record")],
)
@pytest.mark.asyncio
async def test_time_fire_routes_wechat_media_as_address_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    suffix: str,
    expected_kind: str,
) -> None:
    media_path = tmp_path / f"reminder{suffix}"
    await async_io.write_bytes(media_path, b"media")
    monkeypatch.setattr(
        "Undefined.automations.service.collect_context_resources",
        lambda values: {
            key: values[key]
            for key in (
                "send_image_callback",
                "sender",
                "history_manager",
                "onebot_client",
            )
            if key in values
        },
    )

    async def execute_tool(
        _tool_name: str,
        _tool_args: dict[str, Any],
        context: dict[str, Any],
    ) -> str:
        await context["send_image_callback"](
            12345,
            "private",
            str(media_path),
        )
        return "sent"

    ai = SimpleNamespace(
        tool_manager=SimpleNamespace(execute_tool=execute_tool),
        memory_storage=SimpleNamespace(),
        runtime_config=SimpleNamespace(),
    )
    sender = SimpleNamespace(
        send_group_message=AsyncMock(),
        send_private_message=AsyncMock(),
        send_address_message=AsyncMock(),
        send_address_file=AsyncMock(),
    )
    service = _make_service(ai=ai, sender=sender)
    service.tasks["task_wechat_media"] = {
        "task_id": "task_wechat_media",
        "tool_name": "test.media",
        "tool_args": {},
        "cron": "0 9 * * *",
        "target_id": None,
        "target_type": "private",
        "address": "wechat:12345",
    }

    try:
        await service._on_time_fire("task_wechat_media")
    finally:
        service.shutdown()

    sender.send_address_file.assert_awaited_once_with(
        resolve_task_address("wechat:12345", None, "private"),
        str(media_path),
        name=media_path.name,
        kind=expected_kind,
        auto_history=False,
    )
    sender.send_address_message.assert_not_awaited()
