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
- 若桶处于 ``SPECULATING``（已 pre-fire，请求已入队或 inflight 在跑）：
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

# 同 sender 短时合并：T1 结束 batch，T2 投机预发送
from Undefined.services.message_batcher.scheduler import MessageBatcher
from Undefined.services.message_batcher.state import (
    BatchDispatchToken,
    BatchPhase,
    BufferedMessage,
    FlushCallback,
    make_scope,
)

__all__ = [
    "BatchDispatchToken",
    "BatchPhase",
    "BufferedMessage",
    "FlushCallback",
    "MessageBatcher",
    "make_scope",
]
