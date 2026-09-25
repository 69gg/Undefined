"""子命令实现：``up`` / ``down`` / ``status`` / ``logs``。

``cli`` 只负责把参数归一化成普通 dict 后调 :func:`dispatch`，具体流程在这里
按「准备状态 → 渲染 → 写配置 → 调 docker」串起来。每个子命令都保持幂等：
重复执行不换凭据、不覆盖用户手工修改。
"""

from __future__ import annotations

from typing import Any

from Undefined.deploy.catalog import EXIT_ERROR


def dispatch(command: str, options: dict[str, Any]) -> int:
    """按子命令分发；未实现的分支给出明确提示而不是静默成功。"""
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


def run_up(options: dict[str, Any]) -> int:
    del options
    print("错误：deploy up 尚未接线完成。")
    return EXIT_ERROR


def run_down(options: dict[str, Any]) -> int:
    del options
    print("错误：deploy down 尚未接线完成。")
    return EXIT_ERROR


def run_status(options: dict[str, Any]) -> int:
    del options
    print("错误：deploy status 尚未接线完成。")
    return EXIT_ERROR


def run_logs(options: dict[str, Any]) -> int:
    del options
    print("错误：deploy logs 尚未接线完成。")
    return EXIT_ERROR


__all__ = ["dispatch", "run_down", "run_logs", "run_status", "run_up"]
