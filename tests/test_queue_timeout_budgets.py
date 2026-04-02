from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from Undefined.ai.queue_budget import compute_queued_llm_timeout_seconds
from Undefined.services.command import CommandDispatcher
from Undefined.skills.agents.intro_generator import (
    AgentIntroGenConfig,
    AgentIntroGenerator,
)
from Undefined.webui.routes import _runtime as runtime_routes


@pytest.mark.asyncio
async def test_stats_analysis_wait_timeout_uses_queue_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dispatcher: Any = object.__new__(CommandDispatcher)
    dispatcher.ai = SimpleNamespace(
        runtime_config=SimpleNamespace(ai_request_max_retries=2)
    )
    dispatcher.config = SimpleNamespace(
        chat_model=SimpleNamespace(queue_interval_seconds=10.0, model_name="chat-model")
    )
    dispatcher.queue_manager = SimpleNamespace()
    dispatcher._stats_analysis_events = {}
    dispatcher._stats_analysis_results = {}
    dispatcher._build_data_summary = lambda summary, days: f"{summary}-{days}"

    expected_timeout = compute_queued_llm_timeout_seconds(
        dispatcher.ai.runtime_config,
        dispatcher.config.chat_model,
    )
    original_wait_for = asyncio.wait_for
    seen: dict[str, float] = {}

    async def _wait_for(awaitable: Any, timeout: float) -> Any:
        seen["timeout"] = timeout
        return await original_wait_for(awaitable, timeout)

    async def _enqueue(request: dict[str, Any], model_name: str) -> None:
        _ = model_name
        dispatcher._stats_analysis_results[request["request_id"]] = "ok"
        dispatcher._stats_analysis_events[request["request_id"]].set()

    monkeypatch.setattr("Undefined.services.command.asyncio.wait_for", _wait_for)
    dispatcher.queue_manager.add_group_mention_request = _enqueue

    result = await CommandDispatcher._run_stats_ai_analysis(
        dispatcher,
        scope="group",
        scope_id=10001,
        sender_id=20002,
        summary={"value": 1},
        days=7,
    )

    assert result == "ok"
    assert seen["timeout"] == expected_timeout


@pytest.mark.asyncio
async def test_intro_generator_wait_timeout_uses_queue_budget(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    agent_dir = tmp_path / "demo_agent"
    agent_dir.mkdir()
    (agent_dir / "config.json").write_text("{}", encoding="utf-8")
    (agent_dir / "handler.py").write_text("pass\n", encoding="utf-8")

    ai_client = SimpleNamespace(
        runtime_config=SimpleNamespace(ai_request_max_retries=1),
        agent_config=SimpleNamespace(queue_interval_seconds=15.0, model_name="agent"),
    )
    queue_manager = SimpleNamespace()
    generator = AgentIntroGenerator(
        tmp_path,
        ai_client,
        queue_manager,
        AgentIntroGenConfig(cache_path=tmp_path / "cache.json"),
    )
    monkeypatch.setattr(
        generator, "_write_intro_file", lambda *_args, **_kwargs: asyncio.sleep(0)
    )
    monkeypatch.setattr(generator, "_compute_agent_hash", lambda _agent_dir: "digest")
    monkeypatch.setattr(generator, "_save_cache", lambda: asyncio.sleep(0))

    expected_timeout = compute_queued_llm_timeout_seconds(
        ai_client.runtime_config,
        ai_client.agent_config,
    )
    original_wait_for = asyncio.wait_for
    seen: dict[str, float] = {}

    async def _wait_for(awaitable: Any, timeout: float) -> Any:
        seen["timeout"] = timeout
        return await original_wait_for(awaitable, timeout)

    async def _enqueue(request: dict[str, Any], model_name: str) -> None:
        _ = model_name
        generator.set_intro_generation_result(request["request_id"], "intro")

    monkeypatch.setattr(
        "Undefined.skills.agents.intro_generator.asyncio.wait_for", _wait_for
    )
    queue_manager.add_agent_intro_request = _enqueue

    await generator._worker_loop([("demo_agent", agent_dir)])

    assert seen["timeout"] == expected_timeout


def test_chat_proxy_timeout_uses_queue_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = SimpleNamespace(
        ai_request_max_retries=3,
        chat_model=SimpleNamespace(queue_interval_seconds=20.0),
    )
    monkeypatch.setattr(
        runtime_routes, "get_config", lambda strict=False: cast(Any, cfg)
    )

    assert (
        runtime_routes._chat_proxy_timeout_seconds()
        == compute_queued_llm_timeout_seconds(
            cfg,
            cfg.chat_model,
        )
    )


def test_tool_invoke_proxy_timeout_uses_local_schema_sets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = SimpleNamespace(api=SimpleNamespace(tool_invoke_timeout=120))
    monkeypatch.setattr(
        runtime_routes, "get_config", lambda strict=False: cast(Any, cfg)
    )
    monkeypatch.setattr(
        runtime_routes,
        "_get_local_agent_tool_names",
        lambda: {"custom_agent_runner"},
    )
    monkeypatch.setattr(
        runtime_routes,
        "_get_local_tool_names",
        lambda: {"messages.send_message"},
    )

    assert runtime_routes._tool_invoke_proxy_timeout_seconds("custom_agent_runner") is None
    assert (
        runtime_routes._tool_invoke_proxy_timeout_seconds("messages.send_message")
        == 180.0
    )
    assert runtime_routes._tool_invoke_proxy_timeout_seconds("unknown_tool") is None
