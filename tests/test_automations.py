"""Condition-driven automations: mentions, match, migrate, runner, hooks, API."""

from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web

import Undefined.handlers as handlers_module
from Undefined.api import RuntimeAPIContext, RuntimeAPIServer
from Undefined.attachments.models import RegisteredMessageAttachments
from Undefined.automations.engine import iter_matching_tasks
from Undefined.automations.match import AutomationEvent, match_start_node
from Undefined.automations.mentions import consume_mentions
from Undefined.automations.migrate import migrate_legacy_task
from Undefined.automations.runner import (
    WorkflowError,
    WorkflowRunner,
    filter_openai_tools,
)
from Undefined.automations.short import build_short_automation
from Undefined.automations.storage import AutomationStorage
from Undefined.automations.validate import (
    AutomationValidationError,
    collect_automation_issues,
    validate_automation,
)
from Undefined.handlers import MessageHandler
from Undefined.handlers.poke import PokeMixin
from Undefined.automations.service import AutomationService
from Undefined.services.queue_manager import (
    QUEUE_LANE_GROUP_NORMAL,
    QUEUE_LANE_PRIVATE,
)
from Undefined.utils.message_reply import ReplyContext


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
    ask_main: Any = None,
    tool_context: dict[str, Any] | None = None,
) -> WorkflowRunner:
    async def _send(text: str) -> None:
        if send_message is not None:
            await send_message(text)

    return WorkflowRunner(
        execute_tool=execute_tool or AsyncMock(return_value=""),
        ask_main=ask_main or AsyncMock(return_value=""),
        submit_llm=submit_llm or AsyncMock(return_value={"choices": []}),
        send_message=_send if send_message is None else send_message,
        get_openai_tools=lambda: [],
        agent_config=SimpleNamespace(max_tokens=16),
        tool_context=tool_context if tool_context is not None else {},
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
async def test_runner_exposes_message_resources_as_trigger_variables() -> None:
    captured_args: list[dict[str, Any]] = []

    async def execute_tool(
        _name: str,
        args: dict[str, Any],
        _context: dict[str, Any],
    ) -> str:
        captured_args.append(args)
        return "ok"

    runner = _runner(execute_tool=execute_tool, send_message=AsyncMock())
    task = {
        "auto_send_final": False,
        "nodes": [
            {"id": "start", "type": "start", "kind": "message", "channels": ["group"]},
            {
                "id": "capture",
                "type": "tool",
                "tool_name": "capture",
                "args": {
                    "message_id": "{{trigger.message_id}}",
                    "message_ids": "{{trigger.message_ids}}",
                    "attachments": "{{trigger.attachments}}",
                    "message_content": "{{trigger.message_content}}",
                    "reply": "{{trigger.reply_context.message}}",
                    "queue_lane": "{{trigger.queue_lane}}",
                    "batch_scope": "{{trigger.batch_scope}}",
                    "batched_count": "{{trigger.batched_count}}",
                    "is_batched": "{{trigger.current_input_is_batched}}",
                },
            },
        ],
        "edges": [{"from": "start", "to": "capture"}],
    }
    await runner.run(
        task,
        event=AutomationEvent(kind="message", channel="group", text="hi"),
        pass_text="hi",
        consume_mentions=(),
        consume_stripped="hi",
        mentions_all=(),
        trigger_resources={
            "message_id": "m1",
            "message_ids": ["m1"],
            "attachments": [{"uid": "pic_1"}],
            "message_content": [{"type": "text"}],
            "reply_context": {"message": "quoted"},
            "queue_lane": "group_mention",
            "batch_scope": "group:1",
            "batched_count": 1,
            "current_input_is_batched": False,
        },
    )
    assert captured_args == [
        {
            "message_id": "m1",
            "message_ids": "['m1']",
            "attachments": "[{'uid': 'pic_1'}]",
            "message_content": "[{'type': 'text'}]",
            "reply": "quoted",
            "queue_lane": "group_mention",
            "batch_scope": "group:1",
            "batched_count": "1",
            "is_batched": "False",
        }
    ]


@pytest.mark.asyncio
async def test_runner_time_trigger_message_resources_use_empty_defaults() -> None:
    sent: list[str] = []
    runner = _runner(send_message=AsyncMock(side_effect=sent.append))
    task = {
        "auto_send_final": False,
        "nodes": [
            {"id": "start", "type": "start", "kind": "cron", "cron": "0 9 * * *"},
            {
                "id": "done",
                "type": "template",
                "template": "{{trigger.message_id}}|{{trigger.message_ids}}|{{trigger.batched_count}}|{{trigger.current_input_is_batched}}",
                "emit": True,
            },
        ],
        "edges": [{"from": "start", "to": "done"}],
    }
    await runner.run(
        task,
        event=AutomationEvent(kind="time", channel="group"),
        pass_text="",
        consume_mentions=(),
        consume_stripped="",
        mentions_all=(),
    )
    assert sent == ["|[]|0|False"]


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


def test_filter_openai_tools_matches_short_and_dotted_names() -> None:
    tools = [
        {
            "type": "function",
            "function": {"name": "messages.send_message", "description": "send"},
        },
        {
            "type": "function",
            "function": {"name": "cognitive.get_profile", "description": "profile"},
        },
    ]
    selected = filter_openai_tools(
        tools, tools=["messages.send_message"], toolsets=None, agents=None
    )
    assert [item["function"]["name"] for item in selected] == ["messages.send_message"]
    selected_short = filter_openai_tools(
        tools, tools=["send_message"], toolsets=None, agents=None
    )
    assert [item["function"]["name"] for item in selected_short] == [
        "messages.send_message"
    ]


@pytest.mark.asyncio
async def test_runner_independent_downstream_does_not_wait_for_sibling() -> None:
    order: list[str] = []
    after_done = asyncio.Event()

    async def execute_tool(
        name: str, args: dict[str, Any], context: dict[str, Any]
    ) -> str:
        _ = args, context
        order.append(f"start:{name}")
        if name == "slow":
            await after_done.wait()
        elif name == "after":
            after_done.set()
        order.append(f"end:{name}")
        return name

    runner = _runner(execute_tool=execute_tool, send_message=AsyncMock())
    runner.workflow_timeout_seconds = 2
    runner.node_timeout_seconds = 2
    task = {
        "auto_send_final": False,
        "nodes": [
            {"id": "start", "type": "start", "kind": "message", "channels": ["group"]},
            {"id": "slow", "type": "tool", "tool_name": "slow", "args": {}},
            {"id": "fast", "type": "tool", "tool_name": "fast", "args": {}},
            {"id": "after", "type": "tool", "tool_name": "after", "args": {}},
        ],
        "edges": [
            {"from": "start", "to": "slow"},
            {"from": "start", "to": "fast"},
            {"from": "fast", "to": "after"},
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
    assert order.index("end:after") < order.index("end:slow")
    assert order.index("start:slow") < order.index("start:after")


@pytest.mark.asyncio
async def test_runner_join_waits_for_all_upstreams() -> None:
    order: list[str] = []

    async def execute_tool(
        name: str, args: dict[str, Any], context: dict[str, Any]
    ) -> str:
        _ = args, context
        order.append(f"start:{name}")
        if name == "a":
            await asyncio.sleep(0.05)
        elif name == "b":
            await asyncio.sleep(0.01)
        order.append(f"end:{name}")
        return name

    runner = _runner(execute_tool=execute_tool, send_message=AsyncMock())
    task = {
        "auto_send_final": False,
        "nodes": [
            {"id": "start", "type": "start", "kind": "message", "channels": ["group"]},
            {"id": "a", "type": "tool", "tool_name": "a", "args": {}},
            {"id": "b", "type": "tool", "tool_name": "b", "args": {}},
            {"id": "join", "type": "tool", "tool_name": "join", "args": {}},
        ],
        "edges": [
            {"from": "start", "to": "a"},
            {"from": "start", "to": "b"},
            {"from": "a", "to": "join"},
            {"from": "b", "to": "join"},
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
    assert order.index("start:join") > order.index("end:a")
    assert order.index("start:join") > order.index("end:b")


@pytest.mark.asyncio
async def test_runner_copies_tool_context_per_call() -> None:
    ids: list[int] = []

    async def execute_tool(
        name: str, args: dict[str, Any], context: dict[str, Any]
    ) -> str:
        _ = args
        ids.append(id(context))
        context["mutated"] = name
        await asyncio.sleep(0.01)
        return name

    shared: dict[str, Any] = {"shared": True}
    runner = _runner(execute_tool=execute_tool, tool_context=shared)
    task = {
        "auto_send_final": False,
        "nodes": [
            {"id": "start", "type": "start", "kind": "message", "channels": ["group"]},
            {"id": "left", "type": "tool", "tool_name": "left", "args": {}},
            {"id": "right", "type": "tool", "tool_name": "right", "args": {}},
        ],
        "edges": [
            {"from": "start", "to": "left"},
            {"from": "start", "to": "right"},
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
    assert len(ids) == 2
    assert ids[0] != ids[1]
    assert "mutated" not in shared


@pytest.mark.asyncio
async def test_runner_main_passes_session_identity() -> None:
    captured: list[dict[str, Any]] = []

    async def ask_main(prompt: str, extra: dict[str, Any]) -> str:
        _ = prompt
        captured.append(dict(extra))
        return "ok"

    runner = _runner(
        ask_main=ask_main,
        tool_context={
            "request_type": "group",
            "group_id": 1017148870,
            "user_id": 2608261902,
            "sender_id": 2608261902,
            "address": "group:1017148870",
            "channel": "group",
            "scheduled_task_id": "testtoviolet",
            "scheduled_task_name": "测试群祸害紫罗兰",
        },
    )
    task = {
        "auto_send_final": False,
        "nodes": [
            {"id": "start", "type": "start", "kind": "message", "channels": ["group"]},
            {
                "id": "llm_main",
                "type": "llm.main",
                "prompt": "list tools",
                "emit": False,
            },
        ],
        "edges": [{"from": "start", "to": "llm_main"}],
    }
    event = AutomationEvent(
        kind="message",
        channel="group",
        text="hi",
        group_id=1017148870,
        sender_id=2608261902,
        address="group:1017148870",
    )
    await runner.run(
        task,
        event=event,
        pass_text="hi",
        consume_mentions=(),
        consume_stripped="hi",
        mentions_all=(),
    )
    assert captured
    extra = captured[0]
    assert extra["group_id"] == 1017148870
    assert extra["address"] == "group:1017148870"
    assert extra["request_type"] == "group"
    assert extra["sender_id"] == 2608261902


def test_assign_node_output_named_and_skipped() -> None:
    from Undefined.automations.template import (
        assign_node_output,
        is_valid_output_var,
        render_template,
    )

    stored: dict[str, Any] = {"nodes": {}, "vars": {}}
    assign_node_output(
        stored,
        {
            "id": "fetch",
            "type": "tool",
            "store_output": True,
            "output_var": "hotspots",
        },
        "list-a",
    )
    assert stored["fetch"] == "list-a"
    assert stored["hotspots"] == "list-a"
    assert stored["vars"]["hotspots"] == "list-a"
    assert stored["nodes"]["fetch"]["output"] == "list-a"
    assert render_template("got {{hotspots}} / {{vars.hotspots}}", stored) == (
        "got list-a / list-a"
    )
    assert is_valid_output_var("hotspots")
    assert not is_valid_output_var("trigger")
    assert not is_valid_output_var("1hot")

    skipped: dict[str, Any] = {"nodes": {}, "vars": {}}
    assign_node_output(
        skipped,
        {
            "id": "fetch",
            "type": "tool",
            "store_output": False,
            "output_var": "hotspots",
        },
        "secret",
    )
    assert "fetch" not in skipped
    assert "hotspots" not in skipped
    assert render_template("got {{hotspots}}", skipped) == "got {{hotspots}}"


def test_parse_and_apply_extract_vars() -> None:
    from Undefined.automations.extract import (
        apply_extract_tool_call,
        assign_extracted_vars,
        build_extract_tools,
        extract_tool_name,
        parse_extract_vars,
    )

    node = {
        "type": "llm.main",
        "extract_vars": [
            {"name": "roast", "description": "吐槽"},
            {"name": "roast", "description": "重复应忽略"},
            {"name": "trigger", "description": "保留名"},
            {"name": "1bad", "description": "非法"},
            "skip-me",
        ],
    }
    specs = parse_extract_vars(node)
    assert [item.name for item in specs] == ["roast"]
    tools = build_extract_tools(specs)
    assert tools[0]["function"]["name"] == extract_tool_name("roast")
    sink: dict[str, str] = {}
    assert (
        apply_extract_tool_call(
            "extract_roast",
            {"value": "有槽点"},
            sink=sink,
            names={"roast"},
        )
        == "已写入变量 roast"
    )
    assert apply_extract_tool_call("web", {}, sink=sink, names={"roast"}) is None
    variables: dict[str, Any] = {"vars": {}}
    assign_extracted_vars(variables, sink)
    assert variables["roast"] == "有槽点"
    assert variables["vars"]["roast"] == "有槽点"
    assert parse_extract_vars({"type": "branch.llm", "extract_vars": specs}) == []


@pytest.mark.asyncio
async def test_blank_llm_extract_vars_are_available_downstream() -> None:
    captured: dict[str, Any] = {}

    async def submit_llm(
        **kwargs: Any,
    ) -> dict[str, Any]:
        captured["tools"] = kwargs.get("tools")
        messages = kwargs.get("messages") or []
        if any(
            isinstance(item, dict) and item.get("role") == "tool" for item in messages
        ):
            return {"choices": [{"message": {"content": "done"}}]}
        return {
            "choices": [
                {
                    "message": {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "c1",
                                "function": {
                                    "name": "extract_roast",
                                    "arguments": '{"value": "槽点来了"}',
                                },
                            }
                        ],
                    }
                }
            ]
        }

    sent: list[str] = []

    async def send_message(text: str) -> None:
        sent.append(text)

    runner = _runner(submit_llm=submit_llm, send_message=send_message)
    task = {
        "auto_send_final": False,
        "nodes": [
            {
                "id": "start",
                "type": "start",
                "kind": "message",
                "channels": ["group"],
            },
            {
                "id": "llm",
                "type": "llm.blank",
                "user_prompt": "{{trigger.text}}",
                "extract_vars": [{"name": "roast", "description": "吐槽"}],
                "emit": False,
            },
            {
                "id": "out",
                "type": "template",
                "template": "{{roast}}",
                "emit": True,
            },
        ],
        "edges": [
            {"from": "start", "to": "llm"},
            {"from": "llm", "to": "out"},
        ],
    }
    await runner.run(
        task,
        event=AutomationEvent(kind="message", channel="group", text="ssd"),
        pass_text="ssd",
        consume_mentions=(),
        consume_stripped="ssd",
        mentions_all=(),
    )
    assert sent == ["槽点来了"]
    tool_names = [
        str((schema.get("function") or {}).get("name") or "")
        for schema in captured.get("tools") or []
        if isinstance(schema, dict)
    ]
    assert "extract_roast" in tool_names


@pytest.mark.asyncio
async def test_main_llm_extract_vars_are_injected_into_ask() -> None:
    from Undefined.automations.extract import apply_extract_tool_call

    extra_seen: dict[str, Any] = {}

    async def ask_main(prompt: str, extra: dict[str, Any]) -> str:
        extra_seen.update(extra)
        sink = extra.get("automation_extract_sink")
        names = extra.get("automation_extract_names")
        assert isinstance(sink, dict)
        assert isinstance(names, set)
        apply_extract_tool_call(
            "extract_flag",
            {"value": "yes"},
            sink=sink,
            names=names,
        )
        assert "extract_flag" in prompt
        return "ok"

    sent: list[str] = []

    async def send_message(text: str) -> None:
        sent.append(text)

    runner = _runner(ask_main=ask_main, send_message=send_message)
    task = {
        "auto_send_final": False,
        "nodes": [
            {
                "id": "start",
                "type": "start",
                "kind": "message",
                "channels": ["group"],
            },
            {
                "id": "main",
                "type": "llm.main",
                "prompt": "看这句话",
                "extract_vars": [{"name": "flag", "description": "有没有槽点"}],
                "emit": False,
            },
            {
                "id": "out",
                "type": "template",
                "template": "{{flag}}",
                "emit": True,
            },
        ],
        "edges": [
            {"from": "start", "to": "main"},
            {"from": "main", "to": "out"},
        ],
    }
    await runner.run(
        task,
        event=AutomationEvent(kind="message", channel="group", text="hi"),
        pass_text="hi",
        consume_mentions=(),
        consume_stripped="hi",
        mentions_all=(),
    )
    assert sent == ["yes"]
    tools = extra_seen.get("automation_extract_tools")
    assert isinstance(tools, list)
    assert tools[0]["function"]["name"] == "extract_flag"


@pytest.mark.asyncio
async def test_agent_llm_extract_vars_are_injected_into_tool_context() -> None:
    from Undefined.automations.extract import apply_extract_tool_call

    captured: dict[str, Any] = {}

    async def execute_tool(
        name: str, args: dict[str, Any], context: dict[str, Any]
    ) -> str:
        captured["name"] = name
        captured["args"] = args
        captured["context"] = context
        sink = context.get("automation_extract_sink")
        names = context.get("automation_extract_names")
        assert isinstance(sink, dict)
        apply_extract_tool_call(
            "extract_tag",
            {"value": "ok"},
            sink=sink,
            names={str(item) for item in names or []},
        )
        return "agent-out"

    sent: list[str] = []

    async def send_message(text: str) -> None:
        sent.append(text)

    runner = _runner(execute_tool=execute_tool, send_message=send_message)
    task = {
        "auto_send_final": False,
        "nodes": [
            {
                "id": "start",
                "type": "start",
                "kind": "message",
                "channels": ["group"],
            },
            {
                "id": "agent",
                "type": "llm.agent",
                "agent": "info_agent",
                "input": "看这句话",
                "extract_vars": [{"name": "tag", "description": "标签"}],
                "emit": False,
            },
            {
                "id": "out",
                "type": "template",
                "template": "{{tag}}",
                "emit": True,
            },
        ],
        "edges": [
            {"from": "start", "to": "agent"},
            {"from": "agent", "to": "out"},
        ],
    }
    await runner.run(
        task,
        event=AutomationEvent(kind="message", channel="group", text="hi"),
        pass_text="hi",
        consume_mentions=(),
        consume_stripped="hi",
        mentions_all=(),
    )
    assert sent == ["ok"]
    assert captured["name"] == "info_agent"
    assert "extract_tag" in str(captured["args"].get("prompt") or "")
    tools = captured["context"].get("automation_extract_tools")
    assert isinstance(tools, list)
    assert tools[0]["function"]["name"] == "extract_tag"


@pytest.mark.asyncio
async def test_runner_stores_tool_and_llm_output_as_named_variables() -> None:
    sent: list[str] = []

    async def send_message(text: str) -> None:
        sent.append(text)

    async def execute_tool(
        name: str, args: dict[str, Any], context: dict[str, Any]
    ) -> str:
        _ = name, args, context
        return "hot-list"

    ask_main = AsyncMock(return_value="summary")
    runner = _runner(
        execute_tool=execute_tool,
        send_message=send_message,
        ask_main=ask_main,
    )
    task = {
        "auto_send_final": False,
        "nodes": [
            {
                "id": "start",
                "type": "start",
                "kind": "message",
                "channels": ["group"],
            },
            {
                "id": "fetch",
                "type": "tool",
                "tool_name": "web",
                "args": {},
                "store_output": True,
                "output_var": "hotspots",
            },
            {
                "id": "draft",
                "type": "llm.main",
                "prompt": "wrap {{hotspots}}",
                "store_output": True,
                "output_var": "summary",
            },
            {
                "id": "say",
                "type": "template",
                "template": "{{summary}} :: {{fetch}}",
                "emit": True,
            },
        ],
        "edges": [
            {"from": "start", "to": "fetch"},
            {"from": "fetch", "to": "draft"},
            {"from": "draft", "to": "say"},
        ],
    }
    await runner.run(
        task,
        event=AutomationEvent(kind="message", channel="group", text="go"),
        pass_text="go",
        consume_mentions=(),
        consume_stripped="go",
        mentions_all=(),
    )
    assert sent == ["summary :: hot-list"]
    ask_main.assert_awaited_once()
    assert ask_main.await_args is not None
    assert ask_main.await_args.args[0] == "wrap hot-list"


@pytest.mark.asyncio
async def test_runner_skips_variable_when_store_output_false() -> None:
    sent: list[str] = []

    async def send_message(text: str) -> None:
        sent.append(text)

    async def execute_tool(
        name: str, args: dict[str, Any], context: dict[str, Any]
    ) -> str:
        _ = name, args, context
        return "secret"

    runner = _runner(execute_tool=execute_tool, send_message=send_message)
    task = {
        "auto_send_final": False,
        "nodes": [
            {
                "id": "start",
                "type": "start",
                "kind": "message",
                "channels": ["group"],
            },
            {
                "id": "fetch",
                "type": "tool",
                "tool_name": "web",
                "args": {},
                "store_output": False,
                "output_var": "hotspots",
            },
            {
                "id": "say",
                "type": "template",
                "template": "got {{hotspots}} {{fetch}}",
                "emit": True,
            },
        ],
        "edges": [
            {"from": "start", "to": "fetch"},
            {"from": "fetch", "to": "say"},
        ],
    }
    await runner.run(
        task,
        event=AutomationEvent(kind="message", channel="group", text="go"),
        pass_text="go",
        consume_mentions=(),
        consume_stripped="go",
        mentions_all=(),
    )
    assert sent == ["got {{hotspots}} {{fetch}}"]


def test_validate_output_var_rules() -> None:
    reserved = collect_automation_issues(
        {
            "nodes": [
                {
                    "id": "start",
                    "type": "start",
                    "kind": "cron",
                    "cron": "* * * * *",
                },
                {
                    "id": "fetch",
                    "type": "tool",
                    "tool_name": "web",
                    "output_var": "trigger",
                },
            ],
            "edges": [{"from": "start", "to": "fetch"}],
        }
    )
    assert any("reserved" in item["message"] for item in reserved)

    invalid = collect_automation_issues(
        {
            "nodes": [
                {
                    "id": "start",
                    "type": "start",
                    "kind": "cron",
                    "cron": "* * * * *",
                },
                {
                    "id": "fetch",
                    "type": "tool",
                    "tool_name": "web",
                    "output_var": "1hot",
                },
            ],
            "edges": [{"from": "start", "to": "fetch"}],
        }
    )
    assert any("letter or underscore" in item["message"] for item in invalid)

    duplicate = collect_automation_issues(
        {
            "nodes": [
                {
                    "id": "start",
                    "type": "start",
                    "kind": "cron",
                    "cron": "* * * * *",
                },
                {
                    "id": "fetch",
                    "type": "tool",
                    "tool_name": "web",
                    "output_var": "hotspots",
                },
                {
                    "id": "other",
                    "type": "llm.main",
                    "prompt": "x",
                    "output_var": "hotspots",
                },
            ],
            "edges": [
                {"from": "start", "to": "fetch"},
                {"from": "fetch", "to": "other"},
            ],
        }
    )
    assert any("already used" in item["message"] for item in duplicate)

    extract_reserved = collect_automation_issues(
        {
            "nodes": [
                {
                    "id": "start",
                    "type": "start",
                    "kind": "cron",
                    "cron": "* * * * *",
                },
                {
                    "id": "llm",
                    "type": "llm.main",
                    "prompt": "x",
                    "extract_vars": [{"name": "trigger", "description": "x"}],
                },
            ],
            "edges": [{"from": "start", "to": "llm"}],
        }
    )
    assert any("reserved" in item["message"] for item in extract_reserved)

    extract_clash = collect_automation_issues(
        {
            "nodes": [
                {
                    "id": "start",
                    "type": "start",
                    "kind": "cron",
                    "cron": "* * * * *",
                },
                {
                    "id": "fetch",
                    "type": "tool",
                    "tool_name": "web",
                    "output_var": "roast",
                },
                {
                    "id": "llm",
                    "type": "llm.blank",
                    "user_prompt": "x",
                    "extract_vars": [{"name": "roast", "description": "吐槽"}],
                },
            ],
            "edges": [
                {"from": "start", "to": "fetch"},
                {"from": "fetch", "to": "llm"},
            ],
        }
    )
    assert any("already used" in item["message"] for item in extract_clash)

    extract_self = collect_automation_issues(
        {
            "nodes": [
                {
                    "id": "start",
                    "type": "start",
                    "kind": "cron",
                    "cron": "* * * * *",
                },
                {
                    "id": "llm",
                    "type": "llm.main",
                    "prompt": "x",
                    "output_var": "flag",
                    "extract_vars": [{"name": "flag", "description": "x"}],
                },
            ],
            "edges": [{"from": "start", "to": "llm"}],
        }
    )
    assert any("already used" in item["message"] for item in extract_self)


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


def test_automations_config_defaults() -> None:
    from Undefined.automations.constants import (
        DEFAULT_BLANK_LLM_MAX_ITERATIONS,
        DEFAULT_EVENT_COOLDOWN_SECONDS,
        DEFAULT_MAX_CONCURRENT,
        DEFAULT_NODE_TIMEOUT_SECONDS,
        DEFAULT_WORKFLOW_TIMEOUT_SECONDS,
    )
    from Undefined.config.models import AutomationsConfig

    cfg = AutomationsConfig()
    assert DEFAULT_MAX_CONCURRENT == 16
    assert DEFAULT_NODE_TIMEOUT_SECONDS == 600.0
    assert DEFAULT_WORKFLOW_TIMEOUT_SECONDS == 1200.0
    assert DEFAULT_BLANK_LLM_MAX_ITERATIONS == 100
    assert DEFAULT_EVENT_COOLDOWN_SECONDS == 0
    assert cfg.max_concurrent == 16
    assert cfg.node_timeout_seconds == 600.0
    assert cfg.workflow_timeout_seconds == 1200.0
    assert cfg.blank_llm_max_iterations == 100
    assert cfg.default_cooldown_seconds == 0


def test_event_automations_have_no_default_cooldown() -> None:
    from Undefined.automations.constants import DEFAULT_EVENT_COOLDOWN_SECONDS
    from Undefined.config.models import AutomationsConfig

    assert DEFAULT_EVENT_COOLDOWN_SECONDS == 0
    assert AutomationsConfig().default_cooldown_seconds == 0

    now = datetime.now(timezone.utc)
    tasks = {
        "a": {
            "enabled": True,
            "last_run_at": (now - timedelta(seconds=1)).isoformat(),
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
        now=now,
    )
    assert [task_id for task_id, _, _ in matched] == ["a"]


def test_iter_matching_honors_explicit_task_cooldown() -> None:
    now = datetime.now(timezone.utc)
    tasks = {
        "a": {
            "enabled": True,
            "cooldown_seconds": 60,
            "last_run_at": (now - timedelta(seconds=1)).isoformat(),
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
        now=now,
    )
    assert matched == []


class _DummyAutomationStorage:
    def load_tasks(self) -> dict[str, Any]:
        return {}

    async def save_all(self, _tasks: dict[str, Any]) -> None:
        return None


def _make_automation_service(*, max_concurrent: int = 16) -> AutomationService:
    return AutomationService(
        SimpleNamespace(
            ask=AsyncMock(),
            memory_storage=SimpleNamespace(),
            runtime_config=SimpleNamespace(
                automations=SimpleNamespace(max_concurrent=max_concurrent)
            ),
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
        storage=cast(Any, _DummyAutomationStorage()),
    )


def _group_message_task(*, consume_ai_loop: bool) -> dict[str, Any]:
    return {
        "enabled": True,
        "consume_ai_loop": consume_ai_loop,
        "nodes": [
            {
                "id": "start",
                "type": "start",
                "kind": "message",
                "channels": ["group"],
                "text": "",
            }
        ],
        "edges": [],
    }


@pytest.mark.asyncio
async def test_handle_event_nonblocking_returns_before_workflow_finishes() -> None:
    service = _make_automation_service()
    started = asyncio.Event()
    release = asyncio.Event()
    finished = asyncio.Event()

    async def slow_execute(*_args: Any, **_kwargs: Any) -> None:
        started.set()
        await release.wait()
        finished.set()

    setattr(service, "_execute_workflow", slow_execute)
    service.tasks["bg"] = _group_message_task(consume_ai_loop=False)
    event = AutomationEvent(kind="message", channel="group", text="hi", group_id=1)
    try:
        consumed = await service.handle_event(event)
        assert consumed is False
        assert finished.is_set() is False
        await asyncio.wait_for(started.wait(), timeout=1)
        assert finished.is_set() is False
        release.set()
        pending = list(service._background_tasks)
        if pending:
            await asyncio.wait_for(asyncio.gather(*pending), timeout=1)
        assert finished.is_set()
    finally:
        release.set()
        service.shutdown()


@pytest.mark.asyncio
async def test_handle_event_blocking_waits_for_workflow() -> None:
    service = _make_automation_service()
    order: list[str] = []

    async def execute(*_args: Any, **_kwargs: Any) -> None:
        order.append("start")
        await asyncio.sleep(0)
        order.append("done")

    setattr(service, "_execute_workflow", execute)
    service.tasks["block"] = _group_message_task(consume_ai_loop=True)
    event = AutomationEvent(kind="message", channel="group", text="hi", group_id=1)
    try:
        consumed = await service.handle_event(event)
        assert consumed is True
        assert order == ["start", "done"]
        assert not service._background_tasks
    finally:
        service.shutdown()


@pytest.mark.asyncio
async def test_handle_event_mixed_spawns_nonblocking_and_awaits_blocking() -> None:
    service = _make_automation_service()
    bg_started = asyncio.Event()
    bg_release = asyncio.Event()
    blocking_done = asyncio.Event()

    async def execute(task_id: str, **_kwargs: Any) -> None:
        if task_id == "bg":
            bg_started.set()
            await bg_release.wait()
            return
        blocking_done.set()

    setattr(service, "_execute_workflow", execute)
    service.tasks["bg"] = _group_message_task(consume_ai_loop=False)
    service.tasks["block"] = _group_message_task(consume_ai_loop=True)
    event = AutomationEvent(kind="message", channel="group", text="hi", group_id=1)
    try:
        consumed = await service.handle_event(event)
        assert consumed is True
        assert blocking_done.is_set()
        await asyncio.wait_for(bg_started.wait(), timeout=1)
        assert len(service._background_tasks) == 1
        bg_release.set()
        await asyncio.wait_for(
            asyncio.gather(*list(service._background_tasks)),
            timeout=1,
        )
    finally:
        bg_release.set()
        service.shutdown()


@pytest.mark.asyncio
async def test_automation_concurrency_limit_resizes_without_over_admission() -> None:
    service = _make_automation_service(max_concurrent=1)
    started = {task_id: asyncio.Event() for task_id in ("one", "two", "three")}
    releases = {task_id: asyncio.Event() for task_id in started}

    async def execute(task_id: str, **_kwargs: Any) -> None:
        started[task_id].set()
        await releases[task_id].wait()

    setattr(service, "_execute_workflow", execute)
    for task_id in started:
        service.tasks[task_id] = _group_message_task(consume_ai_loop=True)

    def start_run(task_id: str) -> asyncio.Task[None]:
        return asyncio.create_task(
            service._run_automation(
                task_id,
                event=AutomationEvent(
                    kind="message", channel="group", text="hi", group_id=1
                ),
                start_match=None,
                live_resources=None,
                time_fire=False,
            )
        )

    runs = [start_run("one")]
    try:
        await asyncio.wait_for(started["one"].wait(), timeout=1)
        runs.append(start_run("two"))
        await asyncio.sleep(0)
        assert not started["two"].is_set()

        await service.update_max_concurrent(2)
        await asyncio.wait_for(started["two"].wait(), timeout=1)

        await service.update_max_concurrent(1)
        runs.append(start_run("three"))
        await asyncio.sleep(0)
        releases["one"].set()
        await asyncio.sleep(0)
        assert not started["three"].is_set()

        releases["two"].set()
        await asyncio.wait_for(started["three"].wait(), timeout=1)
        releases["three"].set()
        await asyncio.wait_for(asyncio.gather(*runs), timeout=1)
        assert service._run_limiter.limit == 1
    finally:
        for release in releases.values():
            release.set()
        await asyncio.gather(*runs, return_exceptions=True)
        service.shutdown()


@pytest.mark.asyncio
async def test_nonblocking_automation_deep_copies_live_resources() -> None:
    service = _make_automation_service()
    inspect_snapshot = asyncio.Event()
    captured: list[dict[str, Any] | None] = []

    async def run_automation(
        _task_id: str,
        *,
        live_resources: dict[str, Any] | None,
        **_kwargs: Any,
    ) -> None:
        await inspect_snapshot.wait()
        captured.append(live_resources)

    setattr(service, "_run_automation", run_automation)
    resources: dict[str, Any] = {"attachments": [{"uid": "pic_original"}]}
    try:
        service._spawn_event_run(
            "snapshot",
            event=AutomationEvent(kind="message", channel="group", text="hi"),
            start_match=None,
            live_resources=resources,
        )
        resources["attachments"][0]["uid"] = "pic_mutated"
        inspect_snapshot.set()
        await asyncio.wait_for(
            asyncio.gather(*list(service._background_tasks)), timeout=1
        )
        assert captured == [{"attachments": [{"uid": "pic_original"}]}]
    finally:
        inspect_snapshot.set()
        service.shutdown()


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
    live_resources = handler.ai_coordinator.scheduler.handle_event.await_args.kwargs[
        "live_resources"
    ]
    assert live_resources["message_id"] == 1
    assert live_resources["message_ids"] == [1]
    assert live_resources["message_content"] == event["message"]
    assert live_resources["attachments"] == []
    assert live_resources["queue_lane"] == QUEUE_LANE_GROUP_NORMAL
    assert live_resources["batch_scope"] == "group:30001"
    assert live_resources["batched_count"] == 1
    assert live_resources["current_input_is_batched"] is False
    handler.ai_coordinator.handle_auto_reply.assert_not_awaited()


@pytest.mark.asyncio
async def test_member_join_notice_passes_nickname() -> None:
    handler = _group_handler()
    handler.onebot.get_group_member_info = AsyncMock(
        return_value={"card": "群名片", "nickname": "QQ昵称"}
    )
    captured: list[AutomationEvent] = []

    async def handle_event(event: AutomationEvent) -> bool:
        captured.append(event)
        return False

    handler.ai_coordinator.scheduler.handle_event = handle_event
    await handler._handle_member_notice(
        {
            "notice_type": "group_increase",
            "group_id": 30001,
            "user_id": 20001,
        }
    )
    assert len(captured) == 1
    assert captured[0].kind == "member_join"
    assert captured[0].nickname == "群名片"
    assert captured[0].user_id == 20001


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
    handler._collect_message_attachments = AsyncMock(
        return_value=RegisteredMessageAttachments(
            attachments=[{"uid": "pic_direct", "kind": "image"}],
            normalized_text="hello",
            forward_refs=[{"uid": "file_forward", "kind": "file"}],
        )
    )
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
    live_resources = handler.ai_coordinator.scheduler.handle_event.await_args.kwargs[
        "live_resources"
    ]
    assert live_resources["trigger_message_id"] == 1
    assert [item["uid"] for item in live_resources["attachments"]] == [
        "pic_direct",
        "file_forward",
    ]
    assert live_resources["queue_lane"] == QUEUE_LANE_PRIVATE
    assert live_resources["batch_scope"] == "private:20001"
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
    reply_context = ReplyContext(
        title="机器人",
        message_id="quoted-1",
        text="quoted text",
        attachments=({"uid": "pic_quote", "kind": "image"},),
    )
    await handler.handle_weixin_private_message(
        qq_id=1,
        text="hi",
        message_content=[{"type": "text", "data": {"text": "hi"}}],
        attachments=[{"uid": "pic_current", "kind": "image"}],
        sender_name="wx",
        message_id="m1",
        account_alias="primary",
        reply_context=reply_context,
    )
    handler.ai_coordinator.scheduler.handle_event.assert_awaited()
    call = handler.ai_coordinator.scheduler.handle_event.await_args
    assert call.args[0].channel == "wechat"
    live_resources = call.kwargs["live_resources"]
    assert live_resources["message_id"] == "m1"
    assert live_resources["attachments"] == [{"uid": "pic_current", "kind": "image"}]
    assert live_resources["reply_context"] == reply_context.to_dict()
    assert live_resources["queue_lane"] == QUEUE_LANE_PRIVATE
    assert live_resources["batch_scope"] == "private:wechat:1"
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


@pytest.mark.asyncio
async def test_automations_create_returns_400_for_invalid_schedule() -> None:
    scheduler = _make_automation_service()
    server = RuntimeAPIServer(_api_context(scheduler), host="127.0.0.1", port=8788)
    try:
        response = await server._automations_create_handler(
            cast(
                web.Request,
                _JsonRequest(
                    _json={
                        "task_id": "invalid_schedule",
                        "kind": "cron",
                        "cron": "invalid cron",
                        "prompt": "run",
                    }
                ),
            )
        )
        assert response.status == 400
        assert "invalid_schedule" not in scheduler.tasks
        assert scheduler._apscheduler.get_job("invalid_schedule") is None
    finally:
        scheduler.shutdown()


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
    assert "node_type_meta" in catalog_body
    assert {item["id"] for item in catalog_body["node_type_meta"]} >= {
        "tool",
        "branch.if",
        "loop.each",
    }
    assert catalog_body["tools"] == []
    assert catalog_body["agents"] == []
    welcome = next(
        item for item in catalog_body["presets"] if item["id"] == "member_join_welcome"
    )
    welcome_template = welcome["task"]["nodes"][1]["template"]
    assert "{{trigger.nickname}}" in welcome_template
    assert "{{trigger.user_id}}" not in welcome_template

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


def test_collect_automation_issues_reports_multiple_problems() -> None:
    issues = collect_automation_issues(
        {
            "nodes": [
                {"id": "start", "type": "start", "kind": "message"},
                {
                    "id": "iff",
                    "type": "branch.if",
                    "cases": [],
                },
            ],
            "edges": [{"from": "iff", "to": "missing"}],
        }
    )
    messages = [item["message"] for item in issues]
    assert "event start requires channels" in messages
    assert "branch.if requires cases" in messages
    assert any("unknown node" in message for message in messages)


def _single_node_validation_task(
    node: dict[str, Any],
    *,
    start: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "nodes": [
            start
            or {
                "id": "start",
                "type": "start",
                "kind": "message",
                "channels": ["group"],
            },
            node,
        ],
        "edges": [{"from": "start", "to": str(node["id"])}],
    }


@pytest.mark.parametrize(
    ("kind", "field", "value", "path"),
    [
        ("cron", "cron", "not a cron", "start.cron"),
        ("daily", "time", "9:00", "start.time"),
        ("daily", "time", "24:00", "start.time"),
        ("daily", "time", "12:60", "start.time"),
        ("at", "at", "2026-08-19", "start.at"),
        ("at", "at", "not-a-datetime", "start.at"),
    ],
)
def test_validate_rejects_invalid_time_start_formats(
    kind: str,
    field: str,
    value: str,
    path: str,
) -> None:
    start = {"id": "start", "type": "start", "kind": kind, field: value}
    issues = collect_automation_issues(
        _single_node_validation_task(
            {"id": "done", "type": "template", "template": "ok"},
            start=start,
        )
    )
    assert any(issue["path"] == path for issue in issues)


@pytest.mark.parametrize(
    ("start",),
    [
        ({"id": "start", "type": "start", "kind": "cron", "cron": "0 9 * * *"},),
        ({"id": "start", "type": "start", "kind": "daily", "time": "09:05"},),
        (
            {
                "id": "start",
                "type": "start",
                "kind": "at",
                "at": "2026-08-20T09:05:00+08:00",
            },
        ),
    ],
)
def test_validate_accepts_supported_time_start_formats(
    start: dict[str, Any],
) -> None:
    validate_automation(
        _single_node_validation_task(
            {"id": "done", "type": "template", "template": "ok"},
            start=start,
        )
    )


@pytest.mark.parametrize(
    ("node", "path"),
    [
        ({"id": "node", "type": "tool"}, "nodes.node.tool_name"),
        (
            {"id": "node", "type": "llm.agent", "input": "do it"},
            "nodes.node.agent",
        ),
        (
            {"id": "node", "type": "llm.agent", "agent": "web"},
            "nodes.node.input",
        ),
        ({"id": "node", "type": "llm.main"}, "nodes.node.prompt"),
        ({"id": "node", "type": "llm.blank"}, "nodes.node.user_prompt"),
        (
            {
                "id": "node",
                "type": "branch.llm",
                "options": [{"id": "a"}, {"id": "b"}],
            },
            "nodes.node.input",
        ),
    ],
)
def test_validate_requires_runtime_node_fields(
    node: dict[str, Any],
    path: str,
) -> None:
    issues = collect_automation_issues(_single_node_validation_task(node))
    assert any(issue["path"] == path for issue in issues)


def test_validate_requires_complete_branch_edges() -> None:
    task = {
        "nodes": [
            {
                "id": "start",
                "type": "start",
                "kind": "message",
                "channels": ["group"],
            },
            {
                "id": "if",
                "type": "branch.if",
                "cases": [{"id": "hit", "text": "yes"}],
            },
            {
                "id": "llm",
                "type": "branch.llm",
                "input": "{{trigger.text}}",
                "options": [{"id": "left"}, {"id": "right"}],
            },
            {"id": "done", "type": "template", "template": "ok"},
        ],
        "edges": [
            {"from": "start", "to": "if"},
            {"from": "if", "to": "llm", "case": "hit"},
            {"from": "if", "to": "done", "case": "unknown"},
            {"from": "llm", "to": "done", "case": "left"},
        ],
    }
    messages = [issue["message"] for issue in collect_automation_issues(task)]
    assert "unknown branch case: unknown" in messages
    assert "branch case requires an outgoing edge: else" in messages
    assert "branch case requires an outgoing edge: right" in messages


def test_validate_reachability_understands_loop_bodies() -> None:
    task = {
        "nodes": [
            {"id": "start", "type": "start", "kind": "cron", "cron": "0 9 * * *"},
            {"id": "loop", "type": "loop.times", "count": 2, "body": ["body"]},
            {"id": "body", "type": "template", "template": "{{index}}"},
            {"id": "after", "type": "template", "template": "done"},
            {"id": "detached", "type": "template", "template": "never"},
        ],
        "edges": [
            {"from": "start", "to": "loop"},
            {"from": "loop", "to": "after", "kind": "exit"},
        ],
    }
    issues = collect_automation_issues(task)
    unreachable_paths = {
        issue["path"]
        for issue in issues
        if issue["message"] == "node is not reachable from start"
    }
    assert unreachable_paths == {"nodes.detached"}


@pytest.mark.asyncio
async def test_automations_validate_and_ui_roundtrip() -> None:
    scheduler = _FakeAutoScheduler()
    ai = SimpleNamespace(
        memory_storage=None,
        tool_registry=SimpleNamespace(
            get_tools_schema=lambda: [
                {
                    "type": "function",
                    "function": {
                        "name": "echo",
                        "description": "Echo text",
                    },
                },
                {
                    "type": "function",
                    "function": {
                        "name": "render.render_markdown",
                        "description": "Render",
                    },
                },
            ]
        ),
        agent_registry=SimpleNamespace(
            get_agents_schema=lambda: [
                {
                    "type": "function",
                    "function": {"name": "web_agent", "description": "Web"},
                }
            ]
        ),
    )
    ctx = _api_context(scheduler)
    ctx.ai = ai
    server = RuntimeAPIServer(ctx, host="127.0.0.1", port=8788)
    catalog = await server._automations_catalog_handler(
        cast(web.Request, SimpleNamespace())
    )
    catalog_body = json.loads(catalog.text or "{}")
    assert [item["name"] for item in catalog_body["tools"]] == [
        "echo",
        "render.render_markdown",
    ]
    assert catalog_body["toolsets"] == ["render"]
    assert catalog_body["agents"][0]["name"] == "web_agent"

    invalid = await server._automations_validate_handler(
        cast(
            web.Request,
            _JsonRequest(
                _json={
                    "nodes": [
                        {"id": "start", "type": "start", "kind": "message"},
                    ],
                    "edges": [],
                }
            ),
        )
    )
    invalid_body = json.loads(invalid.text or "{}")
    assert invalid_body["ok"] is False
    assert invalid_body["issues"]

    created = await server._automations_create_handler(
        cast(
            web.Request,
            _JsonRequest(
                _json={
                    "task_id": "laid_out",
                    "task_name": "布局",
                    "nodes": [
                        {
                            "id": "start",
                            "type": "start",
                            "kind": "message",
                            "channels": ["group"],
                        },
                        {
                            "id": "main",
                            "type": "template",
                            "template": "ok",
                            "emit": True,
                        },
                    ],
                    "edges": [{"from": "start", "to": "main"}],
                    "ui": {
                        "zoom": 1.2,
                        "pan": {"x": 10, "y": 20},
                        "positions": {
                            "start": {"x": 0, "y": 0},
                            "main": {"x": 240, "y": 0},
                        },
                    },
                }
            ),
        )
    )
    assert created.status == 201
    created_body = json.loads(created.text or "{}")
    assert created_body["task"]["ui"]["zoom"] == 1.2
    assert created_body["task"]["ui"]["positions"]["main"]["x"] == 240

    valid = await server._automations_validate_handler(
        cast(web.Request, _JsonRequest(_json=created_body["task"]))
    )
    valid_body = json.loads(valid.text or "{}")
    assert valid_body["ok"] is True
    assert valid_body["issues"] == []
