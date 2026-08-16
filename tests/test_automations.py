"""Condition-driven automations: mentions, match, migrate, runner, hooks, API."""

from __future__ import annotations

import json
from copy import deepcopy
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web

import Undefined.handlers as handlers_module
from Undefined.api import RuntimeAPIContext, RuntimeAPIServer
from Undefined.automations.engine import iter_matching_tasks
from Undefined.automations.match import AutomationEvent, match_start_node
from Undefined.automations.mentions import consume_mentions
from Undefined.automations.migrate import migrate_legacy_task
from Undefined.automations.runner import WorkflowError, WorkflowRunner
from Undefined.automations.short import build_short_automation
from Undefined.automations.storage import AutomationStorage
from Undefined.automations.validate import (
    AutomationValidationError,
    validate_automation,
)
from Undefined.handlers import MessageHandler
from Undefined.handlers.poke import PokeMixin
from Undefined.automations.service import AutomationService


def test_preview_text_truncates() -> None:
    from Undefined.automations.logutil import preview_text

    assert preview_text("短") == "短"
    assert preview_text("a" * 90).startswith("a" * 80)
    assert "len=90" in preview_text("a" * 90)
    assert preview_text("a\nb") == "a\\nb"


def test_consume_mentions_strips_only_written_tokens() -> None:
    result = consume_mentions("[@1(甲)] [@2] 热点", ["1"])
    assert result.matched is True
    assert result.stripped == "[@2] 热点"
    assert result.mentions == ("1",)
    assert result.mentions_all == ("1", "2")


def test_consume_mentions_keeps_unlisted_and_strips_trailing_space() -> None:
    result = consume_mentions("[@10001] 你好", ["10001"])
    assert result.matched is True
    assert result.stripped == "你好"


def test_consume_mentions_without_space_only_removes_token() -> None:
    result = consume_mentions("[@10001]你好", ["10001"])
    assert result.stripped == "你好"


def test_consume_mentions_no_clauses_passthrough() -> None:
    text = "[@1] 全文原样"
    result = consume_mentions(text, [])
    assert result.matched is True
    assert result.stripped == text
    assert result.mentions == ()


def test_consume_mentions_star_consumes_one() -> None:
    result = consume_mentions("[@1] [@2] rest", ["*"])
    assert result.matched is True
    assert result.mentions == ("1",)
    assert result.stripped == "[@2] rest"


def test_consume_mentions_multiple_clauses() -> None:
    result = consume_mentions("[@1] [@2] [@3] x", ["1", "2", "*"])
    assert result.matched is True
    assert result.mentions == ("1", "2", "3")
    assert result.stripped == "x"


def test_nickname_token_matches_qq() -> None:
    result = consume_mentions("[@123(昵称)] hello", ["123"])
    assert result.matched is True
    assert result.stripped == "hello"


def test_match_start_channels_and_scope() -> None:
    start = {
        "id": "start",
        "type": "start",
        "kind": "message",
        "channels": ["group"],
        "group_ids": [100],
        "user_ids": [200],
        "text": "热点",
    }
    group_ok = AutomationEvent(
        kind="message",
        channel="group",
        text="热点",
        sender_id=200,
        group_id=100,
    )
    assert match_start_node(start, group_ok) is not None
    assert (
        match_start_node(
            start,
            AutomationEvent(
                kind="message", channel="private", text="热点", user_id=200
            ),
        )
        is None
    )
    assert (
        match_start_node(
            start,
            AutomationEvent(kind="message", channel="wechat", text="热点", user_id=200),
        )
        is None
    )
    assert (
        match_start_node(
            start,
            AutomationEvent(
                kind="message",
                channel="group",
                text="热点",
                sender_id=200,
                group_id=999,
            ),
        )
        is None
    )


