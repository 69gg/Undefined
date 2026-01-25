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
            logger.info(
                f"[队列修剪][{self.model_name}] 群聊普通队列长度 {queue_size} 超过阈值(10)，正在修剪..."
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
                f"[队列修剪][{self.model_name}] 修剪完成，保留最新 {len(latest_requests)} 个请求"
            )


class QueueManager:
    """负责 AI 请求的队列管理和调度

    采用“站台-列车”模型：
    1. 每个模型有独立的队列组（站台）
    2. 每个模型每秒发车一次（列车），带走一个请求
    3. 请求处理是异步不阻塞的（不管前一个是否结束）
    """

    def __init__(self, ai_request_interval: float = 1.0) -> None:
        self.ai_request_interval = ai_request_interval

        # 按模型名称区分的队列组
        self._model_queues: dict[str, ModelQueue] = {}

        # 处理任务映射 model_name -> Task
        self._processor_tasks: dict[str, asyncio.Task[None]] = {}

        self._request_handler: (
            Callable[[dict[str, Any]], Coroutine[Any, Any, None]] | None
        ) = None

    def start(
        self, request_handler: Callable[[dict[str, Any]], Coroutine[Any, Any, None]]
    ) -> None:
        """启动队列处理任务"""
        self._request_handler = request_handler
        logger.info("[队列服务] 队列管理器已就绪")

    async def stop(self) -> None:
        """停止所有队列处理任务"""
        logger.info("[队列服务] 正在停止所有队列处理任务...")
        for name, task in self._processor_tasks.items():
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._processor_tasks.clear()
        logger.info("[队列服务] 所有队列处理任务已停止")

    def _get_or_create_queue(self, model_name: str) -> ModelQueue:
        """获取或创建指定模型的队列，并确保处理任务已启动"""
        if model_name not in self._model_queues:
            self._model_queues[model_name] = ModelQueue(model_name=model_name)
            # 启动该模型的处理任务
            if self._request_handler:
                task = asyncio.create_task(self._process_model_loop(model_name))
                self._processor_tasks[model_name] = task
                logger.info(f"[队列服务] 已启动模型 [{model_name}] 的处理循环")
        return self._model_queues[model_name]

    async def add_superadmin_request(
        self, request: dict[str, Any], model_name: str = "default"
    ) -> None:
        """添加超级管理员请求"""
        queue = self._get_or_create_queue(model_name)
        await queue.superadmin_queue.put(request)
        logger.info(
            f"[队列入队][{model_name}] 超级管理员私聊: 队列长度={queue.superadmin_queue.qsize()}"
        )

    async def add_private_request(
        self, request: dict[str, Any], model_name: str = "default"
    ) -> None:
        """添加普通私聊请求"""
        queue = self._get_or_create_queue(model_name)
        await queue.private_queue.put(request)
        logger.info(
            f"[队列入队][{model_name}] 普通私聊: 队列长度={queue.private_queue.qsize()}"
        )

    async def add_group_mention_request(
        self, request: dict[str, Any], model_name: str = "default"
    ) -> None:
        """添加群聊被@请求"""
        queue = self._get_or_create_queue(model_name)
        await queue.group_mention_queue.put(request)
        logger.info(
            f"[队列入队][{model_name}] 群聊被@: 队列长度={queue.group_mention_queue.qsize()}"
        )

    async def add_group_normal_request(
        self, request: dict[str, Any], model_name: str = "default"
    ) -> None:
        """添加群聊普通请求 (会自动裁剪)"""
        queue = self._get_or_create_queue(model_name)
        queue.trim_normal_queue()
        await queue.group_normal_queue.put(request)
        logger.info(
            f"[队列入队][{model_name}] 群聊普通: 队列长度={queue.group_normal_queue.qsize()}"
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

        # 即使没有请求，列车也会每秒发车（检查一次）
        # 这里我们使用 smart sleep: 如果处理了请求，等待剩余时间；如果空闲，等待完整时间?
        # 需求: "列车(AI请求)每1s发车一次... 带走一个请求... 不管前面的请求有没有结束"
        # 意味着频率固定为 1Hz

        try:
            while True:
                cycle_start_time = time.perf_counter()

                # 尝试获取一个请求
                request = None
                chosen_queue_idx = -1

                # 按照优先级和调度逻辑选择一个请求
                # 简单逻辑：遍历优先级，找到第一个非空
                # 原有逻辑：有防饿死机制 (current_queue_processed >= 2 切换)
                # 为了简化且符合“带走一个请求”，我们可以沿用之前的优先级轮转逻辑，
                # 但这必须是非阻塞的 check

                found_request = False

                # 简单的优先级轮询（保留之前的公平性逻辑会比较复杂，这里简化为严格优先级+计数轮转）
                # 为了保持之前的“每个队列处理2个后切换”逻辑，我们需要持久化状态
                # 但这里每次循环都是一次“发车”，所以状态要保存在循环外 (current_queue_idx 等)

                # 尝试从当前关注的队列开始找
                start_idx = current_queue_idx
                for i in range(4):
                    idx = (start_idx + i) % 4
                    q = queues[idx]
                    if not q.empty():
                        request = await q.get()
                        chosen_queue_idx = idx
                        found_request = True
                        break

                if found_request and request:
                    request_type = request.get("type", "unknown")
                    logger.info(
                        f"[队列发车][{model_name}] 载入 {queue_names[chosen_queue_idx]} 请求: {request_type} "
                        f"(当前队列剩余={queues[chosen_queue_idx].qsize()})"
                    )

                    # 异步执行处理，不等待结果
                    if self._request_handler:
                        asyncio.create_task(
                            self._safe_handle_request(
                                request, model_name, queue_names[chosen_queue_idx]
                            )
                        )

                    queues[chosen_queue_idx].task_done()

                    # 更新公平性计数
                    current_queue_processed += 1
                    if current_queue_processed >= 2:
                        current_queue_idx = (current_queue_idx + 1) % 4
                        current_queue_processed = 0
                        # 注意：如果下一个队列是空的，下一次循环会自动找再下一个非空的
                else:
                    # 没有请求，列车空车出发
                    pass

                # 计算需要等待的时间，确保 1s 间隔
                elapsed = time.perf_counter() - cycle_start_time
                wait_time = max(0.0, self.ai_request_interval - elapsed)
                await asyncio.sleep(wait_time)

        except asyncio.CancelledError:
            logger.info(f"QueueManager: 模型 [{model_name}] 处理任务被取消")
        except Exception as e:
            logger.exception(f"QueueManager: 模型 [{model_name}] 循环异常: {e}")

    async def _safe_handle_request(
        self, request: dict[str, Any], model_name: str, queue_name: str
    ) -> None:
        """安全执行请求处理，捕获异常"""
        try:
            start_time = time.perf_counter()
            if self._request_handler:
                await self._request_handler(request)
            duration = time.perf_counter() - start_time
            logger.info(
                f"[请求完成][{model_name}] {queue_name} 请求处理完成, 耗时={duration:.2f}s"
            )
        except Exception as e:
            logger.exception(f"[请求失败][{model_name}] 处理请求失败: {e}")
