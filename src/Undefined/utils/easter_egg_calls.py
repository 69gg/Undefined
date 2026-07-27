"""同轮并行工具调用的彩蛋提示合并。"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Iterable

EASTER_EGG_CALL_BATCH_CONTEXT_KEY = "_easter_egg_call_batch"


def main_call_key(tool_name: str) -> str:
    """返回主 AI 工具或 Agent 调用的批次键。"""

    return f"main:{tool_name}"


def agent_call_key(agent_name: str, tool_name: str) -> str:
    """返回子 Agent 内部工具或 Agent 调用的批次键。"""

    return f"agent:{agent_name}:{tool_name}"


@dataclass(slots=True)
class EasterEggCallBatch:
    """记录同一轮并行调用的次数以及已发送的提示。"""

    counts: dict[str, int]
    announced: set[str] = field(default_factory=set)

    @classmethod
    def from_call_keys(cls, call_keys: Iterable[str]) -> EasterEggCallBatch:
        """按调用键统计当前并行批次。"""

        normalized_keys = (key for key in call_keys if key)
        return cls(counts=dict(Counter(normalized_keys)))

    def format_message(self, call_key: str, message: str) -> str | None:
        """首次调用返回提示文本，重复调用返回 ``None``。"""

        count = self.counts.get(call_key)
        if count is None:
            # 未登记的调用不属于当前并行批次，保持原有逐次提示行为。
            return message
        if call_key in self.announced:
            return None

        # 本方法不包含 await；同一事件循环内并发任务不会在检查与写入间切换。
        self.announced.add(call_key)
        return f"{message} x{count}" if count > 1 else message


def prepare_easter_egg_call_batch(
    context: dict[str, Any], call_keys: Iterable[str]
) -> None:
    """在执行上下文中安装当前一轮并行调用的共享统计。"""

    context[EASTER_EGG_CALL_BATCH_CONTEXT_KEY] = EasterEggCallBatch.from_call_keys(
        call_keys
    )


def format_batched_easter_egg_message(
    context: dict[str, Any], *, call_key: str, message: str
) -> str | None:
    """根据当前并行批次合并重复彩蛋提示。"""

    batch = context.get(EASTER_EGG_CALL_BATCH_CONTEXT_KEY)
    if not isinstance(batch, EasterEggCallBatch):
        return message
    return batch.format_message(call_key, message)