def test_pass_text_original_vs_stripped() -> None:
    start = {
        "kind": "message",
        "channels": ["group"],
        "mentions": ["1"],
        "text": "热点",
        "pass_text": "original",
    }
    event = AutomationEvent(
        kind="message",
        channel="group",
        text="[@1] 热点",
        group_id=1,
    )
    original = match_start_node(start, event)
    assert original is not None
    assert original.pass_text == "[@1] 热点"
    start["pass_text"] = "stripped"
    stripped = match_start_node(start, event)
    assert stripped is not None
    assert stripped.pass_text == "热点"


def test_migrate_legacy_cron_self_instruction() -> None:
    migrated = migrate_legacy_task(
        {
            "task_id": "old",
            "cron": "0 9 * * *",
            "tool_name": "scheduler.call_self",
            "tool_args": {"prompt": "早安"},
            "self_instruction": "早安",
        }
    )
    assert migrated["nodes"][0]["kind"] == "cron"
    assert migrated["nodes"][1]["type"] == "llm.main"
    assert migrated["edges"] == [{"from": "start", "to": "main"}]
    assert migrated["cron"] == "0 9 * * *"
    assert migrated["tool_name"] == "scheduler.call_self"
    assert migrated["self_instruction"] == "早安"
    assert migrated["compat_continue_on_tool_error"] is True
    assert migrated["auto_send_final"] is False


def test_migrate_legacy_single_tool_keeps_single_mode_fields() -> None:
    migrated = migrate_legacy_task(
        {
            "task_id": "t1",
            "cron": "*/5 * * * *",
            "tool_name": "get_current_time",
            "tool_args": {"format": "iso"},
            "target_id": 1,
            "target_type": "group",
        }
    )
    assert migrated["tool_name"] == "get_current_time"
    assert migrated["tool_args"] == {"format": "iso"}
    assert "tools" not in migrated or not migrated["tools"]
    assert migrated["cron"] == "*/5 * * * *"


def test_migrate_legacy_parallel_tools() -> None:
    migrated = migrate_legacy_task(
        {
            "cron": "0 8 * * *",
            "tools": [
                {"tool_name": "a", "tool_args": {}},
                {"tool_name": "b", "tool_args": {"x": 1}},
            ],
            "execution_mode": "parallel",
        }
    )
    assert migrated["execution_mode"] == "parallel"
    assert len(migrated["tools"]) == 2
    assert {edge["from"] for edge in migrated["edges"]} == {"start"}
    assert [node["id"] for node in migrated["nodes"] if node["id"] != "start"] == [
        "tool_0",
        "tool_1",
    ]


def test_short_command_create_graph() -> None:
    task = build_short_automation(
        {
            "kind": "message",
            "channels": ["group", "private"],
            "mentions": ["10001", "*"],
            "text": "热点",
            "pass_text": "stripped",
            "prompt": "{{trigger.text}}",
        }
    )
    start = task["nodes"][0]
    assert start["channels"] == ["group", "private"]
    assert start["mentions"] == ["10001", "*"]
    assert task["nodes"][1]["type"] == "llm.main"


def test_validate_rejects_outer_cycle() -> None:
    task = {
        "nodes": [
            {"id": "start", "type": "start", "kind": "cron", "cron": "0 9 * * *"},
            {"id": "a", "type": "template", "template": "a"},
            {"id": "b", "type": "template", "template": "b"},
        ],
        "edges": [
            {"from": "start", "to": "a"},
            {"from": "a", "to": "b"},
            {"from": "b", "to": "a"},
        ],
    }
    with pytest.raises(AutomationValidationError, match="cycle"):
        validate_automation(task)


def test_validate_rejects_loop_cross_edge() -> None:
    task = {
        "nodes": [
            {"id": "start", "type": "start", "kind": "cron", "cron": "0 9 * * *"},
            {"id": "loop", "type": "loop.times", "count": 2, "body": ["body"]},
            {"id": "body", "type": "template", "template": "{{index}}"},
            {"id": "after", "type": "template", "template": "x"},
        ],
        "edges": [
            {"from": "start", "to": "loop"},
            {"from": "body", "to": "after"},
        ],
    }
    with pytest.raises(AutomationValidationError, match="loop body"):
        validate_automation(task)


