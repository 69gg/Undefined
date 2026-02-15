from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


async def execute(args: dict[str, Any], context: dict[str, Any]) -> str:
    """在 Docker 容器内执行 bash 命令。"""

    command = str(args.get("command", "")).strip()
    if not command:
        return "错误：command 不能为空"

    container_name: str | None = context.get("container_name")
    if not container_name:
        return "错误：容器未启动"

    config = context.get("config")
    default_timeout: int = 600
    max_output: int = 20000
    if config:
        default_timeout = getattr(config, "code_delivery_command_timeout", 600)
        max_output = getattr(config, "code_delivery_max_command_output", 20000)

    timeout = int(args.get("timeout_seconds", 0)) or default_timeout
    workdir = str(args.get("workdir", "")).strip() or "/workspace"

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
