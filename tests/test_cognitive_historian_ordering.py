from __future__ import annotations

import asyncio
import json
import re
from collections import Counter
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from Undefined.cognitive.historian import HistorianWorker
from Undefined.cognitive.historian.scheduling import (
    EntityKey,
    HistorianProgress,
    select_ready_phase,
)
from Undefined.cognitive.job_queue import JobQueue, QueuedJob
from Undefined.cognitive.profile_storage import ProfileStorage
from Undefined.cognitive.service import CognitiveService
from Undefined.utils.io import write_json


def make_job(label: str, *keys: EntityKey) -> dict[str, Any]:
    return {
        "request_id": label,
        "observations": [label],
        "has_observations": True,
        "profile_targets": [
            {"entity_type": kind, "entity_id": entity_id} for kind, entity_id in keys
        ],
    }


def tool_response(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        "choices": [
            {
                "message": {
                    "tool_calls": [
                        {
                            "id": "call",
                            "function": {
                                "name": name,
                                "arguments": json.dumps(arguments),
                            },
                        }
                    ]
                }
            }
        ]
    }


class ControlledAI:
    agent_config = object()

    def __init__(self) -> None:
        self.started: dict[tuple[str, EntityKey], asyncio.Event] = {}
        self.gates: dict[tuple[str, EntityKey], asyncio.Event] = {}
        self.calls: list[tuple[str, EntityKey, str]] = []
        self.failures: Counter[tuple[str, EntityKey]] = Counter()
        self.skips: set[str] = set()
        self.wrong_target = False

    def event(self, label: str, key: EntityKey) -> asyncio.Event:
        return self.started.setdefault((label, key), asyncio.Event())

    async def submit_background_llm_call(self, **kwargs: Any) -> dict[str, Any]:
        prompt = str(kwargs["messages"][0]["content"])

        def field(name: str) -> str:
            match = re.search(rf"^- {name}: (.+)$", prompt, re.MULTILINE)
            assert match is not None
            return match.group(1)

        label = field("request_id")
        key = (field("entity_type"), field("entity_id"))
        snapshot = prompt.split("<current_profile>\n", 1)[1].split(
            "\n</current_profile>", 1
        )[0]
        self.calls.append((label, key, snapshot))
        self.event(label, key).set()
        gate = self.gates.get((label, key))
        if gate is not None:
            await gate.wait()
        if self.failures[(label, key)]:
            self.failures[(label, key)] -= 1
            raise RuntimeError("model unavailable")
        return tool_response(
            "update_profile",
            {
                "entity_type": key[0],
                "entity_id": "999999" if self.wrong_target else key[1],
                "skip": label in self.skips,
                "skip_reason": "no change",
                "name": "name",
                "tags": [],
                "summary": f"- profile {label}",
                "evaluation": "evaluation",
                "roast": "roast",
            },
        )


class ControlledVectors:
    def __init__(self) -> None:
        self.events: dict[str, str] = {}
        self.profiles: dict[str, str] = {}
        self.profile_failures = 0
        self.event_failures = 0
        self.profile_gate: asyncio.Event | None = None
        self.profile_started = asyncio.Event()

    async def query_events(self, query: str, **kwargs: Any) -> list[dict[str, Any]]:
        return []

    async def upsert_event(
        self, event_id: str, text: str, metadata: dict[str, Any]
    ) -> None:
        if self.event_failures:
            self.event_failures -= 1
            raise RuntimeError("event vector unavailable")
        self.events[event_id] = text

    async def upsert_profile(
        self, profile_id: str, text: str, metadata: dict[str, Any]
    ) -> None:
        self.profile_started.set()
        if self.profile_gate is not None:
            await self.profile_gate.wait()
        if self.profile_failures:
            self.profile_failures -= 1
            raise RuntimeError("profile vector unavailable")
        self.profiles[profile_id] = text


class ControlledWorker(HistorianWorker):
    def __init__(
        self,
        queue: JobQueue,
        storage: ProfileStorage,
        ai: ControlledAI,
        vectors: ControlledVectors,
        *,
        concurrency: int = 2,
        retries: int = 2,
    ) -> None:
        self.config = SimpleNamespace(
            poll_interval_seconds=0.01,
            stale_job_timeout_seconds=300,
            job_max_retries=retries,
            failed_cleanup_interval=0,
            failed_max_age_days=30,
            failed_max_files=500,
        )
        super().__init__(
            queue,
            vectors,
            storage,
            ai,
            lambda: self.config,
            max_concurrency=concurrency,
        )
        self.rewrite_gates: dict[str, asyncio.Event] = {}
        self.rewrites: Counter[str] = Counter()
        self.rewrite_started: dict[str, asyncio.Event] = {}

    async def _rewrite(self, job: dict[str, Any], *, job_id: str = "") -> str:
        label = str(job["request_id"])
        self.rewrites[label] += 1
        self.rewrite_started.setdefault(label, asyncio.Event()).set()
        gate = self.rewrite_gates.get(label)
        if gate is not None:
            await gate.wait()
        return f"event {label}"