def _runner(
    *,
    execute_tool: Any = None,
    submit_llm: Any = None,
    send_message: Any = None,
) -> WorkflowRunner:
    async def _send(text: str) -> None:
        if send_message is not None:
            await send_message(text)

    return WorkflowRunner(
        execute_tool=execute_tool or AsyncMock(return_value=""),
        ask_main=AsyncMock(return_value=""),
        submit_llm=submit_llm or AsyncMock(return_value={"choices": []}),
        send_message=_send if send_message is None else send_message,
        get_openai_tools=lambda: [],
        agent_config=SimpleNamespace(max_tokens=16),
        tool_context={},
    )


@pytest.mark.asyncio
async def test_runner_branch_if_else() -> None:
    sent: list[str] = []

    async def send_message(text: str) -> None:
        sent.append(text)

    runner = _runner(send_message=send_message)
    task = {
        "auto_send_final": False,
        "nodes": [
            {"id": "start", "type": "start", "kind": "message", "channels": ["group"]},
            {
                "id": "iff",
                "type": "branch.if",
                "input": "{{trigger.text_original}}",
                "cases": [{"id": "hit", "text": "yes"}],
            },
            {"id": "yes", "type": "template", "template": "HIT", "emit": True},
            {"id": "no", "type": "template", "template": "ELSE", "emit": True},
        ],
        "edges": [
            {"from": "start", "to": "iff"},
            {"from": "iff", "to": "yes", "case": "hit"},
            {"from": "iff", "to": "no", "case": "else"},
        ],
    }
    event = AutomationEvent(kind="message", channel="group", text="yes please")
    await runner.run(
        task,
        event=event,
        pass_text=event.text,
        consume_mentions=(),
        consume_stripped=event.text,
        mentions_all=(),
    )
    assert sent == ["HIT"]
    sent.clear()
    event2 = AutomationEvent(kind="message", channel="group", text="other")
    await runner.run(
        task,
        event=event2,
        pass_text=event2.text,
        consume_mentions=(),
        consume_stripped=event2.text,
        mentions_all=(),
    )
    assert sent == ["ELSE"]


@pytest.mark.asyncio
async def test_runner_branch_llm_uses_option_tool() -> None:
    sent: list[str] = []

    async def send_message(text: str) -> None:
        sent.append(text)

    async def submit_llm(**kwargs: Any) -> dict[str, Any]:
        tools = kwargs.get("tools") or []
        assert tools
        assert kwargs.get("tool_choice") == "required"
        name = str(tools[0]["function"]["name"])
        return {
            "choices": [
                {
                    "message": {
                        "content": "",
                        "tool_calls": [{"function": {"name": name, "arguments": "{}"}}],
                    }
                }
            ]
        }

    runner = _runner(submit_llm=submit_llm, send_message=send_message)
    task = {
        "auto_send_final": False,
        "nodes": [
            {"id": "start", "type": "start", "kind": "message", "channels": ["group"]},
            {
                "id": "br",
                "type": "branch.llm",
                "input": "{{trigger.text}}",
                "options": [
                    {"id": "search", "description": "搜"},
                    {"id": "chat", "description": "聊"},
                ],
            },
            {"id": "search", "type": "template", "template": "SEARCH", "emit": True},
            {"id": "chat", "type": "template", "template": "CHAT", "emit": True},
        ],
        "edges": [
            {"from": "start", "to": "br"},
            {"from": "br", "to": "search", "case": "search"},
            {"from": "br", "to": "chat", "case": "chat"},
        ],
    }
    event = AutomationEvent(kind="message", channel="group", text="hi")
    await runner.run(
        task,
        event=event,
        pass_text="hi",
        consume_mentions=(),
        consume_stripped="hi",
        mentions_all=(),
    )
    assert sent == ["SEARCH"]


