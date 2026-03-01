from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Callable, cast

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
        self.event_calls: list[dict[str, Any]] = []
        self.event_resolver: Callable[[dict[str, Any]], list[dict[str, Any]]] | None = (
            None
        )

    async def query_events(
        self,
        _query: str,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        self.last_event_kwargs = dict(kwargs)
        self.event_calls.append(dict(kwargs))
        if self.event_resolver is not None:
            return self.event_resolver(kwargs)
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


@pytest.mark.asyncio
async def test_build_context_group_mode_uses_group_scope_with_boost() -> None:
    vector_store = _FakeVectorStore()
    vector_store.event_resolver = lambda kwargs: (
        [
            {
                "document": "当前群事件",
                "metadata": {
                    "timestamp_local": "2026-02-24 10:00:00",
                    "group_id": "1001",
                    "request_type": "group",
                },
                "distance": 0.38,
            },
            {
                "document": "跨群事件",
                "metadata": {
                    "timestamp_local": "2026-02-24 11:00:00",
                    "group_id": "2002",
                    "request_type": "group",
                },
                "distance": 0.35,
            },
        ]
        if kwargs.get("where") == {"request_type": "group"}
        else []
    )
    service = CognitiveService(
        config_getter=lambda: SimpleNamespace(
            enabled=True,
            enable_rerank=False,
            auto_top_k=2,
            auto_scope_candidate_multiplier=2,
            auto_current_group_boost=1.15,
            rerank_candidate_multiplier=3,
            time_decay_enabled=True,
            time_decay_half_life_days_auto=14.0,
            time_decay_boost=0.2,
            time_decay_min_similarity=0.35,
        ),
        vector_store=vector_store,
        job_queue=_FakeJobQueue(),
        profile_storage=_FakeProfileStorage(),
        reranker=None,
    )

    context = await service.build_context(
        query="之前有谁提到连接超时",
        group_id="1001",
        user_id="3001",
        sender_id="3001",
        request_type="group",
    )

    assert len(vector_store.event_calls) == 1
    assert vector_store.event_calls[0].get("where") == {"request_type": "group"}
    assert vector_store.event_calls[0].get("top_k") == 4
    assert "当前群事件" in context
    assert "跨群事件" in context
    assert context.index("当前群事件") < context.index("跨群事件")


@pytest.mark.asyncio
async def test_build_context_private_mode_queries_groups_and_current_private() -> None:
    vector_store = _FakeVectorStore()

    def _resolve_events(kwargs: dict[str, Any]) -> list[dict[str, Any]]:
        where = kwargs.get("where")
        if where == {"request_type": "group"}:
            return [
                {
                    "document": "群聊公共经验",
                    "metadata": {
                        "timestamp_local": "2026-02-24 11:00:00",
                        "group_id": "9001",
                        "request_type": "group",
                    },
                    "distance": 0.28,
                }
            ]
        if isinstance(where, dict) and "$and" in where:
            return [
                {
                    "document": "当前私聊上下文",
                    "metadata": {
                        "timestamp_local": "2026-02-24 12:00:00",
                        "group_id": "",
                        "request_type": "private",
                        "user_id": "u1",
                        "sender_id": "u2",
                    },
                    "distance": 0.40,
                }
            ]
        return []

    vector_store.event_resolver = _resolve_events
    service = CognitiveService(
        config_getter=lambda: SimpleNamespace(
            enabled=True,
            enable_rerank=False,
            auto_top_k=2,
            auto_scope_candidate_multiplier=2,
            auto_current_private_boost=1.25,
            rerank_candidate_multiplier=3,
            time_decay_enabled=True,
            time_decay_half_life_days_auto=14.0,
            time_decay_boost=0.2,
            time_decay_min_similarity=0.35,
        ),
        vector_store=vector_store,
        job_queue=_FakeJobQueue(),
        profile_storage=_FakeProfileStorage(),
        reranker=None,
    )

    context = await service.build_context(
        query="我这个报错之前怎么处理过",
        user_id="u1",
        sender_id="u2",
        request_type="private",
    )

    assert len(vector_store.event_calls) == 2
    where_clauses = [call.get("where") for call in vector_store.event_calls]
    assert {"request_type": "group"} in where_clauses
    assert any(
        isinstance(where, dict)
        and isinstance(where.get("$and"), list)
        and {"request_type": "private"} in where.get("$and", [])
        for where in where_clauses
    )
    assert "当前私聊上下文" in context
    assert "群聊公共经验" in context
    assert context.index("当前私聊上下文") < context.index("群聊公共经验")


def test_merge_weighted_events_preserves_scope_rank_order() -> None:
    # scoped_events 已经是 query_events 的最终排序（含 time_decay/mmr/rerank），
    # merge 过程不应再按 base_score 重新洗牌。
    scoped_events = [
        {
            "document": "更新但稍弱相似度",
            "metadata": {"timestamp_local": "2026-02-25 12:00:00"},
            "distance": 0.40,
        },
        {
            "document": "更老但更高相似度",
            "metadata": {"timestamp_local": "2026-02-20 12:00:00"},
            "distance": 0.20,
        },
    ]

    merged = CognitiveService._merge_weighted_events(
        [(scoped_events, 1.0)],
        top_k=2,
    )

    assert [item["document"] for item in merged] == [
        "更新但稍弱相似度",
        "更老但更高相似度",
    ]