@dataclass
class Harness:
    queue: JobQueue
    storage: ProfileStorage
    ai: ControlledAI
    vectors: ControlledVectors
    worker: ControlledWorker


def harness(tmp_path: Path, *, concurrency: int = 2, retries: int = 2) -> Harness:
    queue = JobQueue(tmp_path / "queue")
    storage = ProfileStorage(tmp_path / "profiles")
    ai = ControlledAI()
    vectors = ControlledVectors()
    worker = ControlledWorker(
        queue, storage, ai, vectors, concurrency=concurrency, retries=retries
    )
    return Harness(queue, storage, ai, vectors, worker)


@asynccontextmanager
async def running(h: Harness) -> AsyncIterator[None]:
    await h.worker.start()
    try:
        yield
    finally:
        for gate in [*h.ai.gates.values(), *h.worker.rewrite_gates.values()]:
            gate.set()
        if h.vectors.profile_gate is not None:
            h.vectors.profile_gate.set()
        await asyncio.wait_for(h.worker.stop(), 5)


async def until(predicate: Callable[[], bool]) -> None:
    async with asyncio.timeout(5):
        while not predicate():
            await asyncio.sleep(0.01)


async def drained(h: Harness) -> None:
    await until(
        lambda: (
            h.queue.snapshot()["pending"] == 0
            and h.queue.snapshot()["processing"] == 0
            and not h.worker._inflight_tasks
        )
    )


@pytest.mark.asyncio
async def test_rewrite_can_overtake_but_profile_reads_preceding_commit(
    tmp_path: Path,
) -> None:
    h = harness(tmp_path)
    key = ("user", "1")
    await h.storage.write_profile(*key, "P0 {literal}")
    await h.queue.enqueue(make_job("A1", key))
    later = await h.queue.enqueue(make_job("A2", key))
    gate = h.worker.rewrite_gates["A1"] = asyncio.Event()
    async with running(h):
        await until(lambda: later in h.vectors.events)
        assert not h.ai.calls  # A2 不能提前构造合并上下文或调用模型。
        gate.set()
        await drained(h)
    assert [(label, key) for label, key, _ in h.ai.calls] == [("A1", key), ("A2", key)]
    assert h.ai.calls[0][2] == "P0 {literal}"
    assert "profile A1" in h.ai.calls[1][2]
    assert "profile A2" in str(await h.storage.read_profile(*key))
    assert "profile A2" in h.vectors.profiles["user:1"]


@pytest.mark.asyncio
async def test_waiting_profiles_do_not_occupy_slots_and_other_ids_merge_concurrently(
    tmp_path: Path,
) -> None:
    h = harness(tmp_path)
    a, b = ("user", "1"), ("user", "2")
    a_gate = h.ai.gates[("A1", a)] = asyncio.Event()
    b_gate = h.ai.gates[("B1", b)] = asyncio.Event()
    for index in range(1, 12):
        await h.queue.enqueue(make_job(f"A{index}", a))
    await h.queue.enqueue(make_job("B1", b))
    async with running(h):
        await asyncio.wait_for(h.ai.event("A1", a).wait(), 5)
        await asyncio.wait_for(h.ai.event("B1", b).wait(), 5)
        assert not a_gate.is_set() and not b_gate.is_set()
        assert len(h.worker._inflight_tasks) == 2
        assert [label for label, key, _ in h.ai.calls if key == a] == ["A1"]
        a_gate.set()
        b_gate.set()
        await drained(h)
    assert [label for label, key, _ in h.ai.calls if key == a] == [
        f"A{i}" for i in range(1, 12)
    ]


@pytest.mark.asyncio
async def test_multi_target_can_merge_free_group_while_same_user_waits(
    tmp_path: Path,
) -> None:
    h = harness(tmp_path, concurrency=3)
    user, group1, group2 = ("user", "1"), ("group", "10"), ("group", "20")
    gate = h.ai.gates[("A", user)] = asyncio.Event()
    await h.queue.enqueue(make_job("A", user, group1))
    # 有意让 user 排在 group 前面，验证不受同一任务内列表位置阻塞。
    await h.queue.enqueue(make_job("B", user, group2))
    await h.queue.enqueue(make_job("C", group2, ("user", "20")))
    async with running(h):
        await asyncio.wait_for(h.ai.event("C", group2).wait(), 5)
        assert not h.ai.event("B", user).is_set()
        assert h.ai.event("B", group2).is_set()
        gate.set()
        await drained(h)
    b_snapshot = next(
        snapshot for label, key, snapshot in h.ai.calls if (label, key) == ("B", user)
    )
    assert "profile A" in b_snapshot


