from __future__ import annotations

import asyncio
import logging
from fnmatch import fnmatch
from typing import Any

logger = logging.getLogger(__name__)


def _is_command_blacklisted(command: str, blacklist: list[str]) -> bool:
    """检查命令是否匹配黑名单模式。"""
    for pattern in blacklist:
        if fnmatch(command, pattern) or pattern in command:
            return True
    return False


async def execute(args: dict[str, Any], context: dict[str, Any]) -> str:
    """在 Docker 容器内执行 bash 命令。支持前台/后台执行和进程终止。"""

    action = str(args.get("action", "run")).strip().lower()

    container_name: str | None = context.get("container_name")
    if not container_name:
        return "错误：容器未启动"

    config = context.get("config")
    default_timeout: int = 600
    max_output: int = 20000
    command_blacklist: list[str] = []
    if config:
        default_timeout = getattr(config, "code_delivery_command_timeout", 600)
        max_output = getattr(config, "code_delivery_max_command_output", 20000)
        command_blacklist = getattr(config, "code_delivery_command_blacklist", [])

    if action == "kill":
        # 终止后台进程
        pid = args.get("pid")
        if pid is None:
            return "错误：kill 操作需要 pid 参数"

        pid = int(pid)
        kill_cmd = ["docker", "exec", container_name, "bash", "-lc", f"kill -9 {pid}"]

        try:
            proc = await asyncio.create_subprocess_exec(
                *kill_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=10)

            if proc.returncode == 0:
                return f"已终止进程: {pid}"
            else:
                stderr = stderr_b.decode("utf-8", errors="replace")
                return f"终止进程失败: {stderr or '进程可能不存在'}"
        except Exception as exc:
            logger.exception("终止进程失败: %s", pid)
            return f"终止进程失败: {exc}"

    # action == "run"
    command = str(args.get("command", "")).strip()
    if not command:
        return "错误：command 不能为空"

    # 检查命令黑名单
    if command_blacklist and _is_command_blacklisted(command, command_blacklist):
        return f"错误：命令被黑名单拒绝: {command}"

    timeout = int(args.get("timeout_seconds", 0)) or default_timeout
    workdir = str(args.get("workdir", "")).strip() or "/workspace"
    background = bool(args.get("background", False))

    if background:
        # 后台执行：使用 nohup 并获取进程ID
        bg_cmd = f"nohup bash -lc {repr(command)} > /tmpfs/bg_$$.log 2>&1 & echo $!"
        docker_cmd = [
            "docker",
            "exec",
            "-w",
            workdir,
            container_name,
            "bash",
            "-c",
            bg_cmd,
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *docker_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=10)

            if proc.returncode == 0:
                pid = stdout_b.decode("utf-8", errors="replace").strip()
                return f"后台进程已启动\nPID: {pid}\n日志: /tmpfs/bg_{pid}.log\n\n使用 action=kill, pid={pid} 来终止进程"
            else:
                stderr = stderr_b.decode("utf-8", errors="replace")
                return f"启动后台进程失败: {stderr}"
        except Exception as exc:
            logger.exception("启动后台进程失败: %s", command)
            return f"启动后台进程失败: {exc}"

    # 前台执行（原有逻辑）
    docker_cmd = [
        "docker",
        "exec",
        "-w",
        workdir,
        container_name,
        "bash",
        "-lc",
        command,
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *docker_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        if timeout > 0:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
        else:
            # timeout <= 0 表示不限时
            stdout_bytes, stderr_bytes = await proc.communicate()
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except Exception:
            pass
        return f"命令超时（{timeout}s）: {command}"
    except Exception as exc:
        logger.exception("执行命令失败: %s", command)
        return f"执行命令失败: {exc}"

    stdout = stdout_bytes.decode("utf-8", errors="replace")
    stderr = stderr_bytes.decode("utf-8", errors="replace")
    exit_code = proc.returncode

    # 截断输出
    if len(stdout) > max_output:
        stdout = (
            stdout[:max_output] + f"\n... (stdout 已截断，共 {len(stdout_bytes)} 字节)"
        )
    if len(stderr) > max_output:
        stderr = (
            stderr[:max_output] + f"\n... (stderr 已截断，共 {len(stderr_bytes)} 字节)"
        )

    parts: list[str] = [f"exit_code: {exit_code}"]
    if stdout.strip():
        parts.append(f"stdout:\n{stdout.strip()}")
    if stderr.strip():
        parts.append(f"stderr:\n{stderr.strip()}")

    return "\n\n".join(parts)
