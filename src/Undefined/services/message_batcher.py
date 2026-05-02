"""同 sender 短时多消息合并器（MessageBatcher）。

将同一 sender 在 ``window_seconds`` 内连续发送的消息合并到同一轮 AI 触发，
避免多次独立调用 AI 导致重复或行为打架。

调用约定：
- 调用方先按业务规则决定一条消息是否要进 batcher（例如拍一拍、batch 内 @bot
  立刻处理等场景应当旁路），需要合并的消息构造为 :class:`BufferedMessage`
  通过 :meth:`MessageBatcher.submit` 提交。
- 当窗口到期或触发硬顶（条数 / ``max_window_seconds``）时，batcher 调用
  ``flush_callback(items)``，调用方负责拼装 prompt 并入队。
- 关停时调用 :meth:`MessageBatcher.flush_all` 把所有 buckets 立刻 flush。
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from Undefined.config.models import MessageBatcherConfig

logger = logging.getLogger(__name__)


@dataclass
class BufferedMessage:
    """缓冲中的单条消息上下文。"""

    scope: str
    sender_id: int
    text: str
    message_content: list[dict[str, Any]]
    attachments: list[dict[str, str]]
    sender_name: str
    arrival_time: float
    is_private: bool
    trigger_message_id: int | None = None
    is_poke: bool = False
    is_at_bot: bool = False
    is_fake_at: bool = False
    # 群聊扩展字段
    group_id: int | None = None
    group_name: str = ""
    sender_role: str = "member"
    sender_title: str = ""
    sender_level: str = ""


FlushCallback = Callable[[list[BufferedMessage]], Awaitable[None]]


@dataclass
class _BatchState:
    items: list[BufferedMessage] = field(default_factory=list)
    first_arrival_monotonic: float = 0.0
    timer_handle: asyncio.TimerHandle | None = None


def make_scope(*, group_id: int | None = None, user_id: int | None = None) -> str:
    """构造合并 key 的 scope 字符串。"""
    if group_id and group_id > 0:
        return f"group:{group_id}"
    if user_id is not None:
        return f"private:{user_id}"
    return "unknown"


class MessageBatcher:
    """同 sender 短时合并器。"""

    def __init__(
        self,
        config: MessageBatcherConfig,
        flush_callback: FlushCallback,
    ) -> None:
        self._config = config
        self._flush_callback = flush_callback
        self._buckets: dict[tuple[str, int], _BatchState] = {}
        self._lock = asyncio.Lock()

    def update_config(self, config: MessageBatcherConfig) -> None:
        """配置热更新。"""
        self._config = config
        logger.info(
            "[MessageBatcher] 配置已更新: enabled=%s window=%.2fs strategy=%s "
            "max_window=%.2fs max_messages=%s group=%s private=%s",
            config.enabled,
            config.window_seconds,
            config.strategy,
            config.max_window_seconds,
            config.max_messages_per_batch,
            config.group_enabled,
            config.private_enabled,
        )

    @property
    def config(self) -> MessageBatcherConfig:
        return self._config

    def is_enabled_for(self, *, is_group: bool) -> bool:
        cfg = self._config
        if not cfg.enabled or cfg.window_seconds <= 0:
            return False
        return cfg.group_enabled if is_group else cfg.private_enabled

    def has_buffer(self, scope: str, sender_id: int) -> bool:
        return (scope, sender_id) in self._buckets

    async def submit(self, item: BufferedMessage) -> None:
        """提交一条消息。

        - 若同 (scope, sender_id) 无 buffer：开新 batch，启动 timer。
        - 若已有 buffer：追加；
            - extend 策略 → 重置 timer
            - fixed 策略 → 不重置 timer（仅在剩余时间窗内合并）
        - 触发 ``max_messages_per_batch`` / ``max_window_seconds`` 时立即发车。
        """
        cfg = self._config
        key = (item.scope, item.sender_id)
        flush_items: list[BufferedMessage] | None = None

        async with self._lock:
            state = self._buckets.get(key)
            now_mono = time.monotonic()
            if state is None:
                state = _BatchState(first_arrival_monotonic=now_mono)
                self._buckets[key] = state
            state.items.append(item)
            self._cancel_timer(state)

            elapsed = now_mono - state.first_arrival_monotonic
            remaining_max = cfg.max_window_seconds - elapsed

            should_flush = False
            if (
                cfg.max_messages_per_batch > 0
                and len(state.items) >= cfg.max_messages_per_batch
            ):
                logger.info(
                    "[MessageBatcher] 达到 max_messages_per_batch=%s 立即发车: "
                    "scope=%s sender=%s",
                    cfg.max_messages_per_batch,
                    item.scope,
                    item.sender_id,
                )
                should_flush = True
            elif remaining_max <= 0:
                logger.info(
                    "[MessageBatcher] 已超 max_window_seconds 硬顶 立即发车: "
                    "scope=%s sender=%s elapsed=%.2fs",
                    item.scope,
                    item.sender_id,
                    elapsed,
                )
                should_flush = True

            if should_flush:
                flush_items = self._pop_locked(key)
            else:
                if cfg.strategy == "fixed":
                    target = state.first_arrival_monotonic + cfg.window_seconds
                    delay = max(0.0, target - now_mono)
                else:  # extend
                    delay = cfg.window_seconds
                # 不超过 max_window 硬顶
                delay = min(delay, remaining_max)
                loop = asyncio.get_running_loop()
                state.timer_handle = loop.call_later(
                    max(0.0, delay), self._on_timer, key
                )
                logger.debug(
                    "[MessageBatcher] 缓冲: scope=%s sender=%s count=%s "
                    "next_flush_in=%.2fs strategy=%s",
                    item.scope,
                    item.sender_id,
                    len(state.items),
                    delay,
                    cfg.strategy,
                )

        if flush_items is not None:
            await self._invoke_callback(flush_items)

    def _cancel_timer(self, state: _BatchState) -> None:
        if state.timer_handle is not None:
            state.timer_handle.cancel()
            state.timer_handle = None

    def _pop_locked(self, key: tuple[str, int]) -> list[BufferedMessage] | None:
        state = self._buckets.pop(key, None)
        if state is None or not state.items:
            return None
        self._cancel_timer(state)
        return list(state.items)

    def _on_timer(self, key: tuple[str, int]) -> None:
        # call_later 在事件循环里同步触发，调度到 task 里 await
        asyncio.create_task(self._flush_key(key))

    async def _flush_key(self, key: tuple[str, int]) -> None:
        async with self._lock:
            items = self._pop_locked(key)
        if items:
            await self._invoke_callback(items)

    async def _invoke_callback(self, items: list[BufferedMessage]) -> None:
        if not items:
            return
        first = items[0]
        logger.info(
            "[MessageBatcher] 发车: scope=%s sender=%s count=%s",
            first.scope,
            first.sender_id,
            len(items),
        )
        try:
            await self._flush_callback(items)
        except Exception:  # noqa: BLE001 - 必须吞掉以保证 batcher 不挂
            logger.exception(
                "[MessageBatcher] flush_callback 异常: scope=%s sender=%s count=%s",
                first.scope,
                first.sender_id,
                len(items),
            )

    async def flush_all(self) -> None:
        """立即 flush 所有 buckets（用于关停）。"""
        async with self._lock:
            keys = list(self._buckets.keys())
        if not keys:
            return
        logger.info("[MessageBatcher] flush_all: pending_buckets=%s", len(keys))
        for key in keys:
            await self._flush_key(key)

    def snapshot(self) -> dict[str, Any]:
        """返回当前 buckets 状态的非阻塞快照（供 Runtime API / WebUI 展示）。"""
        cfg = self._config
        now_mono = time.monotonic()
        buckets: list[dict[str, Any]] = []
        # 直接读 dict 副本；不持锁，可能瞬间不一致但够展示
        for (scope, sender_id), state in list(self._buckets.items()):
            buckets.append(
                {
                    "scope": scope,
                    "sender_id": sender_id,
                    "count": len(state.items),
                    "elapsed_seconds": round(
                        max(0.0, now_mono - state.first_arrival_monotonic), 2
                    ),
                }
            )
        return {
            "config": {
                "enabled": cfg.enabled,
                "window_seconds": cfg.window_seconds,
                "strategy": cfg.strategy,
                "max_window_seconds": cfg.max_window_seconds,
                "max_messages_per_batch": cfg.max_messages_per_batch,
                "group_enabled": cfg.group_enabled,
                "private_enabled": cfg.private_enabled,
            },
            "pending_buckets": len(buckets),
            "buckets": buckets,
        }