@pytest.mark.asyncio
async def test_loop_each_hard_cap_25() -> None:
    seen: list[int] = []

    async def execute_tool(
        name: str, args: dict[str, Any], context: dict[str, Any]
    ) -> str:
        _ = name, context
        seen.append(int(args["index"]))
        return str(args["index"])

    runner = _runner(execute_tool=execute_tool, send_message=AsyncMock())
    items = json.dumps(list(range(40)))
    task = {
        "auto_send_final": False,
        "nodes": [
            {"id": "start", "type": "start", "kind": "cron", "cron": "0 9 * * *"},
            {"id": "loop", "type": "loop.each", "source": items, "body": ["body"]},
            {
                "id": "body",
                "type": "tool",
                "tool_name": "echo",
                "args": {"index": "{{index}}"},
            },
        ],
        "edges": [{"from": "start", "to": "loop"}],
    }
    validate_automation(task)
    event = AutomationEvent(kind="time", channel="group")
    await runner.run(
        task,
        event=event,
        pass_text="",
        consume_mentions=(),
        consume_stripped="",
        mentions_all=(),
    )
    assert seen == list(range(25))


@pytest.mark.asyncio
async def test_runner_failure_raises() -> None:
    async def execute_tool(
        name: str, args: dict[str, Any], context: dict[str, Any]
    ) -> str:
        _ = name, args, context
        raise RuntimeError("boom")

    runner = _runner(execute_tool=execute_tool, send_message=AsyncMock())
    task = {
        "auto_send_final": False,
        "nodes": [
            {"id": "start", "type": "start", "kind": "cron", "cron": "* * * * *"},
            {"id": "tool_0", "type": "tool", "tool_name": "x", "args": {}},
        ],
        "edges": [{"from": "start", "to": "tool_0"}],
    }
    with pytest.raises(WorkflowError, match="boom"):
        await runner.run(
            task,
            event=AutomationEvent(kind="time", channel="group"),
            pass_text="",
            consume_mentions=(),
            consume_stripped="",
            mentions_all=(),
        )


@pytest.mark.asyncio
async def test_legacy_tool_error_continues_serial_chain() -> None:
    called: list[str] = []

    async def execute_tool(
        name: str, args: dict[str, Any], context: dict[str, Any]
    ) -> str:
        _ = args, context
        called.append(name)
        if name == "first":
            raise RuntimeError("boom")
        return "ok"

    runner = _runner(execute_tool=execute_tool, send_message=AsyncMock())
    task = migrate_legacy_task(
        {
            "cron": "0 9 * * *",
            "tools": [
                {"tool_name": "first", "tool_args": {}},
                {"tool_name": "second", "tool_args": {}},
            ],
            "execution_mode": "serial",
        }
    )
    await runner.run(
        task,
        event=AutomationEvent(kind="time", channel="group"),
        pass_text="",
        consume_mentions=(),
        consume_stripped="",
        mentions_all=(),
    )
    assert called == ["first", "second"]


def test_serialize_migrated_task_keeps_crontab_mode() -> None:
    from Undefined.api.routes.schedules import serialize_schedule_task

    ctx = RuntimeAPIContext(
        config_getter=lambda: SimpleNamespace(),
        onebot=SimpleNamespace(),
        ai=SimpleNamespace(),
        command_dispatcher=SimpleNamespace(),
        queue_manager=SimpleNamespace(),
        history_manager=SimpleNamespace(),
        scheduler=SimpleNamespace(next_run_iso=lambda _id: None),
    )
    migrated = migrate_legacy_task(
        {
            "task_id": "daily",
            "task_name": "daily",
            "tool_name": "get_current_time",
            "tool_args": {},
            "cron": "0 9 * * *",
            "target_id": 10001,
            "target_type": "group",
        }
    )
    item = serialize_schedule_task(ctx, "daily", migrated)
    assert item["mode"] == "single"
    assert item["cron"] == "0 9 * * *"
    assert item["tool_name"] == "get_current_time"


