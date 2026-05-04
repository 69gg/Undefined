"""Type-safe coercion helpers shared across the codebase."""

from __future__ import annotations

from typing import Any, overload

# 宽松布尔识别（与 end 工具、batcher 共享语义）。
_TRUTHY_TOKENS: frozenset[str] = frozenset({"1", "true", "yes", "y", "on"})
_FALSY_TOKENS: frozenset[str] = frozenset({"0", "false", "no", "n", "off", ""})


@overload
def safe_int(value: Any) -> int | None: ...


@overload
def safe_int(value: Any, default: int) -> int: ...


@overload
def safe_int(value: Any, default: None) -> int | None: ...


def safe_int(value: Any, default: int | None = None) -> int | None:
    """Safely convert *value* to int, returning *default* on failure."""
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def safe_float(value: Any, default: float = 0.0) -> float:
    """Safely convert *value* to float, returning *default* on failure."""
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def coerce_truthy(value: Any) -> tuple[bool, bool]:
    """Loose-truthy parser shared by end tool / message batcher.

    返回 ``(parsed, recognized)``：
    - ``parsed``  — 解析结果（识别失败时按 False 兜底）；
    - ``recognized`` — 是否成功识别（用于调用方决定是否记日志告警）。

    支持：bool、int（0=False / 其余 True）、字符串 ``1/true/yes/y/on``
    与 ``0/false/no/n/off`` / 空串。
    """
    if isinstance(value, bool):
        return value, True
    if isinstance(value, int):
        return value != 0, True
    if isinstance(value, str):
        token = value.strip().lower()
        if token in _TRUTHY_TOKENS:
            return True, True
        if token in _FALSY_TOKENS:
            return False, True
    return False, False


def is_truthy(value: Any) -> bool:
    """``coerce_truthy`` 的便捷封装，仅返回布尔结果。

    传入 None / 不可识别的类型一律按 False 处理。
    """
    parsed, _recognized = coerce_truthy(value)
    return parsed


def was_message_sent(source: Any) -> bool:
    """统一判断"本轮是否已经向用户发送过消息"。

    ``source`` 可以是 ``RequestContext``（提供 ``get_resource``）或 dict。
    任意异常或缺字段都按 False 兜底。
    """
    if source is None:
        return False
    # dict / 自定义 mapping 优先
    if isinstance(source, dict):
        return is_truthy(source.get("message_sent_this_turn", False))
    getter = getattr(source, "get_resource", None)
    if callable(getter):
        try:
            return is_truthy(getter("message_sent_this_turn", False))
        except Exception:  # noqa: BLE001 - context 可能已失效
            return False
    return False
