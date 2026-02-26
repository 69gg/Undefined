from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest

from Undefined.cognitive.service import CognitiveService


class _FakeJobQueue:
    def __init__(self) -> None:
        self.last_job: dict[str, Any] | None = None

    async def enqueue(self, job: dict[str, Any]) -> str:
        self.last_job = job
        return "job-test"


class _FakeVectorStore:
    def __init__(self) -> None:
        self.last_event_kwargs: dict[str, Any] | None = None
        self.last_profile_kwargs: dict[str, Any] | None = None

    async def query_events(
        self,
        _query: str,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        self.last_event_kwargs = dict(kwargs)
        return []

    async def query_profiles(
        self,
        _query: str,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        self.last_profile_kwargs = dict(kwargs)
        return []


class _FakeProfileStorage:
    async def read_profile(
        self,
        _entity_type: str,
        _entity_id: str,
    ) -> str | None:
        return None


class _FakeRetrievalRuntime:
    def __init__(self, reranker: object | None) -> None:
        self._reranker = reranker
        self.ensure_reranker_calls = 0

    def ensure_reranker(self) -> object | None:
        self.ensure_reranker_calls += 1
        return self._reranker


@pytest.mark.asyncio
async def test_enqueue_job_keeps_historian_reference_fields() -> None:
    queue = _FakeJobQueue()
    service = CognitiveService(
        config_getter=lambda: SimpleNamespace(enabled=True, bot_name="Undefined"),
        vector_store=None,
        job_queue=queue,
        profile_storage=None,
        reranker=None,
    )

    context = {
        "request_id": "req-1",
        "request_type": "group",
        "group_id": "1082837821",
        "user_id": "120218451",
        "sender_id": "120218451",
        "sender_name": "洛泫",
        "group_name": "bot测试群",
        "historian_source_message": "Null(1708213363)说发现了竞态问题",
        "historian_recent_messages": [
            "[2026-02-23 19:02:11] 洛泫(120218451): Null 说这个是竞态问题"
        ],
    }

    job_id = await service.enqueue_job(
        memo="",
        observations=["Null(1708213363)说发现了竞态问题"],
        context=context,
    )

    assert job_id == "job-test"
    assert queue.last_job is not None
    assert queue.last_job.get("source_message") == "Null(1708213363)说发现了竞态问题"
    assert queue.last_job.get("recent_messages") == [
        "[2026-02-23 19:02:11] 洛泫(120218451): Null 说这个是竞态问题"
    ]
    assert queue.last_job.get("force") is False
    # 验证 job 字典中使用新 key
    assert "memo" in queue.last_job
    assert "observations" in queue.last_job
    assert "has_observations" in queue.last_job


@pytest.mark.asyncio
async def test_enqueue_job_keeps_force_flag() -> None:
    queue = _FakeJobQueue()
    service = CognitiveService(
        config_getter=lambda: SimpleNamespace(enabled=True, bot_name="Undefined"),
        vector_store=None,
        job_queue=queue,
        profile_storage=None,
        reranker=None,
    )
    context: dict[str, Any] = {"request_id": "req-force-gate"}

    await service.enqueue_job(
        memo="测试",
        observations=[],
        context=context,
        force=True,
    )

    assert queue.last_job is not None
    assert queue.last_job.get("force") is True


@pytest.mark.asyncio
async def test_search_events_uses_reranker_when_cognitive_rerank_enabled() -> None:
    vector_store = _FakeVectorStore()
    reranker = object()
    service = CognitiveService(
        config_getter=lambda: SimpleNamespace(
            enabled=True,
            enable_rerank=True,
            tool_default_top_k=12,
            rerank_candidate_multiplier=3,
            time_decay_enabled=True,
            time_decay_half_life_days_tool=60.0,
            time_decay_boost=0.2,
            time_decay_min_similarity=0.35,
        ),
        vector_store=vector_store,
        job_queue=_FakeJobQueue(),
        profile_storage=_FakeProfileStorage(),
        reranker=reranker,
    )

    await service.search_events("测试")

    assert vector_store.last_event_kwargs is not None
    assert vector_store.last_event_kwargs.get("reranker") is reranker


@pytest.mark.asyncio
async def test_search_events_skips_reranker_when_cognitive_rerank_disabled() -> None:
    vector_store = _FakeVectorStore()
    service = CognitiveService(
        config_getter=lambda: SimpleNamespace(
            enabled=True,
            enable_rerank=False,
            tool_default_top_k=12,
            rerank_candidate_multiplier=3,
            time_decay_enabled=True,
            time_decay_half_life_days_tool=60.0,
            time_decay_boost=0.2,
            time_decay_min_similarity=0.35,
        ),
        vector_store=vector_store,
        job_queue=_FakeJobQueue(),
        profile_storage=_FakeProfileStorage(),
        reranker=object(),
    )

    await service.search_events("测试")

    assert vector_store.last_event_kwargs is not None
    assert vector_store.last_event_kwargs.get("reranker") is None


@pytest.mark.asyncio
async def test_search_profiles_skips_reranker_when_cognitive_rerank_disabled() -> None:
    vector_store = _FakeVectorStore()
    service = CognitiveService(
        config_getter=lambda: SimpleNamespace(
            enabled=True,
            enable_rerank=False,
            rerank_candidate_multiplier=3,
        ),
        vector_store=vector_store,
        job_queue=_FakeJobQueue(),
        profile_storage=_FakeProfileStorage(),
        reranker=object(),
    )

    await service.search_profiles("测试")

    assert vector_store.last_profile_kwargs is not None
    assert vector_store.last_profile_kwargs.get("reranker") is None


@pytest.mark.asyncio
async def test_search_profiles_handles_none_top_k_and_empty_entity_type() -> None:
    vector_store = _FakeVectorStore()
    service = CognitiveService(
        config_getter=lambda: SimpleNamespace(
            enabled=True,
            enable_rerank=True,
            profile_top_k=8,
            rerank_candidate_multiplier=3,
        ),
        vector_store=vector_store,
        job_queue=_FakeJobQueue(),
        profile_storage=_FakeProfileStorage(),
        reranker=object(),
    )

    await service.search_profiles("测试", top_k=None, entity_type=None)

    assert vector_store.last_profile_kwargs is not None
    assert vector_store.last_profile_kwargs.get("top_k") == 8
    assert vector_store.last_profile_kwargs.get("where") is None


@pytest.mark.asyncio
async def test_search_events_uses_runtime_reranker_when_enabled() -> None:
    vector_store = _FakeVectorStore()
    runtime = _FakeRetrievalRuntime(reranker=object())
    service = CognitiveService(
        config_getter=lambda: SimpleNamespace(
            enabled=True,
            enable_rerank=True,
            tool_default_top_k=12,
            rerank_candidate_multiplier=3,
            time_decay_enabled=True,
            time_decay_half_life_days_tool=60.0,
            time_decay_boost=0.2,
            time_decay_min_similarity=0.35,
        ),
        vector_store=vector_store,
        job_queue=_FakeJobQueue(),
        profile_storage=_FakeProfileStorage(),
        retrieval_runtime=cast(Any, runtime),
    )

    await service.search_events("测试")

    assert runtime.ensure_reranker_calls == 1
    assert vector_store.last_event_kwargs is not None
    assert vector_store.last_event_kwargs.get("reranker") is runtime._reranker


@pytest.mark.asyncio
async def test_search_events_does_not_touch_runtime_reranker_when_disabled() -> None:
    vector_store = _FakeVectorStore()
    runtime = _FakeRetrievalRuntime(reranker=object())
    service = CognitiveService(
        config_getter=lambda: SimpleNamespace(
            enabled=True,
            enable_rerank=False,
            tool_default_top_k=12,
            rerank_candidate_multiplier=3,
            time_decay_enabled=True,
            time_decay_half_life_days_tool=60.0,
            time_decay_boost=0.2,
            time_decay_min_similarity=0.35,
        ),
        vector_store=vector_store,
        job_queue=_FakeJobQueue(),
        profile_storage=_FakeProfileStorage(),
        retrieval_runtime=cast(Any, runtime),
    )

    await service.search_events("测试")

    assert runtime.ensure_reranker_calls == 0
    assert vector_store.last_event_kwargs is not None
    assert vector_store.last_event_kwargs.get("reranker") is None