@pytest.mark.asyncio
async def test_remove_event_automation_without_job() -> None:
    class _DummyStorage:
        def load_tasks(self) -> dict[str, Any]:
            return {}

        async def save_all(self, _tasks: dict[str, Any]) -> None:
            return None

    service = AutomationService(
        SimpleNamespace(
            memory_storage=SimpleNamespace(),
            runtime_config=SimpleNamespace(),
        ),
        SimpleNamespace(),
        SimpleNamespace(),
        SimpleNamespace(),
        storage=cast(Any, _DummyStorage()),
    )
    try:
        service.tasks["evt"] = {
            "task_id": "evt",
            "nodes": [
                {
                    "id": "start",
                    "type": "start",
                    "kind": "message",
                    "channels": ["group"],
                }
            ],
            "edges": [],
        }
        assert await service.remove_task("evt") is True
        assert "evt" not in service.tasks
        assert await service.remove_task("missing") is False
    finally:
        service.shutdown()


def test_storage_migrates_legacy_json(tmp_path: Any) -> None:
    legacy = tmp_path / "scheduled_tasks.json"
    auto_path = tmp_path / "automations.json"
    legacy.write_text(
        json.dumps(
            {
                "task_old": {
                    "task_id": "task_old",
                    "tool_name": "get_current_time",
                    "tool_args": {},
                    "cron": "0 8 * * *",
                    "target_type": "group",
                    "target_id": 1,
                }
            }
        ),
        encoding="utf-8",
    )
    storage = AutomationStorage(path=auto_path, legacy_path=legacy)
    tasks = storage.load_tasks()
    assert "task_old" in tasks
    assert tasks["task_old"]["nodes"][0]["kind"] == "cron"
    assert tasks["task_old"]["tool_name"] == "get_current_time"
    assert tasks["task_old"]["cron"] == "0 8 * * *"
    leftover = json.loads(legacy.read_text(encoding="utf-8"))
    assert leftover["task_old"]["cron"] == "0 8 * * *"
    assert "nodes" not in leftover["task_old"]
    assert auto_path.exists()
    saved = json.loads(auto_path.read_text(encoding="utf-8"))
    assert saved["task_old"]["nodes"][0]["kind"] == "cron"


@pytest.mark.asyncio
async def test_storage_save_does_not_write_legacy(tmp_path: Any) -> None:
    auto_path = tmp_path / "automations.json"
    legacy = tmp_path / "scheduled_tasks.json"
    original = {"keep_old": {"cron": "0 1 * * *", "tool_name": "get_current_time"}}
    legacy.write_text(json.dumps(original), encoding="utf-8")
    storage = AutomationStorage(path=auto_path, legacy_path=legacy)
    payload = migrate_legacy_task(
        {
            "task_id": "keep",
            "tool_name": "get_current_time",
            "tool_args": {},
            "cron": "0 9 * * *",
        }
    )
    await storage.save_all({"keep": payload})
    assert auto_path.exists()
    leftover = json.loads(legacy.read_text(encoding="utf-8"))
    assert leftover == original


def test_storage_prefers_automations_over_legacy(tmp_path: Any) -> None:
    auto_path = tmp_path / "automations.json"
    legacy = tmp_path / "scheduled_tasks.json"
    auto_path.write_text(
        json.dumps(
            {
                "newer": {
                    "task_id": "newer",
                    "cron": "0 1 * * *",
                    "tool_name": "messages.send_message",
                    "tool_args": {"message": "n"},
                    "nodes": [
                        {
                            "id": "start",
                            "type": "start",
                            "kind": "cron",
                            "cron": "0 1 * * *",
                        }
                    ],
                    "edges": [],
                }
            }
        ),
        encoding="utf-8",
    )
    legacy.write_text(
        json.dumps(
            {
                "older": {
                    "task_id": "older",
                    "cron": "0 2 * * *",
                    "tool_name": "get_current_time",
                    "tool_args": {},
                }
            }
        ),
        encoding="utf-8",
    )
    storage = AutomationStorage(path=auto_path, legacy_path=legacy)
    tasks = storage.load_tasks()
    assert "newer" in tasks
    assert "older" not in tasks


