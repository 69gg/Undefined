from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

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
