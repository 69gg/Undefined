from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from Undefined.cognitive.historian import HistorianWorker


def _make_worker() -> HistorianWorker:
    return HistorianWorker(
        job_queue=None,
        vector_store=None,
        profile_storage=None,
        ai_client=None,
        config_getter=lambda: SimpleNamespace(),
    )


@pytest.mark.asyncio
async def test_rewrite_and_validate_returns_canonical() -> None:
    class _FakeRewriteWorker(HistorianWorker):
        async def _rewrite(
            self,
            job: dict[str, object],
            *,
            job_id: str = "",
        ) -> str:
            return (
                "Null(1708213363)在2026-02-24于bot测试群(1017148870)解释了名字误判原因"
            )

    worker = _FakeRewriteWorker(
        job_queue=None,
        vector_store=None,
        profile_storage=None,
        ai_client=None,
        config_getter=lambda: SimpleNamespace(),
    )
    canonical = await worker._rewrite_and_validate(
        {"observations": "测试", "memo": ""},
        "job-test",
    )

    assert (
        canonical
        == "Null(1708213363)在2026-02-24于bot测试群(1017148870)解释了名字误判原因"
    )


@pytest.mark.asyncio
async def test_process_job_memo_only_no_observations_skips_vector_write() -> None:
    """仅有 memo 无 observations 时，不应写入向量库。"""
    upserted_events: list[tuple[str, str, dict[str, Any]]] = []
    completed_jobs: list[str] = []

    class _FakeVectorStore:
        async def upsert_event(
            self, event_id: str, text: str, metadata: dict[str, Any]
        ) -> None:
            upserted_events.append((event_id, text, metadata))

    class _FakeJobQueue:
        async def complete(self, job_id: str) -> None:
            completed_jobs.append(job_id)

    worker = HistorianWorker(
        job_queue=_FakeJobQueue(),
        vector_store=_FakeVectorStore(),
        profile_storage=None,
        ai_client=None,
        config_getter=lambda: SimpleNamespace(),
    )

    job: dict[str, Any] = {
        "request_id": "req-memo-only",
        "end_seq": 0,
        "user_id": "120218451",
        "group_id": "1017148870",
        "sender_id": "120218451",
        "sender_name": "洛泫",
        "group_name": "bot测试群",
        "bot_name": "Undefined",
        "request_type": "group",
        "timestamp_utc": "2026-02-24T00:00:00+00:00",
        "timestamp_local": "2026-02-24T08:00:00+08:00",
        "timestamp_epoch": 1771977600,
        "timezone": "Asia/Shanghai",
        "location_abs": "bot测试群",
        "message_ids": [],
        "memo": "已回复用户关于规则的问题",
        "observations": [],
        "has_observations": False,
        "perspective": "",
        "profile_targets": [],
        "schema_version": "final_v1",
        "source_message": "",
        "recent_messages": [],
        "force": False,
    }

    await worker._process_job("job-memo-only", job)

    # memo-only 不应触发向量写入
    assert len(upserted_events) == 0
    # 但任务应正常完成
    assert "job-memo-only" in completed_jobs


@pytest.mark.asyncio
async def test_merge_profile_target_user_queries_history_with_sender_or_user_id() -> (
    None
):
    class _FakeVectorStore:
        def __init__(self) -> None:
            self.where_calls: list[dict[str, Any]] = []

        async def query_events(
            self, _query: str, **kwargs: Any
        ) -> list[dict[str, Any]]:
            where = kwargs.get("where")
            if isinstance(where, dict):
                self.where_calls.append(where)
            return []

    class _FakeAIClient:
        agent_config = object()

        async def submit_background_llm_call(self, **kwargs: Any) -> dict[str, Any]:
            _ = kwargs
            return {"choices": []}

    vector_store = _FakeVectorStore()
    worker = HistorianWorker(
        job_queue=None,
        vector_store=vector_store,
        profile_storage=SimpleNamespace(read_profile=None),
        ai_client=_FakeAIClient(),
        config_getter=lambda: SimpleNamespace(),
    )
    job: dict[str, Any] = {
        "observations": ["用户提到会继续用 Python"],
        "request_type": "private",
        "user_id": "123456",
        "group_id": "",
        "sender_id": "123456",
        "sender_name": "测试用户",
        "group_name": "",
        "timestamp_local": "2026-03-01T12:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "request_id": "req-1",
        "end_seq": 1,
        "message_ids": [],
        "memo": "",
        "source_message": "我还是喜欢 Python",
        "recent_messages": [],
    }

    result = await worker._merge_profile_target(
        job=job,
        canonical="测试用户(123456)表示长期偏好 Python",
        event_id="job-1",
        target={
            "entity_type": "user",
            "entity_id": "123456",
            "perspective": "sender",
            "preferred_name": "测试用户",
        },
        target_index=1,
        target_count=1,
    )

    assert result is False
    assert {"sender_id": "123456"} in vector_store.where_calls
    assert {"user_id": "123456"} in vector_store.where_calls