def test_storage_existing_empty_automations_skips_legacy(tmp_path: Any) -> None:
    auto_path = tmp_path / "automations.json"
    legacy = tmp_path / "scheduled_tasks.json"
    auto_path.write_text("{}", encoding="utf-8")
    legacy.write_text(
        json.dumps(
            {
                "older": {
                    "task_id": "older",
                    "cron": "0 2 * * *",
                    "tool_name": "get_current_time",
                    "tool_args": {},
                }
            }
        ),
        encoding="utf-8",
    )
    storage = AutomationStorage(path=auto_path, legacy_path=legacy)
    assert storage.load_tasks() == {}


def test_iter_matching_respects_enabled() -> None:
    tasks = {
        "a": {
            "enabled": False,
            "nodes": [
                {
                    "id": "start",
                    "type": "start",
                    "kind": "message",
                    "channels": ["group"],
                    "text": "hi",
                }
            ],
            "edges": [],
        }
    }
    matched = iter_matching_tasks(
        tasks,
        AutomationEvent(kind="message", channel="group", text="hi", group_id=1),
    )
    assert matched == []


def _group_handler() -> Any:
    handler: Any = MessageHandler.__new__(MessageHandler)
    handler.config = SimpleNamespace(
        bot_qq=10000,
        is_group_allowed=lambda _gid: True,
        access_control_enabled=lambda: False,
        should_process_group_message=lambda is_at_bot=False: True,
        process_every_message=True,
        keyword_reply_enabled=False,
        repeat_enabled=False,
    )
    handler.onebot = SimpleNamespace(
        get_group_info=AsyncMock(return_value={"group_name": "测试群"}),
        get_msg=AsyncMock(),
        get_forward_msg=AsyncMock(),
    )
    handler.history_manager = SimpleNamespace(add_group_message=AsyncMock())
    handler.ai_coordinator = SimpleNamespace(
        _is_at_bot=MagicMock(return_value=False),
        handle_auto_reply=AsyncMock(),
        scheduler=SimpleNamespace(handle_event=AsyncMock(return_value=True)),
    )
    handler.command_dispatcher = SimpleNamespace(
        parse_command=MagicMock(return_value=None),
        dispatch=AsyncMock(),
    )
    handler.pipeline_registry = SimpleNamespace(run=AsyncMock(return_value=[]))
    handler._pipelines_initialized = True
    handler._schedule_profile_display_name_refresh = MagicMock()
    handler._schedule_meme_ingest = MagicMock()
    handler._schedule_forward_meme_scan = MagicMock()
    handler._background_tasks = set()
    handler._bot_nickname_cache = SimpleNamespace(
        get_nicknames=AsyncMock(return_value=[])
    )
    handler._collect_message_attachments = AsyncMock(return_value=[])
    handler.sender = SimpleNamespace()
    handler._extract_bilibili_ids = AsyncMock(return_value=[])
    handler._extract_douyin_ids = AsyncMock(return_value=[])
    handler._extract_arxiv_ids = AsyncMock(return_value=[])
    handler._extract_github_repo_ids = AsyncMock(return_value=[])
    handler._handle_bilibili_extract = AsyncMock()
    handler._handle_douyin_extract = AsyncMock()
    handler._handle_arxiv_extract = AsyncMock()
    handler._handle_github_extract = AsyncMock()
    return handler


@pytest.mark.asyncio
async def test_group_entry_intercepts_ai(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        handlers_module,
        "parse_message_content_for_history",
        AsyncMock(return_value="[@10000] 热点"),
    )
    handler = _group_handler()
    event = {
        "post_type": "message",
        "message_type": "group",
        "group_id": 30001,
        "user_id": 20001,
        "message_id": 1,
        "sender": {
            "user_id": 20001,
            "card": "用户",
            "nickname": "用户",
            "role": "member",
            "title": "",
        },
        "message": [{"type": "text", "data": {"text": "热点"}}],
    }
    await handler.handle_message(event)
    handler.ai_coordinator.scheduler.handle_event.assert_awaited()
    handler.ai_coordinator.handle_auto_reply.assert_not_awaited()


