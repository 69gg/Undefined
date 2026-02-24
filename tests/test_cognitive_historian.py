from __future__ import annotations

from types import SimpleNamespace
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


def test_collect_entity_id_drift_ignores_context_ids() -> None:
    worker = _make_worker()
    job = {
        "new_info": "洛泫(120218451)在bot测试群(1017148870)提到规则上限80",
        "action_summary": "",
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
        "new_info": "Null(1708213363)在bot测试群(1017148870)解释了名字误判原因",
        "action_summary": "",
        "sender_id": "120218451",
        "user_id": "120218451",
        "group_id": "1017148870",
        "message_ids": ["452663169"],
    }
    canonical = "Null(1708213363)在bot测试群(1017148870)解释了名字误判原因"

    drift = worker._collect_entity_id_drift(job, canonical)

    assert drift == []


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
        {"new_info": "测试", "action_summary": "", "force": True},
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
            "new_info": "Null(1708213363)在bot测试群(1017148870)表示稍后处理",
            "action_summary": "",
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
