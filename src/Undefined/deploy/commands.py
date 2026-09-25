"""子命令分发：把 ``cli`` 归一化后的参数交给 ``runner`` 执行。"""

from __future__ import annotations

from typing import Any

from Undefined.deploy.catalog import EXIT_ERROR
from Undefined.deploy.runner import run_down, run_logs, run_status, run_up


def dispatch(command: str, options: dict[str, Any]) -> int:
    """按子命令分发；未知子命令给出明确提示而不是静默成功。"""
    handlers = {
        "up": run_up,
        "down": run_down,
        "status": run_status,
        "logs": run_logs,
    }
    handler = handlers.get(command)
    if handler is None:
        print(f"错误：未知子命令 {command!r}")
        return EXIT_ERROR
    return handler(options)


__all__ = ["dispatch"]
