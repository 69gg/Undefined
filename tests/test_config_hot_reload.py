from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, cast

import pytest

from Undefined.config.hot_reload import HotReloadContext, apply_config_updates


class _FakeSecurityService:
    def __init__(self) -> None:
        self.applied: list[Any] = []

    def apply_config(self, config: Any) -> None:
        self.applied.append(config)


class _FakeQueueManager:
    def __init__(self) -> None:
        self.intervals: list[Any] = []
        self.max_retries: list[int] = []

    def update_model_intervals(self, intervals: Any) -> None:
        self.intervals.append(intervals)

    def update_max_retries(self, max_retries: int) -> None:
        self.max_retries.append(max_retries)


class _FakeAIClient:
    def __init__(self) -> None:
        self.model_updates: list[dict[str, Any]] = []
        self.runtime_updates: list[Any] = []
        self.attachment_updates: list[Any] = []

    def apply_model_configs(
        self,
        *,
        chat_config: Any,
        vision_config: Any,
        agent_config: Any,
        runtime_config: Any,
    ) -> None:
        self.model_updates.append(
            {
                "chat": chat_config,
                "vision": vision_config,
                "agent": agent_config,
                "runtime": runtime_config,
            }
        )

    def apply_runtime_config(self, runtime_config: Any) -> None:
        self.runtime_updates.append(runtime_config)

    def apply_attachment_config(self, runtime_config: Any) -> None:
        self.attachment_updates.append(runtime_config)


class _FakeReloadRegistry:
    def __init__(self) -> None:
        self.started: list[tuple[float, float]] = []
        self.stopped = 0

    async def stop_hot_reload(self) -> None:
        self.stopped += 1

    def start_hot_reload(self, *, interval: float, debounce: float) -> None:
        self.started.append((interval, debounce))


class _FakeMessageHandler:
    def __init__(self) -> None:
        self.reload_updates: list[tuple[bool, float, float]] = []

    async def apply_skills_hot_reload_config(
        self,
        *,
        enabled: bool,
        interval: float,
        debounce: float,
    ) -> None:
        self.reload_updates.append((enabled, interval, debounce))


class _FakeConfigManager:
    def __init__(self) -> None:
        self.stopped = 0
        self.started: list[tuple[float, float]] = []

    async def stop_hot_reload(self) -> None:
        self.stopped += 1

    def start_hot_reload(self, *, interval: float, debounce: float) -> None:
        self.started.append((interval, debounce))


def test_apply_config_updates_propagates_to_security_service() -> None:
    updated = cast(
        Any,
        SimpleNamespace(
            searxng_url="",
            ai_request_max_retries=7,
            agent_intro_autogen_enabled=False,
            agent_intro_autogen_queue_interval=60.0,
            agent_intro_autogen_max_tokens=512,
            agent_intro_hash_path="data/intro.json",
            chat_model=SimpleNamespace(
                model_name="chat",
                queue_interval_seconds=1.0,
                pool=SimpleNamespace(enabled=False),
            ),
            agent_model=SimpleNamespace(
                model_name="agent",
                queue_interval_seconds=1.0,
                pool=SimpleNamespace(enabled=False),
            ),
            vision_model=SimpleNamespace(
                model_name="vision",
                queue_interval_seconds=1.0,
            ),
            security_model=SimpleNamespace(
                model_name="security",
                queue_interval_seconds=1.0,
            ),
            naga_model=SimpleNamespace(
                model_name="naga",
                queue_interval_seconds=1.0,
            ),
            grok_model=SimpleNamespace(
                model_name="grok",
                queue_interval_seconds=1.0,
            ),
            historian_model=SimpleNamespace(
                model_name="historian",
                queue_interval_seconds=1.0,
            ),
        ),
    )
    security_service = _FakeSecurityService()
    queue_manager = _FakeQueueManager()
    context = HotReloadContext(
        ai_client=cast(Any, SimpleNamespace()),
        queue_manager=cast(Any, queue_manager),
        config_manager=cast(Any, SimpleNamespace()),
        security_service=cast(Any, security_service),
    )

    apply_config_updates(
        updated,
        {"naga_model.model_name": ("old", "new")},
        context,
    )

    assert security_service.applied == [updated]
    assert len(queue_manager.intervals) == 1
    assert queue_manager.max_retries == []


