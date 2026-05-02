"""自动处理管线的共享数据模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Mapping

AutoPipelineTargetType = Literal["group", "private"]
AutoPipelineContext = dict[str, Any]


@dataclass(frozen=True)
class AutoPipelineDetection:
    """单条自动处理管线的命中结果。"""

    name: str
    items: tuple[str, ...]
    metadata: Mapping[str, Any] = field(default_factory=dict)
