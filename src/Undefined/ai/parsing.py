"""Response parsing utilities."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def extract_choices_content(result: dict[str, Any]) -> str:
    """从 API 响应中提取 choices 内容。

    支持两种格式：
    1. {"choices": [...]}
    2. {"data": {"choices": [...]}}
    """
    logger.debug(f"提取 choices 内容，响应结构: {list(result.keys())}")

    def _extract_from_choice(choice: Any) -> str:
        if isinstance(choice, str):
            return choice
        if not isinstance(choice, dict):
            return ""
        message = choice.get("message")
        content: str | None
        if message is None:
            content = choice.get("content")
        elif isinstance(message, str):
            content = message
        elif isinstance(message, dict):
            content = message.get("content")
        else:
            content = None

        if not content and choice.get("message", {}).get("tool_calls"):
            return ""
        return content or ""

    if "choices" in result and result["choices"]:
        return _extract_from_choice(result["choices"][0])

    data = result.get("data")
    if isinstance(data, dict) and data.get("choices"):
        return _extract_from_choice(data["choices"][0])

    raise KeyError(
        "无法从 API 响应中提取 choices 内容。"
        f"响应结构: {list(result.keys())}, "
        f"data 键结构: {list(result.get('data', {}).keys()) if isinstance(result.get('data'), dict) else 'N/A'}"
    )
