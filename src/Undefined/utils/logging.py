"""日志辅助工具。

提供敏感信息脱敏和数据清洗功能，用于安全地记录日志。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

# 敏感关键字列表
_SENSITIVE_KEYWORDS: tuple[str, ...] = (
    "authorization",
    "api_key",
    "apikey",
    "access_token",
    "refresh_token",
    "id_token",
    "token",
    "secret",
    "password",
    "onebot_token",
)

# 敏感信息正则表达式
_BEARER_RE = re.compile(r"(Bearer\s+)[A-Za-z0-9._~+/=-]+", re.IGNORECASE)
_KV_TOKEN_RE = re.compile(
    r"(?i)(api_key|apikey|access_token|refresh_token|id_token|token|secret|password)"
    r"(\s*[:=]\s*)(['\"]?)([^'\"\s]+)"
)
_SK_RE = re.compile(r"\bsk-[A-Za-z0-9]{8,}\b")


def _is_sensitive_key(key: str) -> bool:
    """检查键名是否包含敏感关键字。

    Args:
        key: 键名

    Returns:
        如果包含敏感关键字返回 True，否则返回 False
    """
    lowered = key.lower()
    for keyword in _SENSITIVE_KEYWORDS:
        if keyword in lowered:
            return True
    return False


def redact_string(text: str) -> str:
    """对字符串中的敏感信息进行脱敏处理。

    脱敏规则：
    1. Bearer token: Bearer sk-xxx -> Bearer ***
    2. 键值对 token: api_key=xxx -> api_key=***
    3. SK 开头的 token: sk-xxx -> sk-***

    Args:
        text: 待脱敏的字符串

    Returns:
        脱敏后的字符串
    """
    if not text:
        return text
    masked = _BEARER_RE.sub(r"\\1***", text)
    masked = _KV_TOKEN_RE.sub(r"\\1\\2\\3***", masked)
    masked = _SK_RE.sub("sk-***", masked)
    return masked


def _sanitize_dict(payload: dict[str, Any]) -> dict[str, Any]:
    """对字典进行脱敏处理。

    Args:
        payload: 待脱敏的字典

    Returns:
        脱敏后的字典
    """
    sanitized: dict[str, Any] = {}
    for key, value in payload.items():
        key_str = str(key)
        if _is_sensitive_key(key_str):
            sanitized[key_str] = "***"
        else:
            sanitized[key_str] = sanitize_data(value)
    return sanitized


def _sanitize_sequence(
    payload: list[Any] | tuple[Any, ...],
) -> list[Any] | tuple[Any, ...]:
    """对序列（列表或元组）进行脱敏处理。

    Args:
        payload: 待脱敏的序列

    Returns:
        脱敏后的序列（保持原类型）
    """
    if isinstance(payload, list):
        return [sanitize_data(item) for item in payload]
    return tuple(sanitize_data(item) for item in payload)


def sanitize_data(payload: Any) -> Any:
    """递归清洗数据以避免在日志中泄露敏感信息。

    支持的数据类型：
    - dict: 对敏感键的值进行脱敏
    - list/tuple/set: 递归处理每个元素
    - str: 对敏感模式进行脱敏
    - 其他类型: 原样返回

    Args:
        payload: 待清洗的数据

    Returns:
        清洗后的数据
    """
    if isinstance(payload, dict):
        return _sanitize_dict(payload)
    if isinstance(payload, (list, tuple)):
        return _sanitize_sequence(payload)
    if isinstance(payload, set):
        return {sanitize_data(item) for item in payload}
    if isinstance(payload, str):
        return redact_string(payload)
    return payload


def _serialize_json(payload: Any) -> str:
    """将数据序列化为 JSON 字符串，失败时返回字符串表示。

    Args:
        payload: 待序列化的数据

    Returns:
        JSON 字符串或字符串表示
    """
    try:
        return json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    except (TypeError, ValueError):
        return str(payload)


def log_debug_json(logger: logging.Logger, prefix: str, payload: Any) -> None:
    """在 DEBUG 级别记录 JSON 载荷。

    记录前会先对数据进行脱敏处理。如果序列化失败，会回退到字符串表示。

    Args:
        logger: 日志记录器
        prefix: 日志前缀
        payload: 待记录的数据
    """
    if not logger.isEnabledFor(logging.DEBUG):
        return
    safe_payload = sanitize_data(payload)
    dumped = _serialize_json(safe_payload)
    logger.debug("%s\n%s", prefix, dumped)


def format_log_payload(payload: Any, max_length: int = 2000) -> str:
    """格式化载荷用于信息日志，支持脱敏和截断。

    Args:
        payload: 待格式化的数据
        max_length: 最大长度，超过会截断（0 表示不截断）

    Returns:
        格式化后的字符串
    """
    safe_payload = sanitize_data(payload)
    dumped = _serialize_json(safe_payload)
    if max_length > 0 and len(dumped) > max_length:
        return dumped[:max_length] + "...(truncated)"
    return dumped
