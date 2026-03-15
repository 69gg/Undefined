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

    def update_model_intervals(self, intervals: Any) -> None:
        self.intervals.append(intervals)


def test_apply_config_updates_propagates_to_security_service() -> None:
    updated = cast(
        Any,
        SimpleNamespace(
            searxng_url="",
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
