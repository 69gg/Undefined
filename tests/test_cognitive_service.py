from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from Undefined.cognitive.service import CognitiveService


class _FakeJobQueue:
    def __init__(self) -> None:
        self.last_job: dict[str, Any] | None = None

    async def enqueue(self, job: dict[str, Any]) -> str:
        self.last_job = job
        return "job-test"


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
        action_summary="",
        new_info=["Null(1708213363)说发现了竞态问题"],
        context=context,
    )

    assert job_id == "job-test"
    assert queue.last_job is not None
    assert queue.last_job.get("source_message") == "Null(1708213363)说发现了竞态问题"
    assert queue.last_job.get("recent_messages") == [
        "[2026-02-23 19:02:11] 洛泫(120218451): Null 说这个是竞态问题"
    ]