@pytest.mark.asyncio
async def test_qq_group_and_ilink_share_logical_user_order(tmp_path: Path) -> None:
    h = harness(tmp_path)
    service = CognitiveService(
        lambda: SimpleNamespace(enabled=True, bot_name="bot"),
        h.vectors,
        h.queue,
        h.storage,
    )
    for label, channel, group in [
        ("QQ", "qq", "10"),
        ("WX", "wechat", ""),
        ("PM", "qq", ""),
    ]:
        await service.enqueue_job(
            "",
            [label],
            {
                "request_id": label,
                "sender_id": "123",
                "user_id": "123",
                "group_id": group,
                "request_type": "group" if group else "private",
                "channel": channel,
                "address": f"{channel}:123",
                "account_alias": "ignored",
            },
        )
    gate = h.ai.gates[("QQ", ("user", "123"))] = asyncio.Event()
    async with running(h):
        await asyncio.wait_for(h.ai.event("QQ", ("user", "123")).wait(), 5)
        assert not h.ai.event("WX", ("user", "123")).is_set()
        gate.set()
        await drained(h)
    calls = [
        (label, snapshot)
        for label, key, snapshot in h.ai.calls
        if key == ("user", "123")
    ]
    assert [label for label, _ in calls] == ["QQ", "WX", "PM"]
    assert "profile QQ" in calls[1][1]
    assert "profile WX" in calls[2][1]


@pytest.mark.asyncio
async def test_retries_keep_entity_head_and_do_not_repeat_completed_target(
    tmp_path: Path,
) -> None:
    h = harness(tmp_path)
    group, user = ("group", "1"), ("user", "1")
    h.ai.failures[("A", user)] = 1
    await h.queue.enqueue(make_job("A", group, user))
    await h.queue.enqueue(make_job("B", user))
    async with running(h):
        await drained(h)
    assert [(label, key) for label, key, _ in h.ai.calls] == [
        ("A", group),
        ("A", user),
        ("A", user),
        ("B", user),
    ]
    assert h.worker.rewrites == {"A": 1, "B": 1}
    assert "profile A" in h.ai.calls[-1][2]


@pytest.mark.asyncio
async def test_terminal_failure_and_skip_release_followers_with_current_profile(
    tmp_path: Path,
) -> None:
    h = harness(tmp_path, retries=1)
    key = ("user", "1")
    await h.storage.write_profile(*key, "P0")
    h.ai.failures[("A", key)] = 2
    h.ai.skips.add("B")
    for label in ("A", "B", "C"):
        await h.queue.enqueue(make_job(label, key))
    async with running(h):
        await drained(h)
    assert [label for label, _, _ in h.ai.calls] == ["A", "A", "B", "C"]
    assert all(snapshot == "P0" for _, _, snapshot in h.ai.calls)
    assert h.queue.snapshot()["failed"] == 1


@pytest.mark.asyncio
async def test_vector_failure_retries_current_file_before_follower(
    tmp_path: Path,
) -> None:
    h = harness(tmp_path)
    key = ("user", "1")
    h.vectors.event_failures = 1
    h.vectors.profile_failures = 1
    await h.queue.enqueue(make_job("A", key))
    await h.queue.enqueue(make_job("B", key))
    async with running(h):
        await drained(h)
    assert [label for label, _, _ in h.ai.calls] == ["A", "A", "B"]
    assert "profile A" in h.ai.calls[1][2]
    assert "profile A" in h.ai.calls[2][2]
    assert h.worker.rewrites["A"] == 1


@pytest.mark.asyncio
async def test_terminal_vector_failure_does_not_rollback_existing_file(
    tmp_path: Path,
) -> None:
    h = harness(tmp_path, retries=0)
    key = ("user", "1")
    h.vectors.profile_failures = 1
    await h.queue.enqueue(make_job("A", key))
    await h.queue.enqueue(make_job("B", key))
    async with running(h):
        await drained(h)
    assert [label for label, _, _ in h.ai.calls] == ["A", "B"]
    assert "profile A" in h.ai.calls[1][2]
    assert h.queue.snapshot()["failed"] == 1


