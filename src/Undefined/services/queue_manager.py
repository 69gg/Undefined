"""AI 请求队列管理服务"""

import asyncio
import logging
import time
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)


class QueueManager:
    """负责 AI 请求的队列管理和调度"""

    def __init__(self, ai_request_interval: float = 1.0) -> None:
        self.ai_request_interval = ai_request_interval

        # AI 请求队列（四个队列）
        self._superadmin_queue: asyncio.Queue[dict[str, Any]] = (
            asyncio.Queue()
        )  # 超级管理员私聊队列（最高优先级）
        self._private_queue: asyncio.Queue[dict[str, Any]] = (
            asyncio.Queue()
        )  # 普通私聊队列（高优先级）
        self._group_mention_queue: asyncio.Queue[dict[str, Any]] = (
            asyncio.Queue()
        )  # 群聊被@队列（中等优先级）
        self._group_normal_queue: asyncio.Queue[dict[str, Any]] = (
            asyncio.Queue()
        )  # 群聊普通队列（最低优先级）

        self._processor_task: asyncio.Task[None] | None = None
        self._request_handler: (
            Callable[[dict[str, Any]], Coroutine[Any, Any, None]] | None
        ) = None

    def start(
        self, request_handler: Callable[[dict[str, Any]], Coroutine[Any, Any, None]]
    ) -> None:
        """启动队列处理任务

        参数:
            request_handler: 处理单个请求的异步回调函数
        """
        self._request_handler = request_handler
        if self._processor_task is None or self._processor_task.done():
            self._processor_task = asyncio.create_task(self._process_queue_loop())
            logger.info("[队列服务] 队列处理主循环已启动")

    async def stop(self) -> None:
        """停止队列处理任务"""
        if self._processor_task and not self._processor_task.done():
            logger.info("[队列服务] 正在停止队列处理任务...")
            self._processor_task.cancel()
            try:
                await self._processor_task
            except asyncio.CancelledError:
                pass
            self._processor_task = None
            logger.info("[队列服务] 队列处理任务已停止")

    async def add_superadmin_request(self, request: dict[str, Any]) -> None:
        """添加超级管理员请求"""
        await self._superadmin_queue.put(request)
        logger.info(
            f"[队列入队] 超级管理员私聊: 队列长度={self._superadmin_queue.qsize()}"
        )

    async def add_private_request(self, request: dict[str, Any]) -> None:
        """添加普通私聊请求"""
        await self._private_queue.put(request)
        logger.info(f"[队列入队] 普通私聊: 队列长度={self._private_queue.qsize()}")

    async def add_group_mention_request(self, request: dict[str, Any]) -> None:
        """添加群聊被@请求"""
        await self._group_mention_queue.put(request)
        logger.info(f"[队列入队] 群聊被@: 队列长度={self._group_mention_queue.qsize()}")

    async def add_group_normal_request(self, request: dict[str, Any]) -> None:
        """添加群聊普通请求 (会自动裁剪)"""
        self._trim_normal_queue()
        await self._group_normal_queue.put(request)
        logger.info(f"[队列入队] 群聊普通: 队列长度={self._group_normal_queue.qsize()}")

    def _trim_normal_queue(self) -> None:
        """如果群聊普通队列超过10个，仅保留最新的2个"""
        queue_size = self._group_normal_queue.qsize()
        if queue_size > 10:
            logger.info(
                f"[队列修剪] 群聊普通队列长度 {queue_size} 超过阈值(10)，正在修剪..."
            )
            # 取出所有元素
            all_requests: list[dict[str, Any]] = []
            while not self._group_normal_queue.empty():
                all_requests.append(self._group_normal_queue.get_nowait())
            # 只保留最新的2个
            latest_requests = all_requests[-2:]
            # 放回队列
            for req in latest_requests:
                self._group_normal_queue.put_nowait(req)
            logger.info(f"[队列修剪] 修剪完成，保留最新 {len(latest_requests)} 个请求")

    async def _process_queue_loop(self) -> None:
        """队列处理主循环"""
        queues = [
            self._superadmin_queue,
            self._private_queue,
            self._group_mention_queue,
            self._group_normal_queue,
        ]
        queue_names = ["超级管理员私聊", "私聊", "群聊被@", "群聊普通"]

        current_queue_idx = 0
        current_queue_processed = 0
        last_transfer_to_normal = False
        transfer_count = 0

        try:
            while True:
                try:
                    current_queue = queues[current_queue_idx]

                    if current_queue.empty():
                        all_empty = all(q.empty() for q in queues)
                        if all_empty:
                            await asyncio.sleep(0.2)
                            continue

                        current_queue_idx = (current_queue_idx + 1) % 4
                        current_queue_processed = 0
                        transfer_count += 1
                        continue

                    request = await current_queue.get()
                    request_type = request.get("type", "unknown")

                    logger.info(
                        f"[队列处理] 正在处理 {queue_names[current_queue_idx]} 请求: {request_type} "
                        f"(剩余={current_queue.qsize()})"
                    )

                    try:
                        start_time = time.perf_counter()
                        if self._request_handler:
                            await self._request_handler(request)
                        duration = time.perf_counter() - start_time
                        logger.info(
                            f"[队列处理] {queue_names[current_queue_idx]} 请求处理完成, 耗时={duration:.2f}s"
                        )
                    except Exception as e:
                        logger.exception(f"[队列处理] 处理请求失败: {e}")
                    finally:
                        current_queue.task_done()

                    current_queue_processed += 1

                    # 调度逻辑：每个高优先级队列处理2个后切换
                    if current_queue_processed >= 2:
                        next_queue_idx = (current_queue_idx + 1) % 4
                        logger.info(
                            f"QueueManager: {queue_names[current_queue_idx]}队列已处理2条，"
                            f"转移到{queue_names[next_queue_idx]}队列"
                        )

                        if next_queue_idx == 3:
                            last_transfer_to_normal = True
                        else:
                            last_transfer_to_normal = False

                        current_queue_idx = next_queue_idx
                        current_queue_processed = 0
                        transfer_count += 1

                    # 防饿死逻辑：强制处理普通队列
                    if (
                        transfer_count > 0
                        and transfer_count % 2 == 0
                        and not last_transfer_to_normal
                    ):
                        if not self._group_normal_queue.empty():
                            normal_request = await self._group_normal_queue.get()
                            normal_type = normal_request.get("type", "unknown")
                            logger.info(
                                f"QueueManager: 强制处理群聊普通请求: {normal_type}"
                            )
                            try:
                                if self._request_handler:
                                    await self._request_handler(normal_request)
                            except Exception as e:
                                logger.exception(
                                    f"QueueManager: 处理群聊普通请求失败: {e}"
                                )
                            finally:
                                self._group_normal_queue.task_done()
                        transfer_count = 0

                    await asyncio.sleep(self.ai_request_interval)

                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.exception(f"QueueManager: 队列循环异常: {e}")
                    await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            logger.info("QueueManager: 任务被取消")
        finally:
            logger.info("QueueManager: 任务已退出")