@pytest.mark.asyncio
async def test_private_entry_intercepts_ai(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        handlers_module,
        "parse_message_content_for_history",
        AsyncMock(return_value="hello"),
    )
    handler: Any = MessageHandler.__new__(MessageHandler)
    handler.config = SimpleNamespace(
        bot_qq=10000,
        is_private_allowed=lambda _uid: True,
        access_control_enabled=lambda: False,
        should_process_private_message=lambda: True,
        model_pool_enabled=False,
    )
    handler.onebot = SimpleNamespace(
        get_stranger_info=AsyncMock(return_value={"nickname": "测"}),
        get_msg=AsyncMock(),
        get_forward_msg=AsyncMock(),
    )
    handler.history_manager = SimpleNamespace(add_private_message=AsyncMock())
    handler.ai_coordinator = SimpleNamespace(
        handle_private_reply=AsyncMock(),
        model_pool=SimpleNamespace(
            handle_private_message=AsyncMock(return_value=False)
        ),
        scheduler=SimpleNamespace(handle_event=AsyncMock(return_value=True)),
    )
    handler.command_dispatcher = SimpleNamespace(
        parse_command=MagicMock(return_value=None),
        dispatch_private=AsyncMock(),
    )
    handler.pipeline_registry = SimpleNamespace(run=AsyncMock(return_value=[]))
    handler._pipelines_initialized = True
    handler._schedule_profile_display_name_refresh = MagicMock()
    handler._schedule_meme_ingest = MagicMock()
    handler._background_tasks = set()
    handler._collect_message_attachments = AsyncMock(return_value=[])
    handler._schedule_forward_meme_scan = MagicMock()
    handler.sender = SimpleNamespace()
    handler._extract_bilibili_ids = AsyncMock(return_value=[])
    handler._extract_douyin_ids = AsyncMock(return_value=[])
    handler._extract_arxiv_ids = AsyncMock(return_value=[])
    handler._extract_github_repo_ids = AsyncMock(return_value=[])
    handler._handle_bilibili_extract = AsyncMock()
    handler._handle_douyin_extract = AsyncMock()
    handler._handle_arxiv_extract = AsyncMock()
    handler._handle_github_extract = AsyncMock()
    await handler.handle_message(
        {
            "post_type": "message",
            "message_type": "private",
            "user_id": 20001,
            "message_id": 1,
            "message": [{"type": "text", "data": {"text": "hello"}}],
            "sender": {"user_id": 20001, "nickname": "测"},
        }
    )
    handler.ai_coordinator.scheduler.handle_event.assert_awaited()
    handler.ai_coordinator.handle_private_reply.assert_not_awaited()


@pytest.mark.asyncio
async def test_wechat_entry_intercepts_ai() -> None:
    handler: Any = MessageHandler.__new__(MessageHandler)
    handler.config = SimpleNamespace(
        is_private_allowed=lambda _uid: True,
        should_process_private_message=lambda: True,
        model_pool_enabled=False,
    )
    handler.sender = SimpleNamespace()
    handler.history_manager = SimpleNamespace(
        find_private_message_by_id=AsyncMock(return_value=None),
        find_private_bot_messages_for_reference=AsyncMock(return_value=[]),
        add_private_message=AsyncMock(),
    )
    handler.ai_coordinator = SimpleNamespace(
        handle_private_reply=AsyncMock(),
        scheduler=SimpleNamespace(handle_event=AsyncMock(return_value=True)),
    )
    handler.command_dispatcher = SimpleNamespace(
        parse_command=MagicMock(return_value=None)
    )
    handler._run_pipelines = AsyncMock()
    handler._schedule_meme_ingest = MagicMock()
    await handler.handle_weixin_private_message(
        qq_id=1,
        text="hi",
        message_content=[{"type": "text", "data": {"text": "hi"}}],
        attachments=[],
        sender_name="wx",
        message_id="m1",
        account_alias="primary",
    )
    handler.ai_coordinator.scheduler.handle_event.assert_awaited()
    call = handler.ai_coordinator.scheduler.handle_event.await_args
    assert call.args[0].channel == "wechat"
    handler.ai_coordinator.handle_private_reply.assert_not_awaited()


