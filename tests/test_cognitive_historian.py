from __future__ import annotations

from types import SimpleNamespace

from Undefined.cognitive.historian import HistorianWorker


def _make_worker() -> HistorianWorker:
    return HistorianWorker(
        job_queue=None,
        vector_store=None,
        profile_storage=None,
        ai_client=None,
        config_getter=lambda: SimpleNamespace(rewrite_max_retry=0),
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
