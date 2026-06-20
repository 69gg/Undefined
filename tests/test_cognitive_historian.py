from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from Undefined.cognitive.chroma_scheduler import CHROMA_PRIORITY_MAINTENANCE
from Undefined.cognitive.historian import HistorianWorker
from Undefined.cognitive.historian.tools import _PROFILE_TOOL


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
            self.priority_calls: list[str] = []
            self.embed_query_calls = 0

        async def embed_query(self, _query: str) -> list[float]:
            self.embed_query_calls += 1
            return [0.56, 0.78]

        async def query_events(
            self, _query: str, **kwargs: Any
        ) -> list[dict[str, Any]]:
            where = kwargs.get("where")
            if isinstance(where, dict):
                self.where_calls.append(where)
            self.priority_calls.append(str(kwargs.get("priority", "")))
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
    assert vector_store.embed_query_calls == 1
    assert {"sender_id": "123456"} in vector_store.where_calls
    assert {"user_id": "123456"} in vector_store.where_calls
    assert vector_store.priority_calls == [
        CHROMA_PRIORITY_MAINTENANCE,
        CHROMA_PRIORITY_MAINTENANCE,
    ]


@pytest.mark.asyncio
async def test_poll_loop_dispatches_without_waiting_previous_job_completion() -> None:
    started: list[str] = []
    finished: list[str] = []
    first_job_gate = asyncio.Event()

    class _FakeQueue:
        def __init__(self) -> None:
            self._items: list[tuple[str, dict[str, Any]] | None] = [
                ("job-1", {"_retry_count": 0}),
                ("job-2", {"_retry_count": 0}),
                None,
                None,
            ]

        async def dequeue(self) -> tuple[str, dict[str, Any]] | None:
            if self._items:
                return self._items.pop(0)
            return None

        async def requeue(self, _job_id: str, _error: str) -> None:
            return None

        async def fail(self, _job_id: str, _error: str) -> None:
            return None

    queue = _FakeQueue()

    class _DispatchWorker(HistorianWorker):
        async def _process_job(self, job_id: str, job: dict[str, Any]) -> None:
            _ = job
            started.append(job_id)
            if job_id == "job-1":
                await first_job_gate.wait()
                finished.append(job_id)
                return

            # 关键断言：第二单启动时，第一单尚未完成。
            assert "job-1" in started
            assert "job-1" not in finished
            finished.append(job_id)
            first_job_gate.set()
            self._stop_event.set()

    worker = _DispatchWorker(
        job_queue=queue,
        vector_store=None,
        profile_storage=None,
        ai_client=None,
        config_getter=lambda: SimpleNamespace(
            poll_interval_seconds=0.01,
            failed_cleanup_interval=0,
            failed_max_age_days=30,
            failed_max_files=500,
            job_max_retries=0,
        ),
    )

    await asyncio.wait_for(worker._poll_loop(), timeout=1.0)

    assert started[:2] == ["job-1", "job-2"]
    assert "job-1" in finished and "job-2" in finished


def test_extract_required_tool_args_preserves_job_context_in_error() -> None:
    worker = _make_worker()

    with pytest.raises(ValueError) as exc_info:
        worker._extract_required_tool_args(
            {},
            expected_tool_name="submit_historian_result",
            stage="historian_rewrite",
            job_id="job-123",
            attempt=2,
            target="user:42",
        )

    message = str(exc_info.value)
    assert "job_id=job-123" in message
    assert "attempt=2" in message
    assert "target=user:42" in message


def test_historian_profile_merge_prompt_profile_only_constraints() -> None:
    merge = Path("res/prompts/historian_profile_merge.md").read_text(encoding="utf-8")
    assert "长期高层画像" in merge
    assert "skip=true" in merge
    assert "具体事件" in merge
    assert "曾/刚/最近" in merge


def test_profile_update_tool_does_not_cap_tags() -> None:
    parameters: Any = _PROFILE_TOOL["function"]["parameters"]  # type: ignore[index]
    tags_schema: Any = parameters["properties"]["tags"]

    assert "maxItems" not in tags_schema
    assert "最多 10 个" not in str(tags_schema)


@pytest.mark.asyncio
async def test_merge_profile_target_preserves_more_than_ten_tags() -> None:
    class _FakeVectorStore:
        async def embed_query(self, _query: str) -> list[float]:
            return [0.1, 0.2]

        async def query_events(
            self, _query: str, **_kwargs: Any
        ) -> list[dict[str, Any]]:
            return []

        async def upsert_profile(
            self, _profile_id: str, _document: str, metadata: dict[str, Any]
        ) -> None:
            upserted_metadata.append(metadata)

    class _FakeProfileStorage:
        async def read_profile(self, _entity_type: str, _entity_id: str) -> str:
            return "---\nname: 测试用户\n---\n- 旧侧写"

        async def write_profile(
            self, _entity_type: str, _entity_id: str, content: str
        ) -> None:
            written_profiles.append(content)

    class _FakeAIClient:
        agent_config = object()

        def __init__(self) -> None:
            self.calls = 0

        async def submit_background_llm_call(self, **_kwargs: Any) -> dict[str, Any]:
            self.calls += 1
            if self.calls == 1:
                return {
                    "choices": [
                        {
                            "message": {
                                "tool_calls": [
                                    {
                                        "id": "read-1",
                                        "function": {
                                            "name": "read_profile",
                                            "arguments": (
                                                '{"entity_type":"user","entity_id":"123456"}'
                                            ),
                                        },
                                    }
                                ]
                            }
                        }
                    ]
                }
            tags = [f"标签{i}" for i in range(12)]
            args = {
                "entity_type": "user",
                "entity_id": "123456",
                "skip": False,
                "name": "测试用户",
                "tags": tags,
                "summary": "- 新侧写",
            }

            return {
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "id": "update-1",
                                    "function": {
                                        "name": "update_profile",
                                        "arguments": json.dumps(
                                            args, ensure_ascii=False
                                        ),
                                    },
                                }
                            ]
                        }
                    }
                ]
            }

    written_profiles: list[str] = []
    upserted_metadata: list[dict[str, Any]] = []
    ai_client = _FakeAIClient()
    worker = HistorianWorker(
        job_queue=None,
        vector_store=_FakeVectorStore(),
        profile_storage=_FakeProfileStorage(),
        ai_client=ai_client,
        config_getter=lambda: SimpleNamespace(),
    )
    job: dict[str, Any] = {
        "observations": ["测试用户长期具有多个身份标签"],
        "request_type": "private",
        "user_id": "123456",
        "group_id": "",
        "sender_id": "123456",
        "sender_name": "测试用户",
        "group_name": "",
        "timestamp_local": "2026-06-07T12:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "request_id": "req-tags",
        "end_seq": 1,
        "message_ids": [],
        "memo": "",
        "source_message": "测试",
        "recent_messages": [],
    }

    result = await worker._merge_profile_target(
        job=job,
        canonical="测试用户(123456)具有多个长期身份标签",
        event_id="job-tags",
        target={
            "entity_type": "user",
            "entity_id": "123456",
            "perspective": "sender",
            "preferred_name": "测试用户",
        },
        target_index=1,
        target_count=1,
    )

    assert result is True
    assert len(written_profiles) == 1
    for index in range(12):
        assert f"- 标签{index}" in written_profiles[0]