@pytest.mark.asyncio
async def test_poke_entry_intercepts_ai() -> None:
    handler: Any = MessageHandler.__new__(MessageHandler)
    handler.config = SimpleNamespace(
        bot_qq=10000,
        should_process_poke_message=lambda: True,
        is_private_allowed=lambda _uid: True,
        is_group_allowed=lambda _gid: True,
        access_control_enabled=lambda: False,
    )
    handler.history_manager = SimpleNamespace(
        add_private_message=AsyncMock(),
        add_group_message=AsyncMock(),
    )
    handler.ai_coordinator = SimpleNamespace(
        handle_private_reply=AsyncMock(),
        handle_auto_reply=AsyncMock(),
        scheduler=SimpleNamespace(handle_event=AsyncMock(return_value=True)),
    )
    handler.ai = SimpleNamespace(_cognitive_service=None)
    handler.onebot = SimpleNamespace(
        get_stranger_info=AsyncMock(return_value={"nickname": "测"}),
        get_group_member_info=AsyncMock(return_value={}),
        get_group_info=AsyncMock(return_value={}),
    )
    handler._background_tasks = set()
    await PokeMixin._handle_poke_notice(
        handler,
        {
            "target_id": 10000,
            "group_id": 0,
            "user_id": 20001,
            "sender": {"user_id": 20001},
        },
    )
    handler.ai_coordinator.scheduler.handle_event.assert_awaited()
    handler.ai_coordinator.handle_private_reply.assert_not_called()


def _api_context(scheduler: Any) -> RuntimeAPIContext:
    return RuntimeAPIContext(
        config_getter=lambda: SimpleNamespace(
            bot_qq=10000,
            api=SimpleNamespace(
                enabled=True,
                host="127.0.0.1",
                port=8788,
                auth_key="changeme",
                openapi_enabled=True,
            ),
        ),
        onebot=SimpleNamespace(connection_status=lambda: {}),
        ai=SimpleNamespace(memory_storage=None),
        command_dispatcher=SimpleNamespace(),
        queue_manager=SimpleNamespace(snapshot=lambda: {}),
        history_manager=SimpleNamespace(),
        scheduler=scheduler,
    )


class _JsonRequest(SimpleNamespace):
    async def json(self) -> dict[str, Any]:
        return dict(getattr(self, "_json", {}))


class _FakeAutoScheduler:
    def __init__(self) -> None:
        self.tasks: dict[str, dict[str, Any]] = {}
        self.scheduler = SimpleNamespace(running=True, get_job=lambda _id: None)

    def list_tasks(self) -> dict[str, dict[str, Any]]:
        return self.tasks

    async def upsert_automation(self, task_id: str, task: dict[str, Any]) -> bool:
        payload = deepcopy(task)
        payload["task_id"] = task_id
        self.tasks[task_id] = payload
        return True

    async def remove_task(self, task_id: str) -> bool:
        self.tasks.pop(task_id, None)
        return True

    async def set_enabled(self, task_id: str, enabled: bool) -> bool:
        if task_id not in self.tasks:
            return False
        self.tasks[task_id]["enabled"] = enabled
        return True


@pytest.mark.asyncio
async def test_automations_catalog_and_short_create() -> None:
    scheduler = _FakeAutoScheduler()
    server = RuntimeAPIServer(_api_context(scheduler), host="127.0.0.1", port=8788)
    catalog = await server._automations_catalog_handler(
        cast(web.Request, SimpleNamespace())
    )
    catalog_body = json.loads(catalog.text or "{}")
    assert "presets" in catalog_body
    assert catalog_body["loop_max_iterations"] == 25

    request = _JsonRequest(
        _json={
            "task_id": "hotspot",
            "kind": "message",
            "channels": ["group"],
            "mentions": ["10000"],
            "text": "热点",
            "prompt": "{{trigger.text_stripped}}",
        }
    )
    created = await server._automations_create_handler(cast(web.Request, request))
    assert created.status == 201
    body = json.loads(created.text or "{}")
    assert body["task"]["nodes"][0]["mentions"] == ["10000"]
    assert "hotspot" in scheduler.tasks
