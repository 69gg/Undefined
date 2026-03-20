"""AI 请求队列管理服务"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine


logger = logging.getLogger(__name__)


QUEUE_LANE_SUPERADMIN = "superadmin"
QUEUE_LANE_GROUP_SUPERADMIN = "group_superadmin"
QUEUE_LANE_PRIVATE = "private"
QUEUE_LANE_GROUP_MENTION = "group_mention"
QUEUE_LANE_GROUP_NORMAL = "group_normal"
QUEUE_LANE_BACKGROUND = "background"

STRICT_PRIORITY_QUEUE_LANES = (
    QUEUE_LANE_SUPERADMIN,
    QUEUE_LANE_GROUP_SUPERADMIN,
)
ROTATING_QUEUE_LANES = (
    QUEUE_LANE_PRIVATE,
    QUEUE_LANE_GROUP_MENTION,
    QUEUE_LANE_GROUP_NORMAL,
)
ALL_QUEUE_LANES = (
    *STRICT_PRIORITY_QUEUE_LANES,
    *ROTATING_QUEUE_LANES,
    QUEUE_LANE_BACKGROUND,
)

QUEUE_LANE_DISPLAY_NAMES = {
    QUEUE_LANE_SUPERADMIN: "超级管理员私聊",
    QUEUE_LANE_GROUP_SUPERADMIN: "群聊超级管理员",
    QUEUE_LANE_PRIVATE: "普通私聊",
    QUEUE_LANE_GROUP_MENTION: "群聊被@",
    QUEUE_LANE_GROUP_NORMAL: "群聊普通",
    QUEUE_LANE_BACKGROUND: "后台请求",
}


@dataclass
class LaneQueue:
    """支持尾插与“插入第 2 位”的轻量队列。"""

    _items: deque[dict[str, Any]] = field(default_factory=deque)

    def qsize(self) -> int:
        return len(self._items)

    def empty(self) -> bool:
        return not self._items

    async def put(self, item: dict[str, Any]) -> None:
        self.put_nowait(item)

    def put_nowait(self, item: dict[str, Any]) -> None:
        self._items.append(item)

    async def put_second(self, item: dict[str, Any]) -> None:
        self.put_second_nowait(item)

    def put_second_nowait(self, item: dict[str, Any]) -> None:
        if len(self._items) <= 1:
            self._items.append(item)
            return
        items = list(self._items)
        items.insert(1, item)
        self._items = deque(items)

    async def get(self) -> dict[str, Any]:
        return self.get_nowait()

    def get_nowait(self) -> dict[str, Any]:
        return self._items.popleft()

    def drain(self) -> list[dict[str, Any]]:
        items = list(self._items)
        self._items.clear()
        return items

    def retry_count(self) -> int:
        return sum(
            1 for item in self._items if int(item.get("_retry_count", 0) or 0) > 0
        )


@dataclass
class ModelQueue:
    """单个模型的优先队列组"""

    model_name: str
    superadmin_queue: LaneQueue = field(default_factory=LaneQueue)
    group_superadmin_queue: LaneQueue = field(default_factory=LaneQueue)
    private_queue: LaneQueue = field(default_factory=LaneQueue)
    group_mention_queue: LaneQueue = field(default_factory=LaneQueue)
    group_normal_queue: LaneQueue = field(default_factory=LaneQueue)
    background_queue: LaneQueue = field(default_factory=LaneQueue)

    def lane_queues(self) -> dict[str, LaneQueue]:
        return {
            QUEUE_LANE_SUPERADMIN: self.superadmin_queue,
            QUEUE_LANE_GROUP_SUPERADMIN: self.group_superadmin_queue,
            QUEUE_LANE_PRIVATE: self.private_queue,
            QUEUE_LANE_GROUP_MENTION: self.group_mention_queue,
            QUEUE_LANE_GROUP_NORMAL: self.group_normal_queue,
            QUEUE_LANE_BACKGROUND: self.background_queue,
        }

    def total_retry_count(self) -> int:
        return sum(queue.retry_count() for queue in self.lane_queues().values())

    def trim_normal_queue(self) -> None:
        """如果群聊普通队列超过10个，仅保留最新的2个"""
        queue_size = self.group_normal_queue.qsize()
        if queue_size > 10:
            logger.warning(
                "[队列修剪][%s] 群聊普通队列长度=%s 超过阈值(10)，将丢弃旧请求",
                self.model_name,
                queue_size,
            )
            latest_requests = self.group_normal_queue.drain()[-2:]
            for req in latest_requests:
                self.group_normal_queue.put_nowait(req)
            logger.info(
                "[队列修剪][%s] 修剪完成，保留最新=%s",
                self.model_name,
                len(latest_requests),
            )


@dataclass(frozen=True)
class QueueEnqueueReceipt:
    model_name: str
    lane: str
    size: int
    estimated_wait_seconds: float


class QueueManager:
    """负责 AI 请求的队列管理和调度"""

    def __init__(
        self,
        ai_request_interval: float = 1.0,
        model_intervals: dict[str, float] | None = None,
        max_retries: int = 2,
    ) -> None:
        if ai_request_interval < 0:
            ai_request_interval = 1.0
        self.ai_request_interval = ai_request_interval
        self._default_interval = ai_request_interval
        self._max_retries = max(0, max_retries)
        self._model_intervals: dict[str, float] = {}
        if model_intervals:
            self.update_model_intervals(model_intervals)

        self._model_queues: dict[str, ModelQueue] = {}
        self._processor_tasks: dict[str, asyncio.Task[None]] = {}
        self._inflight_tasks: set[asyncio.Task[None]] = set()
        self._next_dispatch_at: dict[str, float] = {}
        self._request_handler: (
            Callable[[dict[str, Any]], Coroutine[Any, Any, None]] | None
        ) = None

    def update_model_intervals(self, model_intervals: dict[str, float]) -> None:
        """更新模型队列发车节奏映射。"""
        normalized: dict[str, float] = {}
        for model_name, interval in model_intervals.items():
            if not isinstance(model_name, str):
                continue
            name = model_name.strip()
            if not name:
                continue
            normalized[name] = self._normalize_interval(interval)
        self._model_intervals = normalized
        logger.info(
            "[队列服务] 已更新模型发车节奏: count=%s default=%.2fs",
            len(self._model_intervals),
            self._default_interval,
        )

    def get_interval(self, model_name: str) -> float:
        """获取指定模型的发车节奏。"""
        if not model_name:
            return self._default_interval
        return self._model_intervals.get(model_name, self._default_interval)

    def _normalize_interval(self, interval: float) -> float:
        try:
            value = float(interval)
        except (TypeError, ValueError):
            return self._default_interval
        if value < 0:
            return self._default_interval
        return value

    def start(
        self, request_handler: Callable[[dict[str, Any]], Coroutine[Any, Any, None]]
    ) -> None:
        """启动队列处理任务"""
        self._request_handler = request_handler
        logger.info(
            "[队列服务] 队列管理器已就绪: default_interval=%.2fs",
            self._default_interval,
        )

    async def stop(self) -> None:
        """停止所有队列处理任务"""
        logger.info(
            "[队列服务] 正在停止所有队列处理任务: processors=%s inflight=%s",
            len(self._processor_tasks),
            len(self._inflight_tasks),
        )
        for name, task in self._processor_tasks.items():
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._processor_tasks.clear()
        self._next_dispatch_at.clear()

        inflight_count = len(self._inflight_tasks)
        if inflight_count > 0:
            logger.info("[队列服务] 正在回收在途请求任务: count=%s", inflight_count)
            for task in list(self._inflight_tasks):
                if not task.done():
                    task.cancel()
            results = await asyncio.gather(
                *list(self._inflight_tasks), return_exceptions=True
            )
            cancelled_count = sum(
                1 for result in results if isinstance(result, asyncio.CancelledError)
            )
            error_count = sum(
                1
                for result in results
                if isinstance(result, Exception)
                and not isinstance(result, asyncio.CancelledError)
            )
            logger.info(
                "[队列服务] 在途任务回收完成: cancelled=%s errors=%s",
                cancelled_count,
                error_count,
            )
            self._inflight_tasks.clear()

        logger.info("[队列服务] 所有队列处理任务已停止")

    def _track_inflight_task(self, task: asyncio.Task[None]) -> None:
        """追踪在途任务，并在完成时自动移除。"""

        self._inflight_tasks.add(task)

        def _cleanup(done_task: asyncio.Task[None]) -> None:
            self._inflight_tasks.discard(done_task)

        task.add_done_callback(_cleanup)

    def _get_or_create_queue(self, model_name: str) -> ModelQueue:
        """获取或创建指定模型的队列，并确保处理任务已启动"""
        if model_name not in self._model_queues:
            self._model_queues[model_name] = ModelQueue(model_name=model_name)
            if self._request_handler:
                task = asyncio.create_task(self._process_model_loop(model_name))
                self._processor_tasks[model_name] = task
                logger.info("[队列服务] 已启动模型处理循环: model=%s", model_name)
        return self._model_queues[model_name]

    def snapshot(self) -> dict[str, Any]:
        """返回当前队列状态快照。"""
        models: dict[str, dict[str, int]] = {}
        totals = {
            "retry": 0,
            **{lane: 0 for lane in ALL_QUEUE_LANES},
        }

        for model_name, queue in self._model_queues.items():
            model_snapshot = {
                "retry": queue.total_retry_count(),
                **{
                    lane: lane_queue.qsize()
                    for lane, lane_queue in queue.lane_queues().items()
                },
            }
            models[model_name] = model_snapshot
            for key, value in model_snapshot.items():
                totals[key] += value

        return {
            "default_interval_seconds": self._default_interval,
            "max_retries": self._max_retries,
            "processor_count": len(self._processor_tasks),
            "inflight_count": len(self._inflight_tasks),
            "model_count": len(models),
            "models": models,
            "totals": totals,
        }

    def _format_request_meta(self, request: dict[str, Any]) -> str:
        """格式化请求关键元信息，便于日志排查。"""
        parts: list[str] = []
        request_id = request.get("request_id") or request.get("req_id")
        group_id = request.get("group_id")
        user_id = request.get("user_id")
        message_id = request.get("message_id")
        request_type = request.get("type")
        queue_lane = request.get("_queue_lane")
        if request_id:
            parts.append(f"request_id={request_id}")
        if request_type:
            parts.append(f"type={request_type}")
        if queue_lane:
            parts.append(f"lane={queue_lane}")
        if group_id is not None:
            parts.append(f"group_id={group_id}")
        if user_id is not None:
            parts.append(f"user_id={user_id}")
        if message_id is not None:
            parts.append(f"message_id={message_id}")
        if not parts:
            return "meta=none"
        return " ".join(parts)

    def get_max_retries(self) -> int:
        return self._max_retries

    def update_max_retries(self, max_retries: int) -> None:
        self._max_retries = max(0, int(max_retries))
        logger.info("[队列服务] 已更新最大重试次数: max_retries=%s", self._max_retries)

    def estimate_wait_seconds(self, model_name: str, lane: str) -> float:
        model_queue = self._model_queues.get(model_name)
        if model_queue is None:
            return 0.0
        now = time.perf_counter()
        base_wait = max(0.0, self._next_dispatch_at.get(model_name, now) - now)
        total_pending = sum(
            lane_queue.qsize() for lane_queue in model_queue.lane_queues().values()
        )
        ahead = max(0, total_pending - 1)
        return base_wait + (self.get_interval(model_name) * ahead)

    def _get_lane_queue(self, model_queue: ModelQueue, lane: str) -> LaneQueue:
        lane_queue = model_queue.lane_queues().get(lane)
        if lane_queue is not None:
            return lane_queue
        return model_queue.background_queue

    async def _enqueue_lane_request(
        self,
        request: dict[str, Any],
        *,
        model_name: str,
        lane: str,
        display_name: str,
        insert_second: bool = False,
    ) -> QueueEnqueueReceipt:
        queue = self._get_or_create_queue(model_name)
        request["_queue_lane"] = lane
        lane_queue = self._get_lane_queue(queue, lane)
        if lane == QUEUE_LANE_GROUP_NORMAL and not insert_second:
            queue.trim_normal_queue()
        if insert_second:
            await lane_queue.put_second(request)
        else:
            await lane_queue.put(request)
        logger.info(
            "[队列入队][%s] %s: size=%s %s",
            model_name,
            display_name,
            lane_queue.qsize(),
            self._format_request_meta(request),
        )
        logger.debug(
            "[队列入队详情][%s] lane=%s keys=%s",
            model_name,
            lane,
            list(request.keys()),
        )
        return QueueEnqueueReceipt(
            model_name=model_name,
            lane=lane,
            size=lane_queue.qsize(),
            estimated_wait_seconds=self.estimate_wait_seconds(model_name, lane),
        )

    async def add_superadmin_request(
        self, request: dict[str, Any], model_name: str = "default"
    ) -> QueueEnqueueReceipt:
        """添加超级管理员私聊请求"""
        return await self._enqueue_lane_request(
            request,
            model_name=model_name,
            lane=QUEUE_LANE_SUPERADMIN,
            display_name=QUEUE_LANE_DISPLAY_NAMES[QUEUE_LANE_SUPERADMIN],
        )

    async def add_group_superadmin_request(
        self, request: dict[str, Any], model_name: str = "default"
    ) -> QueueEnqueueReceipt:
        """添加群聊超级管理员请求"""
        return await self._enqueue_lane_request(
            request,
            model_name=model_name,
            lane=QUEUE_LANE_GROUP_SUPERADMIN,
            display_name=QUEUE_LANE_DISPLAY_NAMES[QUEUE_LANE_GROUP_SUPERADMIN],
        )

    async def add_private_request(
        self, request: dict[str, Any], model_name: str = "default"
    ) -> QueueEnqueueReceipt:
        """添加普通私聊请求"""
        return await self._enqueue_lane_request(
            request,
            model_name=model_name,
            lane=QUEUE_LANE_PRIVATE,
            display_name=QUEUE_LANE_DISPLAY_NAMES[QUEUE_LANE_PRIVATE],
        )

    async def add_agent_intro_request(
        self, request: dict[str, Any], model_name: str = "default"
    ) -> QueueEnqueueReceipt:
        """添加 Agent 自我介绍生成请求（投递到 private_queue）"""
        return await self._enqueue_lane_request(
            request,
            model_name=model_name,
            lane=QUEUE_LANE_PRIVATE,
            display_name="Agent 自我介绍",
        )

    async def add_group_mention_request(
        self, request: dict[str, Any], model_name: str = "default"
    ) -> QueueEnqueueReceipt:
        """添加群聊被@请求"""
        return await self._enqueue_lane_request(
            request,
            model_name=model_name,
            lane=QUEUE_LANE_GROUP_MENTION,
            display_name=QUEUE_LANE_DISPLAY_NAMES[QUEUE_LANE_GROUP_MENTION],
        )

    async def add_group_normal_request(
        self, request: dict[str, Any], model_name: str = "default"
    ) -> QueueEnqueueReceipt:
        """添加群聊普通请求 (会自动裁剪)"""
        return await self._enqueue_lane_request(
            request,
            model_name=model_name,
            lane=QUEUE_LANE_GROUP_NORMAL,
            display_name=QUEUE_LANE_DISPLAY_NAMES[QUEUE_LANE_GROUP_NORMAL],
        )

    async def add_background_request(
        self, request: dict[str, Any], model_name: str = "default"
    ) -> QueueEnqueueReceipt:
        """添加后台低优先级请求。"""
        return await self._enqueue_lane_request(
            request,
            model_name=model_name,
            lane=QUEUE_LANE_BACKGROUND,
            display_name=QUEUE_LANE_DISPLAY_NAMES[QUEUE_LANE_BACKGROUND],
        )

    async def add_queued_llm_request(
        self,
        request: dict[str, Any],
        *,
        lane: str,
        model_name: str = "default",
        insert_second: bool = False,
    ) -> QueueEnqueueReceipt:
        """添加可重试的 LLM 子请求。"""
        request["type"] = "queued_llm_call"
        return await self._enqueue_lane_request(
            request,
            model_name=model_name,
            lane=lane,
            display_name="LLM 子请求" + ("重试" if insert_second else ""),
            insert_second=insert_second,
        )

    async def _process_model_loop(self, model_name: str) -> None:
        """单个模型的处理循环（列车调度）"""
        model_queue = self._model_queues[model_name]
        lane_queues = model_queue.lane_queues()
        rotating_queues = [lane_queues[lane] for lane in ROTATING_QUEUE_LANES]
        rotating_queue_names = [
            QUEUE_LANE_DISPLAY_NAMES[lane] for lane in ROTATING_QUEUE_LANES
        ]

        current_queue_idx = 0
        current_queue_processed = 0

        try:
            while True:
                cycle_start_time = time.perf_counter()
                interval = self.get_interval(model_name)
                self._next_dispatch_at[model_name] = cycle_start_time + interval

                request: dict[str, Any] | None = None
                dispatch_queue_name = ""

                for lane in STRICT_PRIORITY_QUEUE_LANES:
                    queue = lane_queues[lane]
                    if queue.empty():
                        continue
                    request = queue.get_nowait()
                    dispatch_queue_name = QUEUE_LANE_DISPLAY_NAMES[lane]
                    break
                if request is None:
                    start_idx = current_queue_idx
                    for i in range(len(rotating_queues)):
                        idx = (start_idx + i) % len(rotating_queues)
                        queue = rotating_queues[idx]
                        if queue.empty():
                            continue
                        request = queue.get_nowait()
                        dispatch_queue_name = rotating_queue_names[idx]
                        current_queue_processed += 1
                        if current_queue_processed >= 2:
                            current_queue_idx = (current_queue_idx + 1) % len(
                                rotating_queues
                            )
                            current_queue_processed = 0
                        break

                if request is None and not model_queue.background_queue.empty():
                    request = model_queue.background_queue.get_nowait()
                    dispatch_queue_name = QUEUE_LANE_DISPLAY_NAMES[
                        QUEUE_LANE_BACKGROUND
                    ]

                if request is not None:
                    request_type = request.get("type", "unknown")
                    retry_count = int(request.get("_retry_count", 0) or 0)
                    retry_suffix = (
                        f" (重试第{retry_count}次)" if retry_count > 0 else ""
                    )
                    logger.info(
                        "[队列发车][%s] %s 请求%s: %s %s",
                        model_name,
                        dispatch_queue_name,
                        retry_suffix,
                        request_type,
                        self._format_request_meta(request),
                    )
                    if self._request_handler:
                        inflight_task = asyncio.create_task(
                            self._safe_handle_request(
                                request, model_name, dispatch_queue_name
                            )
                        )
                        self._track_inflight_task(inflight_task)

                elapsed = time.perf_counter() - cycle_start_time
                wait_time = max(0.0, interval - elapsed)
                await asyncio.sleep(wait_time)

        except asyncio.CancelledError:
            logger.info("[队列服务] 模型处理循环已取消: model=%s", model_name)
        except Exception as exc:
            logger.exception(
                "[队列服务] 模型处理循环异常: model=%s error=%s", model_name, exc
            )
        finally:
            self._next_dispatch_at.pop(model_name, None)

    async def _safe_handle_request(
        self, request: dict[str, Any], model_name: str, queue_name: str
    ) -> None:
        """安全执行请求处理。仅 queued_llm_call 允许自动重试。"""
        start_time = time.perf_counter()
        try:
            logger.debug(
                "[请求处理] model=%s queue=%s type=%s %s",
                model_name,
                queue_name,
                request.get("type", "unknown"),
                self._format_request_meta(request),
            )
            if self._request_handler:
                await self._request_handler(request)
            duration = time.perf_counter() - start_time
            logger.info(
                "[请求完成][%s] %s 请求处理完成: elapsed=%.2fs %s",
                model_name,
                queue_name,
                duration,
                self._format_request_meta(request),
            )
        except Exception as exc:
            duration = time.perf_counter() - start_time
            request_type = str(request.get("type", "unknown") or "unknown")
            if request_type != "queued_llm_call":
                logger.exception(
                    "[请求失败][%s] 非LLM请求不重试: queue=%s elapsed=%.2fs %s error=%s",
                    model_name,
                    queue_name,
                    duration,
                    self._format_request_meta(request),
                    exc,
                )
                return

            retry_count = int(request.get("_retry_count", 0) or 0)
            queue_lane = str(request.get("_queue_lane") or QUEUE_LANE_BACKGROUND)
            if self._max_retries > 0 and retry_count < self._max_retries:
                request["_retry_count"] = retry_count + 1
                model_queue = self._model_queues.get(model_name)
                if model_queue is None:
                    logger.exception(
                        "[queued_llm_retry_requeue] 队列已不存在: model=%s lane=%s retry=%s/%s %s error=%s",
                        model_name,
                        queue_lane,
                        retry_count + 1,
                        self._max_retries,
                        self._format_request_meta(request),
                        exc,
                    )
                    return
                await self._get_lane_queue(model_queue, queue_lane).put_second(request)
                logger.warning(
                    "[queued_llm_retry_requeue] model=%s lane=%s retry=%s/%s position=2 elapsed=%.2fs %s error=%s",
                    model_name,
                    queue_lane,
                    retry_count + 1,
                    self._max_retries,
                    duration,
                    self._format_request_meta(request),
                    exc,
                )
                return

            logger.exception(
                "[queued_llm_retry_exhausted] model=%s lane=%s retries=%s/%s elapsed=%.2fs %s error=%s",
                model_name,
                queue_lane,
                retry_count,
                self._max_retries,
                duration,
                self._format_request_meta(request),
                exc,
            )
