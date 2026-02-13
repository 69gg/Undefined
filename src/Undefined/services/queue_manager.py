"""AI 请求队列管理服务"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine


logger = logging.getLogger(__name__)


@dataclass
class ModelQueue:
    """单个模型的优先队列组"""

    model_name: str
    retry_queue: asyncio.Queue[dict[str, Any]] = field(default_factory=asyncio.Queue)
    superadmin_queue: asyncio.Queue[dict[str, Any]] = field(
        default_factory=asyncio.Queue
    )
    private_queue: asyncio.Queue[dict[str, Any]] = field(default_factory=asyncio.Queue)
    group_mention_queue: asyncio.Queue[dict[str, Any]] = field(
        default_factory=asyncio.Queue
    )
    group_normal_queue: asyncio.Queue[dict[str, Any]] = field(
        default_factory=asyncio.Queue
    )

    def trim_normal_queue(self) -> None:
        """如果群聊普通队列超过10个，仅保留最新的2个"""
        queue_size = self.group_normal_queue.qsize()
        if queue_size > 10:
            logger.warning(
                "[队列修剪][%s] 群聊普通队列长度=%s 超过阈值(10)，将丢弃旧请求",
                self.model_name,
                queue_size,
            )
            # 取出所有元素
            all_requests: list[dict[str, Any]] = []
            while not self.group_normal_queue.empty():
                all_requests.append(self.group_normal_queue.get_nowait())
            # 只保留最新的2个
            latest_requests = all_requests[-2:]
            # 放回队列
            for req in latest_requests:
                self.group_normal_queue.put_nowait(req)
            logger.info(
                "[队列修剪][%s] 修剪完成，保留最新=%s",
                self.model_name,
                len(latest_requests),
            )


class QueueManager:
    """负责 AI 请求的队列管理和调度

    采用“站台-列车”模型：
    1. 每个模型有独立的队列组（站台）
    2. 每个模型按配置节奏发车（列车），带走一个请求
    3. 请求处理是异步不阻塞的（不管前一个是否结束）
    """

    def __init__(
        self,
        ai_request_interval: float = 1.0,
        model_intervals: dict[str, float] | None = None,
        max_retries: int = 2,
    ) -> None:
        if ai_request_interval <= 0:
            ai_request_interval = 1.0
        self.ai_request_interval = ai_request_interval
        self._default_interval = ai_request_interval
        self._max_retries = max(0, max_retries)
        self._model_intervals: dict[str, float] = {}
        if model_intervals:
            self.update_model_intervals(model_intervals)

        # 按模型名称区分的队列组
        self._model_queues: dict[str, ModelQueue] = {}

        # 处理任务映射：模型名 -> Task
        self._processor_tasks: dict[str, asyncio.Task[None]] = {}

        # 在途请求任务（发车后异步执行），用于优雅停机时统一回收。
        self._inflight_tasks: set[asyncio.Task[None]] = set()

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
        if value <= 0:
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
            # 启动该模型的处理任务
            if self._request_handler:
                task = asyncio.create_task(self._process_model_loop(model_name))
                self._processor_tasks[model_name] = task
                logger.info("[队列服务] 已启动模型处理循环: model=%s", model_name)
        return self._model_queues[model_name]

    def _format_request_meta(self, request: dict[str, Any]) -> str:
        """格式化请求关键元信息，便于日志排查。"""
        parts: list[str] = []
        request_id = request.get("request_id") or request.get("req_id")
        group_id = request.get("group_id")
        user_id = request.get("user_id")
        message_id = request.get("message_id")
        request_type = request.get("type")
        if request_id:
            parts.append(f"request_id={request_id}")
        if request_type:
            parts.append(f"type={request_type}")
        if group_id is not None:
            parts.append(f"group_id={group_id}")
        if user_id is not None:
            parts.append(f"user_id={user_id}")
        if message_id is not None:
            parts.append(f"message_id={message_id}")
        if not parts:
            return "meta=none"
        return " ".join(parts)

    async def add_superadmin_request(
        self, request: dict[str, Any], model_name: str = "default"
    ) -> None:
        """添加超级管理员请求"""
        queue = self._get_or_create_queue(model_name)
        await queue.superadmin_queue.put(request)
        logger.info(
            "[队列入队][%s] 超级管理员私聊: size=%s %s",
            model_name,
            queue.superadmin_queue.qsize(),
            self._format_request_meta(request),
        )
        logger.debug(
            "[队列入队详情][%s] superadmin keys=%s",
            model_name,
            list(request.keys()),
        )

    async def add_private_request(
        self, request: dict[str, Any], model_name: str = "default"
    ) -> None:
        """添加普通私聊请求"""
        queue = self._get_or_create_queue(model_name)
        await queue.private_queue.put(request)
        logger.info(
            "[队列入队][%s] 普通私聊: size=%s %s",
            model_name,
            queue.private_queue.qsize(),
            self._format_request_meta(request),
        )
        logger.debug(
            "[队列入队详情][%s] private keys=%s",
            model_name,
            list(request.keys()),
        )

    async def add_agent_intro_request(
        self, request: dict[str, Any], model_name: str = "default"
    ) -> None:
        """添加 Agent 自我介绍生成请求（投递到 private_queue）"""
        queue = self._get_or_create_queue(model_name)
        await queue.private_queue.put(request)
        logger.info(
            "[队列入队][%s] Agent 自我介绍: agent=%s size=%s %s",
            model_name,
            request.get("agent_name", "unknown"),
            queue.private_queue.qsize(),
            self._format_request_meta(request),
        )
        logger.debug(
            "[队列入队详情][%s] agent_intro keys=%s",
            model_name,
            list(request.keys()),
        )

    async def add_group_mention_request(
        self, request: dict[str, Any], model_name: str = "default"
    ) -> None:
        """添加群聊被@请求"""
        queue = self._get_or_create_queue(model_name)
        await queue.group_mention_queue.put(request)
        logger.info(
            "[队列入队][%s] 群聊被@: size=%s %s",
            model_name,
            queue.group_mention_queue.qsize(),
            self._format_request_meta(request),
        )
        logger.debug(
            "[队列入队详情][%s] mention keys=%s",
            model_name,
            list(request.keys()),
        )

    async def add_group_normal_request(
        self, request: dict[str, Any], model_name: str = "default"
    ) -> None:
        """添加群聊普通请求 (会自动裁剪)"""
        queue = self._get_or_create_queue(model_name)
        queue.trim_normal_queue()
        await queue.group_normal_queue.put(request)
        logger.info(
            "[队列入队][%s] 群聊普通: size=%s %s",
            model_name,
            queue.group_normal_queue.qsize(),
            self._format_request_meta(request),
        )
        logger.debug(
            "[队列入队详情][%s] normal keys=%s",
            model_name,
            list(request.keys()),
        )

    async def _process_model_loop(self, model_name: str) -> None:
        """单个模型的处理循环（列车调度）"""
        model_queue = self._model_queues[model_name]
        queues = [
            model_queue.superadmin_queue,
            model_queue.private_queue,
            model_queue.group_mention_queue,
            model_queue.group_normal_queue,
        ]
        queue_names = ["超级管理员私聊", "私聊", "群聊被@", "群聊普通"]

        current_queue_idx = 0
        current_queue_processed = 0

        # 即使没有请求，也按模型节奏"发车"一次（检查队列）。
        # 使用"动态睡眠"：若本轮处理过请求，则只睡剩余时间；若空闲则完整等待。
        # 目标：保持固定节奏发车，不等待前一个请求完成。

        try:
            while True:
                cycle_start_time = time.perf_counter()

                request: dict[str, Any] | None = None
                dispatch_queue_name = ""

                # 1. 优先处理重试队列（最高优先级，不参与公平性轮转）
                if not model_queue.retry_queue.empty():
                    request = await model_queue.retry_queue.get()
                    dispatch_queue_name = "重试"
                    model_queue.retry_queue.task_done()
                else:
                    # 2. 按优先级和轮转逻辑选择常规队列
                    start_idx = current_queue_idx
                    for i in range(4):
                        idx = (start_idx + i) % 4
                        q = queues[idx]
                        if not q.empty():
                            request = await q.get()
                            dispatch_queue_name = queue_names[idx]
                            q.task_done()

                            # 更新公平性计数
                            current_queue_processed += 1
                            if current_queue_processed >= 2:
                                current_queue_idx = (current_queue_idx + 1) % 4
                                current_queue_processed = 0
                            break

                # 3. 分发请求
                if request is not None:
                    request_type = request.get("type", "unknown")
                    retry_count = request.get("_retry_count", 0)
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

                    # 异步执行处理，不等待结果（避免阻塞发车节奏）
                    if self._request_handler:
                        inflight_task = asyncio.create_task(
                            self._safe_handle_request(
                                request, model_name, dispatch_queue_name
                            )
                        )
                        self._track_inflight_task(inflight_task)

                # 计算需要等待的时间，确保固定间隔
                elapsed = time.perf_counter() - cycle_start_time
                interval = self.get_interval(model_name)
                wait_time = max(0.0, interval - elapsed)
                await asyncio.sleep(wait_time)

        except asyncio.CancelledError:
            logger.info("[队列服务] 模型处理循环已取消: model=%s", model_name)
        except Exception as exc:
            logger.exception(
                "[队列服务] 模型处理循环异常: model=%s error=%s", model_name, exc
            )

    async def _safe_handle_request(
        self, request: dict[str, Any], model_name: str, queue_name: str
    ) -> None:
        """安全执行请求处理，捕获异常并按需重试"""
        try:
            start_time = time.perf_counter()
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
            retry_count = request.get("_retry_count", 0)
            if self._max_retries > 0 and retry_count < self._max_retries:
                request["_retry_count"] = retry_count + 1
                model_queue = self._model_queues.get(model_name)
                if model_queue:
                    await model_queue.retry_queue.put(request)
                    logger.warning(
                        "[请求重试][%s] 第%s/%s次重试已入队: %s %s",
                        model_name,
                        retry_count + 1,
                        self._max_retries,
                        exc,
                        self._format_request_meta(request),
                    )
                else:
                    logger.exception(
                        "[请求失败][%s] 处理请求异常且队列已不存在: %s %s",
                        model_name,
                        exc,
                        self._format_request_meta(request),
                    )
            else:
                logger.exception(
                    "[请求失败][%s] 处理请求异常%s: %s %s",
                    model_name,
                    f"（已达最大重试次数{self._max_retries}）"
                    if self._max_retries > 0
                    else "",
                    exc,
                    self._format_request_meta(request),
                )