def test_apply_config_updates_hot_reloads_ai_request_max_retries() -> None:
    updated = cast(
        Any,
        SimpleNamespace(
            searxng_url="",
            ai_request_max_retries=9,
            agent_intro_autogen_enabled=False,
            agent_intro_autogen_queue_interval=60.0,
            agent_intro_autogen_max_tokens=512,
            agent_intro_hash_path="data/intro.json",
            chat_model=SimpleNamespace(
                model_name="chat",
                queue_interval_seconds=1.0,
                pool=SimpleNamespace(enabled=False),
            ),
            agent_model=SimpleNamespace(
                model_name="agent",
                queue_interval_seconds=1.0,
                pool=SimpleNamespace(enabled=False),
            ),
            vision_model=SimpleNamespace(
                model_name="vision",
                queue_interval_seconds=1.0,
            ),
            security_model=SimpleNamespace(
                model_name="security",
                queue_interval_seconds=1.0,
            ),
            naga_model=SimpleNamespace(
                model_name="naga",
                queue_interval_seconds=1.0,
            ),
            grok_model=SimpleNamespace(
                model_name="grok",
                queue_interval_seconds=1.0,
            ),
            historian_model=SimpleNamespace(
                model_name="historian",
                queue_interval_seconds=1.0,
            ),
        ),
    )
    security_service = _FakeSecurityService()
    queue_manager = _FakeQueueManager()
    context = HotReloadContext(
        ai_client=cast(Any, SimpleNamespace()),
        queue_manager=cast(Any, queue_manager),
        config_manager=cast(Any, SimpleNamespace()),
        security_service=cast(Any, security_service),
    )

    apply_config_updates(
        updated,
        {"ai_request_max_retries": (2, 9)},
        context,
    )

    assert queue_manager.max_retries == [9]


def test_apply_config_updates_hot_reloads_ai_model_configs() -> None:
    updated = cast(
        Any,
        SimpleNamespace(
            searxng_url="",
            ai_request_max_retries=2,
            agent_intro_autogen_enabled=False,
            agent_intro_autogen_queue_interval=60.0,
            agent_intro_autogen_max_tokens=512,
            agent_intro_hash_path="data/intro.json",
            chat_model=SimpleNamespace(
                model_name="chat",
                queue_interval_seconds=1.0,
                stream_enabled=True,
                pool=SimpleNamespace(enabled=False),
            ),
            agent_model=SimpleNamespace(
                model_name="agent",
                queue_interval_seconds=1.0,
                stream_enabled=False,
                pool=SimpleNamespace(enabled=False),
            ),
            vision_model=SimpleNamespace(
                model_name="vision",
                queue_interval_seconds=1.0,
                stream_enabled=True,
            ),
            security_model=SimpleNamespace(
                model_name="security",
                queue_interval_seconds=1.0,
            ),
            naga_model=SimpleNamespace(
                model_name="naga",
                queue_interval_seconds=1.0,
            ),
            grok_model=SimpleNamespace(
                model_name="grok",
                queue_interval_seconds=1.0,
            ),
            historian_model=SimpleNamespace(
                model_name="historian",
                queue_interval_seconds=1.0,
            ),
        ),
    )
    security_service = _FakeSecurityService()
    queue_manager = _FakeQueueManager()
    ai_client = _FakeAIClient()
    context = HotReloadContext(
        ai_client=cast(Any, ai_client),
        queue_manager=cast(Any, queue_manager),
        config_manager=cast(Any, SimpleNamespace()),
        security_service=cast(Any, security_service),
    )

    apply_config_updates(
        updated,
        {"chat_model.stream_enabled": (False, True)},
        context,
    )

    assert len(ai_client.model_updates) == 1
    assert ai_client.model_updates[0]["chat"].stream_enabled is True
    assert ai_client.model_updates[0]["vision"].stream_enabled is True
    assert ai_client.model_updates[0]["agent"].stream_enabled is False