@pytest.mark.asyncio
async def test_failed_progress_commit_keeps_follower_waiting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = harness(tmp_path)
    key = ("user", "1")
    first = await h.queue.enqueue(make_job("A", key))
    await h.queue.enqueue(make_job("B", key))
    checkpoint = h.queue.checkpoint
    failed = False

    async def fail_once(job_id: str, job: dict[str, Any]) -> None:
        nonlocal failed
        if (
            job_id == first
            and HistorianProgress.from_job(job).completed_targets
            and not failed
        ):
            failed = True
            raise OSError("checkpoint unavailable")
        await checkpoint(job_id, job)

    monkeypatch.setattr(h.queue, "checkpoint", fail_once)
    async with running(h):
        await drained(h)
    assert [label for label, _, _ in h.ai.calls] == ["A", "A", "B"]
    assert "profile A" in h.ai.calls[-1][2]


@pytest.mark.asyncio
@pytest.mark.parametrize("concurrency", [1, 2, 4])
async def test_dispatch_never_exceeds_concurrency(
    tmp_path: Path, concurrency: int
) -> None:
    h = harness(tmp_path, concurrency=concurrency)
    for index in range(6):
        label, key = f"A{index}", ("user", str(index + 1))
        h.ai.gates[(label, key)] = asyncio.Event()
        await h.queue.enqueue(make_job(label, key))
    async with running(h):
        await until(lambda: len(h.ai.calls) == concurrency)
        assert len(h.worker._inflight_tasks) == concurrency
        for gate in h.ai.gates.values():
            gate.set()
        await drained(h)
    assert len(h.ai.calls) == 6


@pytest.mark.asyncio
async def test_orphan_processing_blocks_only_its_entities_until_recovered(
    tmp_path: Path,
) -> None:
    h = harness(tmp_path)
    key = ("user", "1")
    first = await h.queue.enqueue(make_job("A", key))
    await h.queue.claim(first)
    await h.queue.enqueue(make_job("B", key))
    await h.queue.enqueue(make_job("C", ("user", "2")))
    async with running(h):
        await asyncio.wait_for(h.ai.event("C", ("user", "2")).wait(), 5)
        assert not h.ai.event("B", key).is_set()
        h.worker.config.stale_job_timeout_seconds = -1
        h.worker._wakeup.set()
        await drained(h)
    assert [label for label, target, _ in h.ai.calls if target == key] == ["A", "B"]


@pytest.mark.asyncio
async def test_stop_and_restart_resume_saved_events_and_target_progress(
    tmp_path: Path,
) -> None:
    h = harness(tmp_path)
    group, user = ("group", "1"), ("user", "1")
    first = await h.queue.enqueue(make_job("A", group, user))
    claimed = await h.queue.claim(first)
    assert claimed is not None
    await h.worker._process_job_with_retry(*claimed)
    claimed = await h.queue.claim(first)
    assert claimed is not None
    await h.worker._process_job_with_retry(
        *claimed, target={"entity_type": "group", "entity_id": "1"}
    )
    # 模拟新进程：队列与 worker 均重新构造，profile 与进度留在磁盘。
    resumed = harness(tmp_path)
    await resumed.queue.enqueue(make_job("B", user))
    async with running(resumed):
        await drained(resumed)
    assert resumed.worker.rewrites == {"B": 1}
    assert [(label, key) for label, key, _ in resumed.ai.calls] == [
        ("A", user),
        ("B", user),
    ]
    assert "profile A" in resumed.ai.calls[-1][2]


@pytest.mark.asyncio
async def test_cancellation_waits_for_vector_and_progress_before_release(
    tmp_path: Path,
) -> None:
    h = harness(tmp_path)
    key = ("user", "1")
    h.vectors.profile_gate = asyncio.Event()
    first = await h.queue.enqueue(make_job("A", key))
    await h.queue.enqueue(make_job("B", key))
    async with running(h):
        await asyncio.wait_for(h.vectors.profile_started.wait(), 5)
        task = next(
            task
            for task in h.worker._inflight_tasks
            if task.get_name() == f"historian:{first}"
        )
        task.cancel()
        await asyncio.sleep(0)
        assert first in h.worker._active_jobs
        assert not h.ai.event("B", key).is_set()
        h.vectors.profile_gate.set()
        await drained(h)
    assert "profile A" in h.ai.calls[-1][2]


@pytest.mark.asyncio
async def test_profile_read_failure_never_provides_empty_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = harness(tmp_path, retries=0)
    key = ("user", "1")

    async def broken_read(entity_type: str, entity_id: str) -> str | None:
        raise OSError("read failed")

    monkeypatch.setattr(h.storage, "read_profile", broken_read)
    await h.queue.enqueue(make_job("A", key))
    async with running(h):
        await drained(h)
    assert not h.ai.calls
    assert h.queue.snapshot()["failed"] == 1


