"""响应解析工具。

提供从 AI API 响应中提取内容的辅助函数。
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _get_content_from_message(message: Any) -> str | None:
    """从 OpenAI 风格的 message 对象中提取 content 字符串"""
    if message is None:
        return None
    if isinstance(message, str):
        return message
    if isinstance(message, dict):
        return message.get("content")
    return None


def _extract_from_choice(choice: Any) -> str:
    """从单个 choice 结构中提取最终的文本内容"""
    # 如果 choice 是字符串，直接返回
    if isinstance(choice, str):
        return choice

    # 如果 choice 不是字典，返回空字符串
    if not isinstance(choice, dict):
        return ""

    # 尝试从 message 中获取 content
    message = choice.get("message")
    content = _get_content_from_message(message)

    # 如果 message 中没有 content，尝试从 choice 直接获取
    if content is None:
        content = choice.get("content")

    # 如果有 tool_calls 但没有 content，返回空字符串
    if not content and choice.get("message", {}).get("tool_calls"):
        return ""

    return content or ""


def _find_first_choice(result: dict[str, Any]) -> dict[str, Any] | None:
    """在响应中查找第一个 choice。

    支持两种格式：
    1. {"choices": [...]}
    2. {"data": {"choices": [...]}}

    Args:
        result: API 响应字典

    Returns:
        第一个 choice 字典，未找到时返回 None
    """
    # 直接检查 choices 字段
    if "choices" in result and result["choices"]:
        choice = result["choices"][0]
        if isinstance(choice, dict):
            return choice

    # 检查 data.choices 字段
    data = result.get("data")
    if isinstance(data, dict) and data.get("choices"):
        choice = data["choices"][0]
        if isinstance(choice, dict):
            return choice

    return None


def _build_error_message(result: dict[str, Any]) -> str:
    """构建包含响应结构详情的错误提示消息

    参数:
        result: API 响应字典
    """
    keys = list(result.keys())
    data = result.get("data")
    if isinstance(data, dict):
        data_keys = list(data.keys())
    else:
        data_keys = ["N/A"]

    return (
        "无法从 API 响应中提取 choices 内容。"
        f"响应结构: {keys}, "
        f"data 键结构: {data_keys}"
    )


def extract_choices_content(result: dict[str, Any]) -> str:
    """从 API 响应中提取 choices 内容。

    支持的响应格式：
    1. {"choices": [{"message": {"content": "..."}}]}
    2. {"data": {"choices": [{"message": {"content": "..."}}]}}

    Args:
        result: API 响应字典

    Returns:
        提取的内容字符串

    Raises:
        KeyError: 当无法从响应中提取内容时
    """
    logger.debug(f"提取 choices 内容，响应结构: {list(result.keys())}")

    # 查找第一个 choice
    choice = _find_first_choice(result)

    # 如果没有找到 choice，抛出错误
    if choice is None:
        raise KeyError(_build_error_message(result))

    # 从 choice 中提取内容
    return _extract_from_choice(choice)
