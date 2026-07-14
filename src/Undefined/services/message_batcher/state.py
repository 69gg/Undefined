"""MessageBatcher 数据模型与 scope 工具。"""

from __future__ import annotations

# 同 sender 短时合并：T1 结束 batch，T2 投机预发送

import asyncio
import enum
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable


@dataclass
class BatchDispatchToken:
    """一次 batch 发车的身份令牌，用于取消已入队但尚未执行的投机请求。"""

    scope: str
    sender_id: int
    batch_id: int
    speculative: bool = False
    cancelled: bool = False

    def cancel(self) -> None:
        self.cancelled = True


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
    trigger_message_id: int | str | None = None
    channel: str = "qq"
    address: str = ""
    is_poke: bool = False
    is_at_bot: bool = False
    is_fake_at: bool = False
    # 群聊扩展字段
    group_id: int | None = None
    group_name: str = ""
    sender_role: str = "member"
    sender_title: str = ""
    sender_level: str = ""
    batch_token: BatchDispatchToken | None = None


FlushCallback = Callable[[list[BufferedMessage]], Awaitable[None]]
"""``flush_callback(items)``：batcher 决定 fire 时调用，调用方负责拼装 prompt 并入队执行。

调用约定：
- batcher 的 ``flush_callback`` **不应** 立即 await LLM 的完成，
  而是把请求扔进 QueueManager 后立即返回，真正的 LLM 任务由 coordinator 在 ``execute_reply``
  开头调用 :meth:`MessageBatcher.register_inflight` 上报。
- 若需要 batcher 关停时也等待 in-flight 收尾，由 :meth:`MessageBatcher.flush_all` 处理。
"""


class BatchPhase(enum.Enum):
    """桶状态机：TYPING → SPECULATING(可选) → FINALIZING。"""

    TYPING = "typing"  # 等待 T1/T2 静默，用户仍在输入
    SPECULATING = "speculating"  # T2 已触发投机 pre-fire，T1 未到，batch 未结束
    FINALIZING = "finalizing"  # T1 已到，等待 inflight 自然结束后再释放桶


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
    # SPECULATING 阶段记录 inflight LLM 任务（由 coordinator 通过 register_inflight 注入）
    inflight: _InflightInfo | None = None
    # T2 fire 时由 batcher 创建的 flush task；inflight 还未上报前用于兜底取消
    speculative_flush_task: asyncio.Task[Any] | None = None
    # 当前 batch 的身份令牌；T2 入队后若又来新消息，可将旧 token 标记取消，
    # coordinator 在真正执行前会跳过它。
    dispatch_token: BatchDispatchToken | None = None


def make_scope(*, group_id: int | None = None, user_id: int | None = None) -> str:
    """构造合并 key 的 scope 字符串。"""
    if group_id and group_id > 0:
        return f"group:{group_id}"
    if user_id is not None:
        return f"private:{user_id}"
    return "unknown"
