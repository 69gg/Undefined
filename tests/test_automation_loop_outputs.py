"""Parallel loop scopes must not publish stale copies of sibling outputs."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from Undefined.automations.match import AutomationEvent
from Undefined.automations.runner import WorkflowRunner
from Undefined.automations.validate import validate_automation


@pytest.mark.asyncio
@pytest.mark.parametrize("inner_type", ["loop.times", "loop.each"])
async def test_nested_loop_preserves_concurrently_published_sibling_outputs(
    inner_type: str,
) -> None:
    entered = [asyncio.Event(), asyncio.Event()]
    release = [asyncio.Event(), asyncio.Event()]
    inner_calls = 0
    observed: list[str] = []

    async def execute_tool(
        name: str, args: dict[str, Any], context: dict[str, Any]
    ) -> str:
        nonlocal inner_calls
        if name == "inner_body":
            iteration = inner_calls
            inner_calls += 1
            entered[iteration].set()
            await release[iteration].wait()
            return "inner"
        iteration = int(args["index"])
        if name == "producer":
            await entered[iteration].wait()
            return str(iteration)
        if name == "signal":
            release[iteration].set()
            return ""
        observed.append(str(args["value"]))
        return ""

    runner = WorkflowRunner(
        execute_tool=execute_tool,
        ask_main=AsyncMock(return_value=""),
        submit_llm=AsyncMock(return_value={"choices": []}),
        send_message=AsyncMock(),
        get_openai_tools=lambda: [],
        agent_config=SimpleNamespace(max_tokens=16),
        tool_context={},
    )
    task: dict[str, Any] = {
        "auto_send_final": False,
        "nodes": [
            {"id": "start", "type": "start", "kind": "cron", "cron": "0 9 * * *"},
            {
                "id": "outer",
                "type": "loop.times",
                "count": 2,
                "body": ["producer", "signal", "inner", "join"],
            },
            {
                "id": "producer",
                "type": "tool",
                "tool_name": "producer",
                "args": {"index": "{{index}}"},
                "output_var": "produced",
            },
            {
                "id": "signal",
                "type": "tool",
                "tool_name": "signal",
                "args": {"index": "{{index}}"},
            },
            {
                "id": "inner",
                "type": inner_type,
                "count": 1,
                "source": '["one"]',
                "body": ["inner_body"],
            },
            {"id": "inner_body", "type": "tool", "tool_name": "inner_body"},
            {
                "id": "join",
                "type": "tool",
                "tool_name": "join",
                "args": {
                    "index": "{{index}}",
                    "value": "{{producer}}|{{nodes.producer.output}}|{{produced}}|{{vars.produced}}",
                },
            },
        ],
        "edges": [
            {"from": "start", "to": "outer"},
            {"from": "producer", "to": "signal"},
            {"from": "signal", "to": "join"},
            {"from": "inner", "to": "join"},
        ],
    }
    validate_automation(task)
    await asyncio.wait_for(
        runner.run(
            task,
            event=AutomationEvent(kind="time", channel="group"),
            pass_text="",
            consume_mentions=(),
            consume_stripped="",
            mentions_all=(),
        ),
        timeout=2,
    )
    assert observed == ["0|0|0|0", "1|1|1|1"]
