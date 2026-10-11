"""Persisted loop graphs retain their legacy default-count behavior."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, call

import pytest

from Undefined.automations.match import AutomationEvent
from Undefined.automations.service import AutomationService
from Undefined.automations.storage import AutomationStorage


@pytest.mark.asyncio
@pytest.mark.parametrize("count_mode", ["null", "missing", "zero"])
async def test_persisted_loop_count_runs_through_event_service(
    tmp_path: Path, count_mode: str
) -> None:
    loop: dict[str, Any] = {
        "id": "loop",
        "type": "loop.times",
        "body": ["body"],
        "max_iterations": 3,
    }
    if count_mode != "missing":
        loop["count"] = None if count_mode == "null" else 0
    task = {
        "enabled": True,
        "consume_ai_loop": True,
        "auto_send_final": False,
        "nodes": [
            {
                "id": "start",
                "type": "start",
                "kind": "message",
                "channels": ["group"],
                "text": "run",
            },
            loop,
            {
                "id": "body",
                "type": "template",
                "template": "iteration {{index}}",
                "emit": True,
            },
            {"id": "after", "type": "template", "template": "after", "emit": True},
        ],
        "edges": [
            {"from": "start", "to": "loop"},
            {"from": "loop", "to": "after", "kind": "exit"},
        ],
    }
    path = tmp_path / "automations.json"
    path.write_text(json.dumps({"legacy": task}), encoding="utf-8")
    storage = AutomationStorage(path=path)
    sender = SimpleNamespace(send_group_message=AsyncMock())
    service = AutomationService(
        SimpleNamespace(
            memory_storage=SimpleNamespace(),
            runtime_config=SimpleNamespace(
                automations=SimpleNamespace(loop_max_iterations=2)
            ),
        ),
        sender,
        SimpleNamespace(get_image=AsyncMock(), get_forward_msg=AsyncMock()),
        SimpleNamespace(),
        storage=storage,
    )
    try:
        consumed = await service.handle_event(
            AutomationEvent(kind="message", channel="group", group_id=1, text="run")
        )
        assert consumed is True
        persisted = storage.load_tasks()["legacy"]
        assert persisted["last_status"] == "ok", persisted["last_error"]
        assert persisted["current_executions"] == 1
        expected = [] if count_mode == "zero" else ["iteration 0", "iteration 1"]
        expected.append("after")
        assert sender.send_group_message.await_args_list == [
            call(1, message, reply_to=None) for message in expected
        ]
    finally:
        service.shutdown()
