"""Skills 内部共享助手。

`skills/` 下的 handler 允许依赖本模块（以及同目录的相对导入），用于收敛那些
在每个工具里各写一份的小函数。跨 `skills/` 的公共能力应优先放到这里，而不是
在多个 handler 间复制实现。
"""

from __future__ import annotations

from typing import Any


def private_access_error(
    runtime_config: Any,
    target_id: int,
    *,
    prefix: str = "发送失败：",
) -> str:
    """按访问控制拒绝原因生成统一的用户可见说明。

    读取 `runtime_config.private_access_denied_reason(target_id)`：
    - `blacklist` 表示命中 `access.blocked_private_ids`；
    - 其余情况（含 `allowlist` / 未配置）统一提示不在允许列表内。
    """
    reason_getter = getattr(runtime_config, "private_access_denied_reason", None)
    reason = reason_getter(target_id) if callable(reason_getter) else None
    if reason == "blacklist":
        return (
            f"{prefix}目标用户 {target_id} 在黑名单内（access.blocked_private_ids），"
            "已被访问控制拦截"
        )
    return (
        f"{prefix}目标用户 {target_id} 不在允许列表内（access.allowed_private_ids），"
        "已被访问控制拦截"
    )


def parse_positive_int(
    value: Any,
    field_name: str,
) -> tuple[int | None, str | None]:
    """解析可选正整数字段，返回 `(值, 错误说明)`。

    `None` 表示未提供（返回 `(None, None)`）；非法值返回 `(None, 错误说明)`。
    """
    if value is None:
        return None, None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None, f"{field_name} 必须是整数"
    if parsed <= 0:
        return None, f"{field_name} 必须是正整数"
    return parsed, None


__all__ = ["parse_positive_int", "private_access_error"]
