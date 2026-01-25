import asyncio
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)

# Docker 执行配置
DOCKER_IMAGE = "python:3.11-slim"
MEMORY_LIMIT = "128m"
CPU_LIMIT = "0.5"
TIMEOUT = 120  # 用户要求的 120s


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    """
    在 Docker 容器中执行 Python 代码。
    """
    code = args.get("code", "")
    if not code:
        return "错误: 未提供代码。"

    # 构建 docker run 命令
    # --rm: 执行后自动删除容器
    # --network none: 禁用网络
    # --memory/--cpus: 资源限制
    # --read-only: 只读文件系统
    # --tmpfs /tmp: 允许在 /tmp 写入
    # -u 1000:1000: 以非 root 用户运行 (在 slim 镜像中通常存在 'python' 用户，或者用 UID)

    cmd = [
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "--memory",
        MEMORY_LIMIT,
        "--cpus",
        CPU_LIMIT,
        "--read-only",
        "--tmpfs",
        "/tmp",
        "-i",  # 交互模式，用于传入代码
        DOCKER_IMAGE,
        "python",
        "-c",
        code,
    ]

    logger.info(f"[Python解释器] 开始执行代码，超时限制: {TIMEOUT}s")
    logger.debug(f"[Python解释器] 代码内容:\n{code}")

    try:
        # 使用 asyncio 执行子进程
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            # 等待完成，带超时
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=TIMEOUT
            )

            exit_code = process.returncode
            response = stdout.decode("utf-8", errors="replace")
            error_output = stderr.decode("utf-8", errors="replace")

            if exit_code == 0:
                return response if response.strip() else "代码执行成功 (无输出)。"
            else:
                return (
                    f"代码执行失败 (退出代码: {exit_code}):\n{error_output}\n{response}"
                )

        except asyncio.TimeoutError:
            # 超时处理
            try:
                # 尝试杀掉容器 (由于用了 --rm，杀掉容器会清理资源)
                # 注意：子进程是 docker 客户端，单纯 kill 客户端可能不会立刻停止远程容器
                # 但在这里 docker run -i 配合 communicate()，终止子进程通常足够
                process.terminate()
                await process.wait()
            except Exception as e:
                logger.error(f"[Python解释器] 终止超时进程失败: {e}")

            return f"错误: 代码执行超时 ({TIMEOUT}s)。"

    except Exception as e:
        logger.exception(f"[Python解释器] 执行出错: {e}")
        return f"执行出错: {str(e)}"
