"""LLM 请求的兼容层（已弃用）。

该模块曾包含 LLM 请求实现，现已迁移到 `Undefined.ai.llm`。
保留此模块用于兼容旧导入路径，避免破坏既有调用。
"""

from __future__ import annotations

import warnings
from typing import Any

from Undefined.ai import llm as _llm

warnings.warn(
    "Undefined.ai.http 已弃用，请改用 Undefined.ai.llm（本模块仅作兼容保留）。",
    DeprecationWarning,
    stacklevel=2,
)

# 常用符号显式导出（避免类型检查/集成开发环境跳转体验变差）
ModelRequester = _llm.ModelRequester
ModelConfig = _llm.ModelConfig
build_request_body = _llm.build_request_body


def __getattr__(name: str) -> Any:  # pragma: no cover
    return getattr(_llm, name)


def __dir__() -> list[str]:  # pragma: no cover
    return sorted(set(globals().keys()) | set(dir(_llm)))


__all__ = getattr(
    _llm, "__all__", ["ModelRequester", "ModelConfig", "build_request_body"]
)