@pytest.mark.asyncio
async def test_nickname_refresh_waits_then_preserves_new_profile(
    tmp_path: Path,
) -> None:
    h = harness(tmp_path)
    key = ("user", "1")
    gate = h.ai.gates[("A", key)] = asyncio.Event()
    await h.storage.write_profile(*key, "P0")
    await h.queue.enqueue(make_job("A", key))
    service = CognitiveService(lambda: SimpleNamespace(), h.vectors, h.queue, h.storage)
    async with running(h):
        await asyncio.wait_for(h.ai.event("A", key).wait(), 5)
        refresh = asyncio.create_task(
            service.sync_profile_display_name(
                entity_type="user", entity_id="1", preferred_name="new name"
            )
        )
        await asyncio.sleep(0)
        assert not refresh.done()
        gate.set()
        assert await asyncio.wait_for(refresh, 5)
        await drained(h)
    profile = str(await h.storage.read_profile(*key))
    assert "profile A" in profile and "new name" in profile
    assert "profile A" in h.vectors.profiles["user:1"]


@pytest.mark.asyncio
async def test_model_cannot_update_an_unscheduled_entity(tmp_path: Path) -> None:
    h = harness(tmp_path, retries=0)
    h.ai.wrong_target = True
    await h.queue.enqueue(make_job("A", ("user", "1")))
    async with running(h):
        await drained(h)
    assert await h.storage.read_profile("user", "999999") is None
    assert not h.vectors.profiles
    assert h.queue.snapshot()["failed"] == 1


def test_active_entity_remains_reserved_after_checkpoint_until_phase_returns() -> None:
    first = make_job("A", ("user", "1"))
    progress = HistorianProgress(
        rewrites=["A"], events_written=1, completed_targets=["user:1"]
    )
    progress.store(first)
    second = make_job("B", ("user", "1"))
    HistorianProgress(rewrites=["B"], events_written=1).store(second)
    entries = [QueuedJob("A", first, "processing"), QueuedJob("B", second, "pending")]
    assert select_ready_phase(entries, {"A": ("user", "1")}) is None


@pytest.mark.asyncio
async def test_read_profile_tool_returns_same_prompt_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = harness(tmp_path)
    await h.storage.write_profile("user", "1", "P0")
    original_read = h.storage.read_profile
    original_call = h.ai.submit_background_llm_call
    reads = 0
    calls = 0

    async def read(entity_type: str, entity_id: str) -> str | None:
        nonlocal reads
        reads += 1
        return await original_read(entity_type, entity_id)

    async def call(**kwargs: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        if calls == 1:
            return tool_response(
                "read_profile", {"entity_type": "user", "entity_id": "1"}
            )
        assert kwargs["messages"][-1]["content"] == "P0"
        return await original_call(**kwargs)

    monkeypatch.setattr(h.storage, "read_profile", read)
    monkeypatch.setattr(h.ai, "submit_background_llm_call", call)
    await h.queue.enqueue(make_job("A", ("user", "1")))
    async with running(h):
        await drained(h)
    assert calls == 2 and reads == 1
    assert h.ai.calls[0][2] == "P0"


@pytest.mark.asyncio
async def test_legacy_payload_without_progress_or_explicit_targets(
    tmp_path: Path,
) -> None:
    h = harness(tmp_path)
    await write_json(
        tmp_path / "queue/pending/z_1_1000.json",
        {
            "request_id": "A",
            "new_info": ["A"],
            "has_new_info": True,
            "user_id": "1",
        },
    )
    await write_json(
        tmp_path / "queue/pending/a_1_2000.json",
        {
            "request_id": "B",
            "new_info": ["B"],
            "has_new_info": True,
            "user_id": "1",
        },
    )
    async with running(h):
        await drained(h)
    assert [label for label, _, _ in h.ai.calls] == ["A", "B"]
    assert "profile A" in h.ai.calls[1][2]


@pytest.mark.asyncio
async def test_failed_cleanup_runs_per_dispatch_threshold(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = harness(tmp_path)
    calls: list[Path] = []

    def cleanup(path: Path, *, max_age_seconds: int, max_files: int) -> int:
        calls.append(path)
        return 0

    monkeypatch.setattr("Undefined.utils.cache.cleanup_cache_dir", cleanup)
    h.worker.config.failed_cleanup_interval = 2
    await h.queue.enqueue(make_job("A", ("user", "1")))
    async with running(h):
        await drained(h)
    assert calls == [h.queue._failed_dir]