def test_apply_config_updates_runtime_model_config_without_rebuilding_core_models() -> (
    None
):
    updated = cast(
        Any,
        SimpleNamespace(
            searxng_url="",
            ai_request_max_retries=2,
            agent_intro_autogen_enabled=False,
            agent_intro_autogen_queue_interval=60.0,
            agent_intro_autogen_max_tokens=512,
            agent_intro_hash_path="data/intro.json",
            chat_model=SimpleNamespace(
                model_name="chat",
                queue_interval_seconds=1.0,
                stream_enabled=True,
                pool=SimpleNamespace(enabled=False),
            ),
            agent_model=SimpleNamespace(
                model_name="agent",
                queue_interval_seconds=1.0,
                stream_enabled=False,
                pool=SimpleNamespace(enabled=False),
            ),
            vision_model=SimpleNamespace(
                model_name="vision",
                queue_interval_seconds=1.0,
                stream_enabled=True,
            ),
            security_model=SimpleNamespace(
                model_name="security",
                queue_interval_seconds=1.0,
            ),
            naga_model=SimpleNamespace(
                model_name="naga",
                queue_interval_seconds=1.0,
            ),
            grok_model=SimpleNamespace(
                model_name="grok",
                queue_interval_seconds=1.0,
            ),
            historian_model=SimpleNamespace(
                model_name="historian",
                queue_interval_seconds=1.0,
            ),
            summary_model=SimpleNamespace(
                model_name="summary-new",
                queue_interval_seconds=1.0,
            ),
        ),
    )
    ai_client = _FakeAIClient()
    queue_manager = _FakeQueueManager()
    context = HotReloadContext(
        ai_client=cast(Any, ai_client),
        queue_manager=cast(Any, queue_manager),
        config_manager=cast(Any, SimpleNamespace()),
        security_service=cast(Any, _FakeSecurityService()),
    )

    apply_config_updates(
        updated,
        {"summary_model.model_name": ("summary-old", "summary-new")},
        context,
    )

    assert ai_client.model_updates == []
    assert ai_client.runtime_updates == [updated]
    assert len(queue_manager.intervals) == 1


def test_apply_config_updates_hot_reloads_missing_tool_call_retries() -> None:
    updated = cast(
        Any,
        SimpleNamespace(
            searxng_url="",
            missing_tool_call_retries=4,
        ),
    )
    ai_client = _FakeAIClient()
    context = HotReloadContext(
        ai_client=cast(Any, ai_client),
        queue_manager=cast(Any, _FakeQueueManager()),
        config_manager=cast(Any, SimpleNamespace()),
        security_service=cast(Any, _FakeSecurityService()),
    )

    apply_config_updates(
        updated,
        {"missing_tool_call_retries": (3, 4)},
        context,
    )

    assert ai_client.runtime_updates == [updated]


def test_apply_config_updates_hot_reloads_tool_search_config() -> None:
    updated = cast(
        Any,
        SimpleNamespace(
            tool_search_enabled=True,
            tool_search_always_loaded=["send_message", "end"],
            tool_search_max_results=8,
        ),
    )
    ai_client = _FakeAIClient()
    context = HotReloadContext(
        ai_client=cast(Any, ai_client),
        queue_manager=cast(Any, _FakeQueueManager()),
        config_manager=cast(Any, SimpleNamespace()),
        security_service=cast(Any, _FakeSecurityService()),
    )

    apply_config_updates(
        updated,
        {
            "tool_search_enabled": (False, True),
            "tool_search_always_loaded": (
                ["send_message", "end"],
                ["send_message", "end", "get_current_time"],
            ),
            "tool_search_max_results": (5, 8),
        },
        context,
    )

    assert ai_client.runtime_updates == [updated]


