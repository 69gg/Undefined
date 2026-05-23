"""MessageBatcher 调度与 timer 逻辑。"""

from __future__ import annotations

# 同 sender 短时合并：T1 结束 batch，T2 投机预发送

import asyncio
import logging
import time
from typing import Any

from Undefined.config.models import MessageBatcherConfig
from Undefined.services.message_batcher.state import (
    BatchDispatchToken,
    BatchPhase,
    BufferedMessage,
    FlushCallback,
    _BatchState,
    _InflightInfo,
)
from Undefined.utils.coerce import was_message_sent

logger = logging.getLogger(__name__)


class MessageBatcher:
    """同 sender 短时合并器（含 T2 投机预发送）。"""

    def __init__(
        self,
        config: MessageBatcherConfig,
        flush_callback: FlushCallback,
    ) -> None:
        self._config = config
        self._flush_callback = flush_callback
        self._buckets: dict[tuple[str, int], _BatchState] = {}
        self._flush_failure_counts: dict[tuple[str, int], int] = {}
        self._lock = asyncio.Lock()
        # 持有 timer 触发后创建的 flush task 强引用，避免被 GC（asyncio 文档要求）
        self._pending_tasks: set[asyncio.Task[Any]] = set()
        self._next_batch_id = 0
        self._shutdown = False

    # ------------------------------------------------------------------ public

    def update_config(self, config: MessageBatcherConfig) -> None:
        """配置热更新。"""
        self._config = config
        logger.info(
            "[MessageBatcher] 配置已更新: enabled=%s window=%.2fs pre_send=%.2fs "
            "strategy=%s max_window=%.2fs max_messages=%s group=%s private=%s "
            "allow_cancel_after_send=%s",
            config.enabled,
            config.window_seconds,
            config.pre_send_seconds,
            config.strategy,
            config.max_window_seconds,
            config.max_messages_per_batch,
            config.group_enabled,
            config.private_enabled,
            config.allow_cancel_after_send,
        )

    @property
    def config(self) -> MessageBatcherConfig:
        return self._config

    def is_enabled_for(self, *, is_group: bool) -> bool:
        cfg = self._config
        if not cfg.enabled or cfg.window_seconds <= 0:
            return False
        return cfg.group_enabled if is_group else cfg.private_enabled

    # 立即触发 batch 发车
    def has_buffer(self, scope: str, sender_id: int) -> bool:
        return (scope, sender_id) in self._buckets

    # 立即触发 batch 发车
    async def flush_sender(self, scope: str, sender_id: int) -> bool:
        return await self._handle_t1((scope, sender_id), raise_on_failure=False)

    @property
    def speculative_enabled(self) -> bool:
        # 0 < pre_send < window 时启用 T2 投机预发送
        cfg = self._config
        return 0 < cfg.pre_send_seconds < cfg.window_seconds

    # 提交消息进入 (scope,sender) 合并桶并重置 T1/T2 计时器
    async def submit(self, item: BufferedMessage) -> None:
        """提交一条消息进入合并桶。

        新消息到来时的处理依赖当前桶 ``phase``，详见模块 docstring。
        """
        cfg = self._config
        key = (item.scope, item.sender_id)
        # 异步路径里只在锁内修改桶；invoke callback 在锁外执行
        immediate_fire_items: list[BufferedMessage] | None = None

        async with self._lock:
            if self._shutdown:
                logger.info(
                    "[MessageBatcher] 已进入关停模式，新消息立即发车: scope=%s sender=%s",
                    item.scope,
                    item.sender_id,
                )
                immediate_fire_items = [item]
            else:
                now_mono = time.monotonic()
                state = self._buckets.get(key)

                # === 阶段 1: 决定本条消息怎么进桶 ===
                if state is None:
                    # 全新桶
                    state = _BatchState(
                        phase=BatchPhase.TYPING,
                        first_arrival_monotonic=now_mono,
                        dispatch_token=self._new_token(item.scope, item.sender_id),
                    )
                    self._buckets[key] = state
                    state.items.append(item)
                elif state.phase is BatchPhase.SPECULATING:
                    # 已 pre-fire，决定是否 cancel inflight
                    inflight = state.inflight
                    already_sent = (
                        was_message_sent(inflight.request_context)
                        if inflight is not None
                        else False
                    )
                    allow_cancel = (not already_sent) or cfg.allow_cancel_after_send

                    if inflight is not None and allow_cancel:
                        logger.info(
                            "[MessageBatcher] 投机调用被新消息抢占取消: scope=%s sender=%s "
                            "already_sent=%s allow_cancel_after_send=%s",
                            item.scope,
                            item.sender_id,
                            already_sent,
                            cfg.allow_cancel_after_send,
                        )
                        if state.dispatch_token is not None:
                            state.dispatch_token.cancel()
                        inflight.task.cancel()
                        state.inflight = None
                        state.phase = BatchPhase.TYPING
                        # 新消息追加到现有 items 后面
                        state.items.append(item)
                        self._retokenize_locked(state, item.scope, item.sender_id)
                    elif inflight is None:
                        # inflight 尚未注册（coordinator 还没进入 execute_reply）：
                        # 1) 若 flush task 仍在跑，先 cancel；
                        # 2) 若它已经把请求入队，则取消旧 token，execute_reply 入口会跳过旧请求。
                        logger.info(
                            "[MessageBatcher] inflight 未注册，取消投机 token/flush task: "
                            "scope=%s sender=%s",
                            item.scope,
                            item.sender_id,
                        )
                        if state.dispatch_token is not None:
                            state.dispatch_token.cancel()
                        if state.speculative_flush_task is not None:
                            state.speculative_flush_task.cancel()
                            state.speculative_flush_task = None
                        state.phase = BatchPhase.TYPING
                        state.items.append(item)
                        self._retokenize_locked(state, item.scope, item.sender_id)
                    else:
                        # 已发过消息且不允许取消：丢弃当前桶，新消息开新桶
                        logger.info(
                            "[MessageBatcher] 投机调用已发出消息且不允许取消，新消息开新 batch: "
                            "scope=%s sender=%s",
                            item.scope,
                            item.sender_id,
                        )
                        self._cancel_t1(state)
                        self._cancel_t2(state)
                        state.phase = BatchPhase.FINALIZING
                        # 旧桶让 inflight 自然结束；从 _buckets pop 以释放 key 给新 batch
                        self._buckets.pop(key, None)
                        # 新桶
                        state = _BatchState(
                            phase=BatchPhase.TYPING,
                            first_arrival_monotonic=now_mono,
                            dispatch_token=self._new_token(item.scope, item.sender_id),
                        )
                        self._buckets[key] = state
                        state.items.append(item)
                elif state.phase is BatchPhase.FINALIZING:
                    # 极少见：T1 已到、inflight 未上报但 task 已不可控；当作新桶处理
                    logger.warning(
                        "[MessageBatcher] 桶处于 FINALIZING 期间收到新消息，开新 batch: "
                        "scope=%s sender=%s",
                        item.scope,
                        item.sender_id,
                    )
                    self._buckets.pop(key, None)
                    state = _BatchState(
                        phase=BatchPhase.TYPING,
                        first_arrival_monotonic=now_mono,
                        dispatch_token=self._new_token(item.scope, item.sender_id),
                    )
                    self._buckets[key] = state
                    state.items.append(item)
                else:  # TYPING：直接 append
                    state.items.append(item)

                self._bind_items_to_token_locked(state)

                # === 阶段 2: 重置 T1/T2 timer ===
                self._cancel_t1(state)
                self._cancel_t2(state)

                elapsed = now_mono - state.first_arrival_monotonic
                unlimited_window = cfg.max_window_seconds <= 0
                remaining_max = (
                    float("inf")
                    if unlimited_window
                    else cfg.max_window_seconds - elapsed
                )

                # 硬顶：max_messages_per_batch 立即发车（结束 batch）
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
                    immediate_fire_items = self._pop_locked(key)
                elif not unlimited_window and remaining_max <= 0:
                    logger.info(
                        "[MessageBatcher] 已超 max_window_seconds 硬顶 立即发车: "
                        "scope=%s sender=%s elapsed=%.2fs",
                        item.scope,
                        item.sender_id,
                        elapsed,
                    )
                    immediate_fire_items = self._pop_locked(key)
                else:
                    # T1 delay
                    # fixed：从首条到达时刻起算绝对 T1；extend：每条新消息重置为 window_seconds
                    if cfg.strategy == "fixed":
                        target = state.first_arrival_monotonic + cfg.window_seconds
                        t1_delay = max(0.0, target - now_mono)
                    else:  # extend
                        t1_delay = cfg.window_seconds
                    if not unlimited_window:
                        t1_delay = min(t1_delay, remaining_max)

                    loop = asyncio.get_running_loop()
                    state.t1_handle = loop.call_later(
                        max(0.0, t1_delay), self._on_t1_timer, key
                    )

                    # T2 delay（仅当投机启用，且本桶尚未 pre-fire 时设置）
                    if (
                        self.speculative_enabled
                        and state.phase is BatchPhase.TYPING
                        and cfg.pre_send_seconds < t1_delay
                    ):
                        t2_delay = cfg.pre_send_seconds
                        state.t2_handle = loop.call_later(
                            max(0.0, t2_delay), self._on_t2_timer, key
                        )
                        logger.debug(
                            "[MessageBatcher] 缓冲: scope=%s sender=%s count=%s "
                            "t1=%.2fs t2=%.2fs strategy=%s",
                            item.scope,
                            item.sender_id,
                            len(state.items),
                            t1_delay,
                            t2_delay,
                            cfg.strategy,
                        )
                    else:
                        logger.debug(
                            "[MessageBatcher] 缓冲: scope=%s sender=%s count=%s "
                            "t1=%.2fs strategy=%s phase=%s",
                            item.scope,
                            item.sender_id,
                            len(state.items),
                            t1_delay,
                            cfg.strategy,
                            state.phase.value,
                        )

        # 锁外执行 callback
        if immediate_fire_items is not None:
            success = await self._invoke_callback(immediate_fire_items)
            if success:
                self._flush_failure_counts.pop(key, None)
            else:
                await self._restore_items_after_failed_flush(
                    key, immediate_fire_items, schedule_retry=True
                )

    # ----------------------------------------------------------- inflight API

    def register_inflight(
        self,
        scope: str,
        sender_id: int,
        task: asyncio.Task[Any],
        request_context: Any = None,
    ) -> None:
        """coordinator 在 ``execute_reply`` 开头上报 inflight LLM 任务。

        如果桶不存在或 phase 不是 SPECULATING，则忽略（说明这次 fire 不是投机的）。
        """
        key = (scope, sender_id)
        state = self._buckets.get(key)
        if state is None:
            return
        if state.phase is not BatchPhase.SPECULATING:
            return
        state.inflight = _InflightInfo(task=task, request_context=request_context)
        logger.debug(
            "[MessageBatcher] 注册 inflight 任务: scope=%s sender=%s",
            scope,
            sender_id,
        )

    # 注销 inflight 任务
    def unregister_inflight(
        self, scope: str, sender_id: int, task: asyncio.Task[Any]
    ) -> None:
        """coordinator 在 ``execute_reply`` 结束（含异常/取消）时上报。"""
        key = (scope, sender_id)
        state = self._buckets.get(key)
        if state is None:
            return
        if state.inflight is not None and state.inflight.task is not task:
            logger.debug(
                "[MessageBatcher] 忽略过期 inflight 注销: scope=%s sender=%s phase=%s",
                scope,
                sender_id,
                state.phase.value,
            )
            return
        state.inflight = None
        # 若 phase 是 SPECULATING 且 T1 已经 fire 过（FINALIZING 才 unregister），
        # 此时 inflight 自然结束 → 桶已经在 _on_t1_timer 中弹出，无需再做事
        # 若仍在 SPECULATING（T1 未到）：inflight 已结束但仍可能有新消息进来；
        # 保持 SPECULATING，新消息会按 SPECULATING 分支处理（已发消息开新 batch / 未发追加）
        logger.debug(
            "[MessageBatcher] 注销 inflight 任务: scope=%s sender=%s phase=%s",
            scope,
            sender_id,
            state.phase.value,
        )

    # ---------------------------------------------------------------- timers

    def _cancel_t1(self, state: _BatchState) -> None:
        if state.t1_handle is not None:
            state.t1_handle.cancel()
            state.t1_handle = None

    def _cancel_t2(self, state: _BatchState) -> None:
        if state.t2_handle is not None:
            state.t2_handle.cancel()
            state.t2_handle = None

    def _new_token(self, scope: str, sender_id: int) -> BatchDispatchToken:
        self._next_batch_id += 1
        return BatchDispatchToken(
            scope=scope,
            sender_id=sender_id,
            batch_id=self._next_batch_id,
        )

    def _retokenize_locked(
        self, state: _BatchState, scope: str, sender_id: int
    ) -> None:
        state.dispatch_token = self._new_token(scope, sender_id)
        self._bind_items_to_token_locked(state)

    @staticmethod
    def _bind_items_to_token_locked(state: _BatchState) -> None:
        if state.dispatch_token is None:
            return
        for buffered in state.items:
            buffered.batch_token = state.dispatch_token

    def _pop_locked(self, key: tuple[str, int]) -> list[BufferedMessage] | None:
        state = self._buckets.pop(key, None)
        if state is None or not state.items:
            return None
        self._cancel_t1(state)
        self._cancel_t2(state)
        return list(state.items)

    def _on_t1_timer(self, key: tuple[str, int]) -> None:
        """T1 静默到期：batch 结束。"""
        task = asyncio.create_task(self._handle_t1(key))
        self._pending_tasks.add(task)
        task.add_done_callback(self._pending_tasks.discard)

    def _on_t2_timer(self, key: tuple[str, int]) -> None:
        """T2 静默到期：投机预发送（pre-fire），但 batch 不结束。"""
        task = asyncio.create_task(self._handle_t2(key))
        self._pending_tasks.add(task)
        task.add_done_callback(self._pending_tasks.discard)

    async def _handle_t1(
        self, key: tuple[str, int], *, raise_on_failure: bool = False
    ) -> bool:
        items_to_fire: list[BufferedMessage] | None = None
        wait_inflight: asyncio.Task[Any] | None = None
        wait_prefire: asyncio.Task[Any] | None = None
        finalizing_state: _BatchState | None = None
        async with self._lock:
            state = self._buckets.get(key)
            if state is None:
                return True
            self._cancel_t2(state)
            if state.phase is BatchPhase.SPECULATING:
                # T1 到了，投机请求已经发出/入队；这里只结束 batch，不能再次发车。
                state.phase = BatchPhase.FINALIZING
                finalizing_state = state
                if state.inflight is not None:
                    wait_inflight = state.inflight.task
                elif (
                    state.speculative_flush_task is not None
                    and not state.speculative_flush_task.done()
                ):
                    wait_prefire = state.speculative_flush_task
                else:
                    self._buckets.pop(key, None)
                    logger.debug(
                        "[MessageBatcher] T1 结束已投机 batch，不重复发车: "
                        "scope=%s sender=%s",
                        key[0],
                        key[1],
                    )
            else:
                # 普通模式或 SPECULATING 但 inflight 已结束：直接 fire
                items_to_fire = self._pop_locked(key)
                if items_to_fire is not None:
                    state.phase = BatchPhase.FINALIZING

        wait_task: asyncio.Task[Any] | None = wait_inflight or wait_prefire
        if wait_task is not None:
            try:
                await wait_task
            except asyncio.CancelledError:
                # inflight/prefire 已被 cancel（极少同时发生），让 cancel 路径自然走
                logger.info(
                    "[MessageBatcher] T1 等待投机任务时被取消: scope=%s sender=%s",
                    key[0],
                    key[1],
                )
            except Exception:
                logger.exception(
                    "[MessageBatcher] T1 等待投机任务失败: scope=%s sender=%s",
                    key[0],
                    key[1],
                )
            finally:
                # 仅当桶仍是 finalizing_state（同一对象）时才 pop；
                # 否则 submit 已经在 SPECULATING/FINALIZING 分支把旧桶 pop 并建立新桶，
                # 不能误删新桶。
                async with self._lock:
                    current = self._buckets.get(key)
                    if current is finalizing_state:
                        self._buckets.pop(key, None)
            return True

        if items_to_fire is not None:
            success = await self._invoke_callback(items_to_fire, speculative=False)
            if success:
                self._flush_failure_counts.pop(key, None)
            else:
                await self._restore_items_after_failed_flush(
                    key, items_to_fire, schedule_retry=not self._shutdown
                )
                if raise_on_failure:
                    raise RuntimeError("message batcher flush callback failed")
            return success
        return True

    async def _handle_t2(self, key: tuple[str, int]) -> None:
        speculative_items: list[BufferedMessage] | None = None
        async with self._lock:
            state = self._buckets.get(key)
            if state is None:
                return
            if state.phase is not BatchPhase.TYPING:
                return
            if not state.items:
                return
            # 切到 SPECULATING，但**不**清空 items（保留以便后续 T1 也能用 / 抢占回收）
            state.phase = BatchPhase.SPECULATING
            self._cancel_t2(state)
            if state.dispatch_token is None:
                state.dispatch_token = self._new_token(key[0], key[1])
                self._bind_items_to_token_locked(state)
            state.dispatch_token.speculative = True
            # 记录"承担投机职责"的当前 task；此处指向 _handle_t2 协程本身
            # （pre-fire 协程），不是 LLM inflight task。
            # 后续 submit() 抢占判定通过 `state.speculative_flush_task is asyncio.current_task()`
            # 区分新旧 pre-fire 协程，避免误清理新 batch。
            state.speculative_flush_task = asyncio.current_task()
            speculative_items = list(state.items)
            logger.info(
                "[MessageBatcher] 投机预发送: scope=%s sender=%s count=%s",
                key[0],
                key[1],
                len(speculative_items),
            )

        if speculative_items is not None:
            success = False
            try:
                success = await self._invoke_callback(
                    speculative_items, speculative=True
                )
            finally:
                # 清掉自身引用，避免 state 残留指向已结束 task；若投机 callback
                # 异常/取消且桶仍是本次 SPECULATING，则回滚为 TYPING，等待 T1 正常重试。
                async with self._lock:
                    state2 = self._buckets.get(key)
                    if (
                        state2 is not None
                        and state2.speculative_flush_task is asyncio.current_task()
                    ):
                        state2.speculative_flush_task = None
                        if state2.phase is BatchPhase.SPECULATING and not success:
                            if state2.dispatch_token is not None:
                                state2.dispatch_token.cancel()
                            state2.phase = BatchPhase.TYPING
                            self._retokenize_locked(state2, key[0], key[1])
                            logger.warning(
                                "[MessageBatcher] 投机预发送失败，回滚等待 T1 重试: "
                                "scope=%s sender=%s",
                                key[0],
                                key[1],
                            )

    async def _invoke_callback(
        self,
        items: list[BufferedMessage],
        *,
        speculative: bool = False,
    ) -> bool:
        if not items:
            return True
        first = items[0]
        logger.info(
            "[MessageBatcher] 发车: scope=%s sender=%s count=%s speculative=%s",
            first.scope,
            first.sender_id,
            len(items),
            speculative,
        )
        try:
            await self._flush_callback(items)
            return True
        except asyncio.CancelledError:
            # 投机被新消息取消是预期行为
            logger.info(
                "[MessageBatcher] flush_callback 被取消（投机抢占）: "
                "scope=%s sender=%s speculative=%s",
                first.scope,
                first.sender_id,
                speculative,
            )
            return False
        except Exception:
            logger.exception(
                "[MessageBatcher] flush_callback 异常: scope=%s sender=%s count=%s",
                first.scope,
                first.sender_id,
                len(items),
            )
            return False

    async def _restore_items_after_failed_flush(
        self,
        key: tuple[str, int],
        items: list[BufferedMessage],
        *,
        schedule_retry: bool,
    ) -> None:
        """flush callback 失败后回滚到 TYPING 阶段。

        重试策略（fail-fast）：
        - 每次失败累加 ``self._flush_failure_counts[key]``；
        - 仅在 ``failure_count <= 1``（即首次失败）时安排一次延后 T1 重试；
        - 第二次起仅恢复 batch、等待用户新消息或 ``flush_all`` 触发，
          避免 LLM 端持续故障时形成"无限重试风暴"；
        - 桶在成功一次后 ``failure_count`` 会被 pop 清零。
        - ``flush_all`` 路径会 raise，从而暴露持续失败。
        """
        if not items:
            return
        async with self._lock:
            state = self._buckets.get(key)
            if state is None:
                state = _BatchState(
                    phase=BatchPhase.TYPING,
                    first_arrival_monotonic=time.monotonic(),
                    dispatch_token=self._new_token(key[0], key[1]),
                )
                self._buckets[key] = state
                state.items = list(items)
            else:
                self._cancel_t1(state)
                self._cancel_t2(state)
                state.phase = BatchPhase.TYPING
                state.items = list(items) + state.items
                state.first_arrival_monotonic = time.monotonic()
            state.inflight = None
            if state.dispatch_token is not None:
                state.dispatch_token.cancel()
            self._retokenize_locked(state, key[0], key[1])
            logger.warning(
                "[MessageBatcher] flush 失败，已恢复 batch: scope=%s sender=%s count=%s",
                key[0],
                key[1],
                len(state.items),
            )
            failure_count = self._flush_failure_counts.get(key, 0) + 1
            self._flush_failure_counts[key] = failure_count
            if schedule_retry and not self._shutdown and failure_count <= 1:
                loop = asyncio.get_running_loop()
                delay = max(0.0, self._config.window_seconds)
                state.t1_handle = loop.call_later(delay, self._on_t1_timer, key)

    # ------------------------------------------------------------ shutdown

    async def flush_all(self) -> None:
        """立即 flush 所有 buckets（用于关停）。

        关停时直接对所有桶执行 T1 等价路径并等 inflight 收尾。
        """
        while True:
            async with self._lock:
                self._shutdown = True
                keys = list(self._buckets.keys())
            if not keys:
                break
            logger.info("[MessageBatcher] flush_all: pending_buckets=%s", len(keys))
            for key in keys:
                await self._handle_t1(key, raise_on_failure=True)
        # 等 timer 已触发但回调仍在跑的 task
        pending = [t for t in self._pending_tasks if not t.done()]
        if pending:
            logger.info(
                "[MessageBatcher] flush_all: 等待 %s 个 in-flight flush task",
                len(pending),
            )
            await asyncio.gather(*pending, return_exceptions=True)

    # ------------------------------------------------------------- snapshot

    def snapshot(self) -> dict[str, Any]:
        """返回当前 buckets 状态的非阻塞快照（供 Runtime API / WebUI 展示）。"""
        cfg = self._config
        now_mono = time.monotonic()
        buckets: list[dict[str, Any]] = []
        for (scope, sender_id), state in list(self._buckets.items()):
            buckets.append(
                {
                    "scope": scope,
                    "sender_id": sender_id,
                    "count": len(state.items),
                    "elapsed_seconds": round(
                        max(0.0, now_mono - state.first_arrival_monotonic), 2
                    ),
                    "phase": state.phase.value,
                    "has_inflight": state.inflight is not None,
                    "has_speculative_dispatch": (
                        state.dispatch_token is not None
                        and state.dispatch_token.speculative
                        and not state.dispatch_token.cancelled
                    ),
                }
            )
        return {
            "config": {
                "enabled": cfg.enabled,
                "window_seconds": cfg.window_seconds,
                "pre_send_seconds": cfg.pre_send_seconds,
                "speculative_enabled": self.speculative_enabled,
                "strategy": cfg.strategy,
                "max_window_seconds": cfg.max_window_seconds,
                "max_messages_per_batch": cfg.max_messages_per_batch,
                "group_enabled": cfg.group_enabled,
                "private_enabled": cfg.private_enabled,
                "flush_on_command": cfg.flush_on_command,
                "allow_cancel_after_send": cfg.allow_cancel_after_send,
                "shutdown": self._shutdown,
            },
            "pending_buckets": len(buckets),
            "buckets": buckets,
        }
