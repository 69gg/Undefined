"""同 sender 短时多消息合并器（MessageBatcher）。

核心目标：把同一个 sender 在短时间内连续发出的消息合并到同一轮 AI 调用，
让模型一次看到全部 ``<message>`` 块自行决定 "独立请求 / 修正 / 打断"，
避免 N 条独立 LLM 调用造成的重复回复或行为打架。

时序：每个 (scope, sender_id) 桶内有两条独立的"静默计时器"：

- ``T1 = window_seconds`` —— "打字静默阈值"。静默达到 T1 视为用户写完，
  这一批 batch 结束。
- ``T2 = pre_send_seconds`` —— "投机预发送阈值"，要求严格小于 T1。
  静默到 T2 时**先把当前 batch 提前发给 LLM 抢时间**（speculative pre-fire），
  但 batch 尚未结束；T1 才决定结束。

新消息到来：

- 若桶处于 ``TYPING``（尚未 pre-fire）：append 后重置 T1/T2。
- 若桶处于 ``SPECULATING``（已 pre-fire，inflight 在跑）：
  - 检查 inflight 是否已经 "向用户发出过任何消息"
    （来自 ``RequestContext.get_resource("message_sent_this_turn")``）。
  - inflight 尚未发消息 → 调 ``inflight_task.cancel()``，桶回到 TYPING；
    新消息照常 append 到原有 items 后面，T1/T2 重置。
  - inflight 已经发过消息且 ``allow_cancel_after_send=False``（默认安全）→
    保留旧 batch 让其自然走完，新消息开新 batch（即清空当前桶后立即重新作为首条入桶）。
  - inflight 已经发过消息但开关 = True → 仍 cancel（可能造成重复发送，仅极端场景）。

兼容回退：当 ``pre_send_seconds <= 0`` 或 ``>= window_seconds`` 时投机模式关闭，
退化为旧版 "T1 静默到期才发车" 的行为。
"""

from __future__ import annotations

import asyncio
import enum
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
"""``flush_callback(items)``：batcher 决定 fire 时调用，调用方负责拼装 prompt 并入队执行。

调用约定：
- batcher 的 ``flush_callback`` **不应** 立即 await LLM 的完成，
  而是把请求扔进 QueueManager 后立即返回，真正的 LLM 任务由 coordinator 在 ``execute_reply``
  开头调用 :meth:`MessageBatcher.register_inflight` 上报。
- 若需要 batcher 关停时也等待 in-flight 收尾，由 :meth:`MessageBatcher.flush_all` 处理。
"""


class BatchPhase(enum.Enum):
    """桶状态机。"""

    TYPING = "typing"  # 等待 T1/T2 静默
    SPECULATING = "speculating"  # T2 已触发，inflight LLM 在跑；T1 仍未到
    FINALIZING = "finalizing"  # T1 已到，等 inflight（若有）自然结束


@dataclass
class _InflightInfo:
    """inflight LLM 任务关联信息，由 coordinator 通过 ``register_inflight`` 上报。"""

    task: asyncio.Task[Any]
    # ``RequestContext`` 引用，用于判断 ``message_sent_this_turn`` 资源
    request_context: Any = None


@dataclass
class _BatchState:
    """单个 (scope, sender_id) 桶的状态。"""

    phase: BatchPhase = BatchPhase.TYPING
    items: list[BufferedMessage] = field(default_factory=list)
    first_arrival_monotonic: float = 0.0
    # T1 = window_seconds 静默 timer（决定 batch 结束）
    t1_handle: asyncio.TimerHandle | None = None
    # T2 = pre_send_seconds 静默 timer（决定 pre-fire）；投机关闭时为 None
    t2_handle: asyncio.TimerHandle | None = None
    # SPECULATING 阶段记录 inflight LLM 任务
    inflight: _InflightInfo | None = None


def make_scope(*, group_id: int | None = None, user_id: int | None = None) -> str:
    """构造合并 key 的 scope 字符串。"""
    if group_id and group_id > 0:
        return f"group:{group_id}"
    if user_id is not None:
        return f"private:{user_id}"
    return "unknown"


