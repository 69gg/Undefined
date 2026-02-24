from __future__ import annotations

from types import SimpleNamespace
from typing import Any
import pytest

from Undefined.cognitive.historian import HistorianWorker


def _make_worker(*, rewrite_max_retry: int = 0) -> HistorianWorker:
    return HistorianWorker(
        job_queue=None,
        vector_store=None,
        profile_storage=None,
        ai_client=None,
        config_getter=lambda: SimpleNamespace(rewrite_max_retry=rewrite_max_retry),
    )


def test_collect_entity_id_drift_detects_missing_third_party_id() -> None:
    worker = _make_worker()
    job = {
        "observations": "Null(1708213363)在bot测试群(1017148870)解释了名字误判原因",
        "memo": "",
        "sender_id": "120218451",
        "user_id": "120218451",
        "group_id": "1017148870",
        "message_ids": ["452663169"],
    }
    canonical = "洛泫(120218451)在bot测试群(1017148870)解释了名字误判原因"

    drift = worker._collect_entity_id_drift(job, canonical)

    assert drift == ["1708213363"]


def test_collect_entity_id_drift_ignores_context_ids() -> None:
    worker = _make_worker()
    job = {
        "observations": "洛泫(120218451)在bot测试群(1017148870)提到规则上限80",
        "memo": "",
        "sender_id": "120218451",
        "user_id": "120218451",
        "group_id": "1017148870",
        "message_ids": ["452663169"],
    }
    canonical = "洛泫(120218451)在bot测试群(1017148870)提到规则上限80"

    drift = worker._collect_entity_id_drift(job, canonical)

    assert drift == []


def test_collect_entity_id_drift_passes_when_third_party_id_retained() -> None:
    worker = _make_worker()
    job = {
        "observations": "Null(1708213363)在bot测试群(1017148870)解释了名字误判原因",
        "memo": "",
        "sender_id": "120218451",
        "user_id": "120218451",
        "group_id": "1017148870",
        "message_ids": ["452663169"],
    }
    canonical = "Null(1708213363)在bot测试群(1017148870)解释了名字误判原因"

    drift = worker._collect_entity_id_drift(job, canonical)

    assert drift == []


def test_collect_entity_id_drift_backward_compat_old_keys() -> None:
    """向后兼容：旧 key new_info/action_summary 仍能被 _collect_source_entity_ids 识别。"""
    worker = _make_worker()
    job = {
        "new_info": "Null(1708213363)在bot测试群(1017148870)解释了名字误判原因",
        "action_summary": "",
        "sender_id": "120218451",
        "user_id": "120218451",
        "group_id": "1017148870",
        "message_ids": ["452663169"],
    }
    canonical = "洛泫(120218451)在bot测试群(1017148870)解释了名字误判原因"

    drift = worker._collect_entity_id_drift(job, canonical)

    assert drift == ["1708213363"]


@pytest.mark.asyncio
async def test_rewrite_and_validate_force_skips_regex_gate() -> None:
    rewrite_calls: list[int] = []

    def _config_getter() -> SimpleNamespace:
        return SimpleNamespace(rewrite_max_retry=2)

    class _FakeRewriteWorker(HistorianWorker):
        async def _rewrite(
            self,
            job: dict[str, object],
            *,
            job_id: str = "",
            attempt: int = 1,
            must_keep_entity_ids: list[str] | None = None,
            gate_feedback: str | None = None,
        ) -> str:
            rewrite_calls.append(attempt)
            return "他在这里说之后再处理"

    worker = _FakeRewriteWorker(
        job_queue=None,
        vector_store=None,
        profile_storage=None,
        ai_client=None,
        config_getter=_config_getter,
    )
    canonical, is_absolute = await worker._rewrite_and_validate(
        {"observations": "测试", "memo": "", "force": True},
        "job-force",
    )

    assert canonical == "他在这里说之后再处理"
    assert is_absolute is False
    assert rewrite_calls == [1]


@pytest.mark.asyncio
async def test_rewrite_and_validate_passes_gate_feedback_on_retry() -> None:
    captured_feedback: list[str] = []

    def _config_getter() -> SimpleNamespace:
        return SimpleNamespace(rewrite_max_retry=1)

    class _FakeRewriteWorker(HistorianWorker):
        async def _rewrite(
            self,
            job: dict[str, object],
            *,
            job_id: str = "",
            attempt: int = 1,
            must_keep_entity_ids: list[str] | None = None,
            gate_feedback: str | None = None,
        ) -> str:
            if attempt == 1:
                return "他今天在这里说之后再处理"
            captured_feedback.append(str(gate_feedback or ""))
            return "Null(1708213363)在2026-02-24 10:00于bot测试群(1017148870)表示将于2026-02-24 11:00处理"

    worker = _FakeRewriteWorker(
        job_queue=None,
        vector_store=None,
        profile_storage=None,
        ai_client=None,
        config_getter=_config_getter,
    )
    canonical, is_absolute = await worker._rewrite_and_validate(
        {
            "observations": "Null(1708213363)在bot测试群(1017148870)表示稍后处理",
            "memo": "",
            "sender_id": "120218451",
            "user_id": "120218451",
            "group_id": "1017148870",
            "message_ids": ["452663169"],
            "force": False,
        },
        "job-retry-feedback",
    )

    assert canonical.startswith("Null(1708213363)")
    assert is_absolute is True
    assert captured_feedback
    feedback = captured_feedback[0]
    assert "命中代词" in feedback
    assert "命中相对时间" in feedback
    assert "命中相对地点" in feedback
    assert "当前 force: false" in feedback


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
        config_getter=lambda: SimpleNamespace(rewrite_max_retry=0),
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