def test_apply_config_updates_hot_reloads_long_image_defaults() -> None:
    updated = cast(
        Any,
        SimpleNamespace(
            render_long_image_default_width=1080,
            render_long_image_default_padding=36,
        ),
    )
    ai_client = _FakeAIClient()
    context = HotReloadContext(
        ai_client=cast(Any, ai_client),
        queue_manager=cast(Any, _FakeQueueManager()),
        config_manager=cast(Any, SimpleNamespace()),
        security_service=cast(Any, _FakeSecurityService()),
    )

    apply_config_updates(
        updated,
        {
            "render_long_image_default_width": (900, 1080),
            "render_long_image_default_padding": (28, 36),
        },
        context,
    )

    assert ai_client.runtime_updates == [updated]


def test_apply_config_updates_hot_reloads_attachment_config() -> None:
    updated = cast(
        Any,
        SimpleNamespace(
            searxng_url="",
            ai_request_max_retries=2,
            attachment_remote_download_max_size_mb=8,
            attachment_cache_max_total_size_mb=512,
            attachment_cache_max_records=300,
            attachment_cache_max_age_days=14,
            attachment_url_reference_max_records=150,
            attachment_url_max_length=4096,
            chat_model=SimpleNamespace(
                model_name="chat",
                queue_interval_seconds=1.0,
                pool=SimpleNamespace(enabled=False),
            ),
            agent_model=SimpleNamespace(
                model_name="agent",
                queue_interval_seconds=1.0,
                pool=SimpleNamespace(enabled=False),
            ),
            vision_model=SimpleNamespace(
                model_name="vision",
                queue_interval_seconds=1.0,
            ),
            security_model=SimpleNamespace(
                model_name="security",
                queue_interval_seconds=1.0,
            ),
            naga_model=SimpleNamespace(
                model_name="naga",
                queue_interval_seconds=1.0,
            ),
            grok_model=SimpleNamespace(
                model_name="grok",
                queue_interval_seconds=1.0,
            ),
            historian_model=SimpleNamespace(
                model_name="historian",
                queue_interval_seconds=1.0,
            ),
        ),
    )
    ai_client = _FakeAIClient()
    context = HotReloadContext(
        ai_client=cast(Any, ai_client),
        queue_manager=cast(Any, _FakeQueueManager()),
        config_manager=cast(Any, SimpleNamespace()),
        security_service=cast(Any, _FakeSecurityService()),
    )

    apply_config_updates(
        updated,
        {
            "attachment_cache_max_total_size_mb": (0, 512),
            "attachment_cache_max_records": (2000, 300),
            "attachment_cache_max_age_days": (7, 14),
            "attachment_url_reference_max_records": (2000, 150),
            "attachment_url_max_length": (8192, 4096),
        },
        context,
    )

    assert ai_client.attachment_updates == [updated]


@pytest.mark.asyncio
async def test_apply_config_updates_refreshes_pipelines_hot_reload() -> None:
    updated = cast(
        Any,
        SimpleNamespace(
            searxng_url="",
            skills_hot_reload=True,
            skills_hot_reload_interval=3.0,
            skills_hot_reload_debounce=0.75,
        ),
    )
    tool_registry = _FakeReloadRegistry()
    agent_registry = _FakeReloadRegistry()
    anthropic_skill_registry = _FakeReloadRegistry()
    message_handler = _FakeMessageHandler()
    config_manager = _FakeConfigManager()
    ai_client = SimpleNamespace(
        tool_registry=tool_registry,
        agent_registry=agent_registry,
        anthropic_skill_registry=anthropic_skill_registry,
    )
    context = HotReloadContext(
        ai_client=cast(Any, ai_client),
        queue_manager=cast(Any, _FakeQueueManager()),
        config_manager=cast(Any, config_manager),
        security_service=cast(Any, _FakeSecurityService()),
        message_handler=cast(Any, message_handler),
    )

    apply_config_updates(
        updated,
        {"skills_hot_reload_interval": (2.0, 3.0)},
        context,
    )
    await asyncio.sleep(0)

    assert tool_registry.started == [(3.0, 0.75)]
    assert agent_registry.started == [(3.0, 0.75)]
    assert anthropic_skill_registry.started == [(3.0, 0.75)]
    assert message_handler.reload_updates == [(True, 3.0, 0.75)]
    assert config_manager.started == [(3.0, 0.75)]