def _was_message_sent_this_turn(ctx: Any) -> bool:
    """判断 inflight RequestContext 是否已经向用户发出过任何消息。

    与 ``skills/tools/end/handler.py::_was_message_sent_this_turn`` 同语义；
    这里采用宽松布尔解析。
    """
    if ctx is None:
        return False
    try:
        value = ctx.get_resource("message_sent_this_turn", False)
    except Exception:  # noqa: BLE001 - ctx 可能已失效
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return False


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
        self._lock = asyncio.Lock()
        # 持有 timer 触发后创建的 flush task 强引用，避免被 GC（asyncio 文档要求）
        self._pending_tasks: set[asyncio.Task[None]] = set()

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

    def has_buffer(self, scope: str, sender_id: int) -> bool:
        return (scope, sender_id) in self._buckets

    @property
    def speculative_enabled(self) -> bool:
        cfg = self._config
        return 0 < cfg.pre_send_seconds < cfg.window_seconds

    async def submit(self, item: BufferedMessage) -> None:
        """提交一条消息进入合并桶。

        新消息到来时的处理依赖当前桶 ``phase``，详见模块 docstring。
        """
        cfg = self._config
        key = (item.scope, item.sender_id)
        # 异步路径里只在锁内修改桶；invoke callback 在锁外执行
        speculative_fire_items: list[BufferedMessage] | None = None
        immediate_fire_items: list[BufferedMessage] | None = None

        async with self._lock:
            state = self._buckets.get(key)
            now_mono = time.monotonic()

            # === 阶段 1: 决定本条消息怎么进桶 ===
            if state is None:
                # 全新桶
                state = _BatchState(
                    phase=BatchPhase.TYPING,
                    first_arrival_monotonic=now_mono,
                )
                self._buckets[key] = state
                state.items.append(item)
            elif state.phase is BatchPhase.SPECULATING:
                # 已 pre-fire，决定是否 cancel inflight
                inflight = state.inflight
                already_sent = (
                    _was_message_sent_this_turn(inflight.request_context)
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
                    inflight.task.cancel()
                    state.inflight = None
                    state.phase = BatchPhase.TYPING
                    # 新消息追加到现有 items 后面
                    state.items.append(item)
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
                )
                self._buckets[key] = state
                state.items.append(item)
            else:  # TYPING：直接 append
                state.items.append(item)

            # === 阶段 2: 重置 T1/T2 timer ===
            self._cancel_t1(state)
            self._cancel_t2(state)

            elapsed = now_mono - state.first_arrival_monotonic
            unlimited_window = cfg.max_window_seconds <= 0
            remaining_max = (
                float("inf") if unlimited_window else cfg.max_window_seconds - elapsed
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
                if self.speculative_enabled and state.phase is BatchPhase.TYPING:
                    t2_delay = min(cfg.pre_send_seconds, t1_delay)
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
            await self._invoke_callback(immediate_fire_items)
        elif speculative_fire_items is not None:  # 此分支当前不会触发，预留扩展
            await self._invoke_callback(speculative_fire_items)

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

    def unregister_inflight(self, scope: str, sender_id: int) -> None:
        """coordinator 在 ``execute_reply`` 结束（含异常/取消）时上报。"""
        key = (scope, sender_id)
        state = self._buckets.get(key)
        if state is None:
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

    async def _handle_t1(self, key: tuple[str, int]) -> None:
        items_to_fire: list[BufferedMessage] | None = None
        wait_inflight: asyncio.Task[Any] | None = None
        finalizing_state: _BatchState | None = None
        async with self._lock:
            state = self._buckets.get(key)
            if state is None:
                return
            self._cancel_t2(state)
            if state.phase is BatchPhase.SPECULATING and state.inflight is not None:
                # T1 到了但投机调用还在跑：等它完成，桶状态切到 FINALIZING
                state.phase = BatchPhase.FINALIZING
                wait_inflight = state.inflight.task
                finalizing_state = state
                # 桶将在 inflight 结束后清理
            else:
                # 普通模式或 SPECULATING 但 inflight 已结束：直接 fire
                items_to_fire = self._pop_locked(key)
                if items_to_fire is not None:
                    state.phase = BatchPhase.FINALIZING

        if wait_inflight is not None:
            try:
                await wait_inflight
            except asyncio.CancelledError:
                # inflight 已被 cancel（极少同时发生），让 cancel 路径自然走
                logger.info(
                    "[MessageBatcher] T1 等待 inflight 时被取消: scope=%s sender=%s",
                    key[0],
                    key[1],
                )
            except Exception:
                logger.exception(
                    "[MessageBatcher] T1 等待 inflight 失败: scope=%s sender=%s",
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
            return

        if items_to_fire is not None:
            await self._invoke_callback(items_to_fire, speculative=False)

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
            speculative_items = list(state.items)
            logger.info(
                "[MessageBatcher] 投机预发送: scope=%s sender=%s count=%s",
                key[0],
                key[1],
                len(speculative_items),
            )

        if speculative_items is not None:
            await self._invoke_callback(speculative_items, speculative=True)

    async def _invoke_callback(
        self,
        items: list[BufferedMessage],
        *,
        speculative: bool = False,
    ) -> None:
        if not items:
            return
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
        except asyncio.CancelledError:
            # 投机被新消息取消是预期行为
            logger.info(
                "[MessageBatcher] flush_callback 被取消（投机抢占）: "
                "scope=%s sender=%s speculative=%s",
                first.scope,
                first.sender_id,
                speculative,
            )
        except Exception:
            logger.exception(
                "[MessageBatcher] flush_callback 异常: scope=%s sender=%s count=%s",
                first.scope,
                first.sender_id,
                len(items),
            )

    # ------------------------------------------------------------ shutdown

    async def flush_all(self) -> None:
        """立即 flush 所有 buckets（用于关停）。

        关停时直接对所有桶执行 T1 等价路径并等 inflight 收尾。
        """
        async with self._lock:
            keys = list(self._buckets.keys())
        if keys:
            logger.info("[MessageBatcher] flush_all: pending_buckets=%s", len(keys))
            for key in keys:
                await self._handle_t1(key)
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
                "allow_cancel_after_send": cfg.allow_cancel_after_send,
            },
            "pending_buckets": len(buckets),
            "buckets": buckets,
        }
