"""Deprecated compatibility layer for LLM requests.

This module used to contain the LLM requester implementation. It now lives in
`Undefined.ai.llm`. Keep this module to avoid breaking existing imports.
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

# 常用符号显式导出（避免类型检查/IDE 跳转体验变差）
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
