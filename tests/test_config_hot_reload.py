from __future__ import annotations

import asyncio
from pathlib import Path
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
        self.automation_updates: list[int] = []

    async def apply_skills_hot_reload_config(
        self,
        *,
        enabled: bool,
        interval: float,
        debounce: float,
    ) -> None:
        self.reload_updates.append((enabled, interval, debounce))

    async def apply_automations_hot_reload_config(
        self,
        *,
        max_concurrent: int,
    ) -> None:
        self.automation_updates.append(max_concurrent)


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
        {"security_model.model_name": ("old", "new")},
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


def test_apply_config_updates_hot_reloads_prompt_file_includes() -> None:
    updated = cast(
        Any,
        SimpleNamespace(
            prompt_file_includes={"p0": "config/prompts/creator.local.xml"},
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
            "prompt_file_includes": (
                {},
                {"p0": "config/prompts/creator.local.xml"},
            )
        },
        context,
    )

    assert ai_client.runtime_updates == [updated]


def test_apply_config_updates_hot_reloads_lxmusic2api_config() -> None:
    updated = cast(
        Any,
        SimpleNamespace(
            lxmusic2api_base_url="https://music.example.test",
            lxmusic2api_api_key="music-key",
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
            "lxmusic2api_base_url": (
                "http://127.0.0.1:3000",
                "https://music.example.test",
            ),
            "lxmusic2api_api_key": ("", "music-key"),
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


@pytest.mark.asyncio
async def test_apply_config_updates_refreshes_automation_concurrency() -> None:
    updated = cast(
        Any,
        SimpleNamespace(automations=SimpleNamespace(max_concurrent=7)),
    )
    message_handler = _FakeMessageHandler()
    context = HotReloadContext(
        ai_client=cast(Any, _FakeAIClient()),
        queue_manager=cast(Any, _FakeQueueManager()),
        config_manager=cast(Any, _FakeConfigManager()),
        security_service=cast(Any, _FakeSecurityService()),
        message_handler=cast(Any, message_handler),
    )

    apply_config_updates(
        updated,
        {"automations": (SimpleNamespace(max_concurrent=1), updated.automations)},
        context,
    )
    await asyncio.sleep(0)

    assert message_handler.automation_updates == [7]


def test_apply_config_updates_isolates_failed_step(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """单个步骤失败不应中断其余步骤，且必须以 error 日志暴露。"""
    updated = cast(
        Any,
        SimpleNamespace(
            ai_request_max_retries=7,
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
                model_name="vision", queue_interval_seconds=1.0
            ),
            security_model=SimpleNamespace(
                model_name="security", queue_interval_seconds=1.0
            ),
            naga_model=SimpleNamespace(model_name="naga", queue_interval_seconds=1.0),
            grok_model=SimpleNamespace(model_name="grok", queue_interval_seconds=1.0),
            historian_model=SimpleNamespace(
                model_name="historian", queue_interval_seconds=1.0
            ),
        ),
    )

    class _BrokenSecurity:
        def apply_config(self, config: Any) -> None:
            raise RuntimeError("security boom")

    queue_manager = _FakeQueueManager()
    context = HotReloadContext(
        ai_client=cast(Any, SimpleNamespace()),
        queue_manager=cast(Any, queue_manager),
        config_manager=cast(Any, SimpleNamespace()),
        security_service=cast(Any, _BrokenSecurity()),
    )

    with caplog.at_level("ERROR"):
        apply_config_updates(
            updated,
            {"security_model.model_name": ("old", "new")},
            context,
        )

    # 后续步骤仍然执行
    assert len(queue_manager.intervals) == 1
    assert "security" in caplog.text
    assert "热更新步骤失败" in caplog.text
    assert "热更新未完全生效" in caplog.text


@pytest.mark.asyncio
async def test_spawned_hot_reload_task_logs_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from Undefined.config.hot_reload import _spawn_hot_reload_task

    async def _boom() -> None:
        raise RuntimeError("background boom")

    with caplog.at_level("ERROR"):
        _spawn_hot_reload_task(_boom(), "unit-test-task")
        for _ in range(5):
            await asyncio.sleep(0)

    assert "热更新后台任务失败" in caplog.text
    assert "unit-test-task" in caplog.text


def test_config_manager_notify_survives_failing_callback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from Undefined.config.manager import ConfigManager

    manager = ConfigManager()
    seen: list[dict[str, Any]] = []

    def _boom(config: Any, changes: dict[str, Any]) -> None:
        raise RuntimeError("callback boom")

    def _record(config: Any, changes: dict[str, Any]) -> None:
        seen.append(changes)

    manager._config = cast(Any, SimpleNamespace())
    manager.subscribe(_boom)
    manager.subscribe(_record)

    with caplog.at_level("ERROR"):
        manager._notify({"core.bot_qq": (1, 2)})

    assert seen == [{"core.bot_qq": (1, 2)}]
    assert "热更新回调执行失败" in caplog.text
    assert "回调未完成" in caplog.text


def test_weixin_config_updates_in_place_for_hot_reload(tmp_path: Path) -> None:
    """WeixinService 持有 config.weixin 对象，热更新必须原地改字段而非换身份。"""
    from dataclasses import replace as dc_replace

    from Undefined.config.loader import Config

    def _load(text: str, name: str) -> Config:
        path = tmp_path / name
        path.write_text(text, encoding="utf-8")
        return Config.load(path, strict=False)

    base = _load("[weixin]\nenabled = false\n", "base.toml")
    updated = _load("[weixin]\nenabled = true\n", "updated.toml")
    assert base.weixin.enabled is False

    held = base.weixin  # 模拟组件构造时持有的引用
    changes = base.update_from(updated)

    assert any(key.startswith("weixin.") for key in changes)
    assert held is base.weixin  # 身份未变，组件不会读到旧对象
    assert held.enabled is True
    assert dc_replace(updated.weixin, enabled=False) != updated.weixin


def test_security_step_skipped_when_unrelated_keys_change() -> None:
    """安全服务持有同一个 Config 实例，无关变更不需要重建注入回复 Agent。"""
    updated = cast(
        Any,
        SimpleNamespace(
            searxng_url="",
            ai_request_max_retries=7,
            agent_intro_autogen_enabled=False,
            agent_intro_autogen_queue_interval=0.0,
            message_batcher=SimpleNamespace(),
            automations=SimpleNamespace(),
            skills_hot_reload=False,
            skills_hot_reload_interval=1.0,
            skills_hot_reload_debounce=1.0,
        ),
    )
    security_service = _FakeSecurityService()
    context = HotReloadContext(
        ai_client=cast(Any, SimpleNamespace()),
        queue_manager=cast(Any, _FakeQueueManager()),
        config_manager=cast(Any, SimpleNamespace()),
        security_service=cast(Any, security_service),
    )

    apply_config_updates(updated, {"searxng_url": ("old", "new")}, context)

    assert security_service.applied == []
