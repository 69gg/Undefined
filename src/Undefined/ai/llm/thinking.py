"""思维链（CoT）提取与 thinking 参数规范化。

从 Chat Completions / Responses 响应中抽取 reasoning 字段，并将配置中的
thinking 覆盖值归一化为各上游兼容格式；不负责发送请求。
"""

from __future__ import annotations

from typing import Any

from Undefined.ai.llm.types import ModelConfig

_THINKING_KEYS: tuple[str, ...] = (
    "thinking",
    "reasoning",
    "reasoning_content",
    "chain_of_thought",
    "cot",
    "thoughts",
)


def _stringify_thinking_list(value: list[Any]) -> str:
    """将列表类型的思维链转换为字符串。

    Args:
        value: 思维链列表

    Returns:
        格式化后的字符串
    """
    parts = [stringify_thinking(item) for item in value]
    return "\n".join([part for part in parts if part])


def _stringify_thinking_dict(value: dict[str, Any]) -> str:
    """将字典类型的思维链转换为字符串。

    Args:
        value: 思维链字典

    Returns:
        格式化后的字符串
    """
    content = value.get("content")
    if isinstance(content, str) and content:
        return content
    return str(value)


def stringify_thinking(value: Any) -> str:
    """将思维链值转换为字符串。

    Args:
        value: 思维链值（可以是 None、字符串、列表或字典）

    Returns:
        格式化后的字符串
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return _stringify_thinking_list(value)
    if isinstance(value, dict):
        return _stringify_thinking_dict(value)
    return str(value)


def _extract_from_message(message: dict[str, Any]) -> str:
    """从 message 对象中提取思维链内容。

    Args:
        message: message 对象

    Returns:
        思维链内容字符串
    """
    if not isinstance(message, dict):
        return ""
    for key in _THINKING_KEYS:
        if key in message:
            return stringify_thinking(message.get(key))
    return ""


def _extract_from_choice(choice: dict[str, Any]) -> str:
    """从 choice 对象中提取思维链内容。

    Args:
        choice: choice 对象

    Returns:
        思维链内容字符串
    """
    if not isinstance(choice, dict):
        return ""

    # 优先从 message 中提取
    message = choice.get("message")
    if isinstance(message, dict):
        thinking = _extract_from_message(message)
        if thinking:
            return thinking

    # 尝试从 choice 直接提取
    for key in _THINKING_KEYS:
        if key in choice:
            return stringify_thinking(choice.get(key))

    return ""


def _extract_from_choices(choices: list[Any]) -> str:
    """从 choices 列表中提取思维链内容。

    Args:
        choices: choices 列表

    Returns:
        思维链内容字符串
    """
    if not isinstance(choices, list) or not choices:
        return ""
    choice = choices[0]
    return _extract_from_choice(choice)


def _extract_from_result(result: dict[str, Any]) -> str:
    """直接从结果对象中提取思维链内容。

    Args:
        result: API 响应结果

    Returns:
        思维链内容字符串
    """
    for key in _THINKING_KEYS:
        if key in result:
            return stringify_thinking(result.get(key))
    return ""


def extract_thinking_content(result: dict[str, Any]) -> str:
    """从 API 响应中提取思维链内容。

    提取优先级：
    1. 从 choices[0].message 中提取
    2. 从 choices[0] 直接提取
    3. 从响应根对象中提取

    Args:
        result: API 响应结果

    Returns:
        思维链内容字符串
    """
    # 尝试从 choices 中提取
    choices = result.get("choices")
    if isinstance(choices, list):
        thinking = _extract_from_choices(choices)
        if thinking:
            return thinking

    return _extract_from_result(result)


def _is_deepseek_provider(model_config: ModelConfig) -> bool:
    model_name = str(getattr(model_config, "model_name", "") or "").lower()
    if model_name.startswith("deepseek"):
        return True
    api_url = str(getattr(model_config, "api_url", "") or "").lower()
    return "deepseek" in api_url


def normalize_thinking_override(
    value: Any, model_config: ModelConfig
) -> dict[str, Any] | None:
    """将 request 覆盖中的 thinking 值归一化为上游可接受的 dict。"""
    if value is None:
        return None

    is_deepseek = _is_deepseek_provider(model_config)

    if isinstance(value, dict):
        raw_type = value.get("type")
        if isinstance(raw_type, str):
            type_value = raw_type.strip().lower()
            if type_value in {"enabled", "disabled"}:
                # DeepSeek 仅接受 {type: enabled|disabled}，其它字段原样透传
                return {"type": type_value} if is_deepseek else dict(value)

        raw_enabled = value.get("enabled")
        if isinstance(raw_enabled, bool):
            type_value = "enabled" if raw_enabled else "disabled"
            if is_deepseek:
                return {"type": type_value}
            normalized = dict(value)
            normalized.pop("enabled", None)
            normalized["type"] = type_value
            return normalized

        return None

    if isinstance(value, bool):
        return {"type": "enabled" if value else "disabled"}

    if isinstance(value, str):
        type_value = value.strip().lower()
        if type_value in {"enabled", "disabled"}:
            return {"type": type_value}

    return None
