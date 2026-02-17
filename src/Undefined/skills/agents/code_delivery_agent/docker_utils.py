from __future__ import annotations

import asyncio
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


async def run_cmd(*args: str, timeout: float = 60) -> tuple[int, str, str]:
    """执行宿主机命令，返回 (exit_code, stdout, stderr)。"""
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return -1, "", "timeout"
    return (
        proc.returncode or 0,
        stdout_b.decode("utf-8", errors="replace").strip(),
        stderr_b.decode("utf-8", errors="replace").strip(),
    )


async def create_container(
    container_name: str,
    workspace: Path,
    tmpfs_dir: Path,
    docker_image: str,
    memory_limit: str = "",
    cpu_limit: str = "",
) -> None:
    """创建并启动 Docker 容器。"""
    cmd_args = [
        "docker",
        "run",
        "-d",
        "--name",
        container_name,
    ]

    if memory_limit:
        cmd_args.extend(["--memory", memory_limit])
    if cpu_limit:
        cmd_args.extend(["--cpus", cpu_limit])

    cmd_args.extend(
        [
            "-v",
            f"{workspace.resolve()}:/workspace",
            "-v",
            f"{tmpfs_dir.resolve()}:/tmpfs",
            "-w",
            "/workspace",
            docker_image,
            "sleep",
            "infinity",
        ]
    )

    rc, stdout, stderr = await run_cmd(*cmd_args, timeout=120)
    if rc != 0:
        raise RuntimeError(f"创建容器失败: {stderr or stdout}")
    logger.info("[CodeDelivery] 容器已创建: %s", container_name)


async def destroy_container(container_name: str) -> bool:
    """停止并删除容器，返回是否清理成功。"""
    try:
        rc, stdout, stderr = await run_cmd(
            "docker", "rm", "-f", container_name, timeout=30
        )
        if rc != 0:
            err_msg = stderr or stdout
            # 不存在视为已完成清理，避免重复清理导致噪声。
            if "No such container" in err_msg:
                logger.info("[CodeDelivery] 容器不存在，视为已清理: %s", container_name)
                return True
            logger.warning(
                "[CodeDelivery] 销毁容器失败: %s -> %s", container_name, err_msg
            )
            return False
        logger.info("[CodeDelivery] 容器已销毁: %s", container_name)
        return True
    except Exception as exc:
        logger.warning("[CodeDelivery] 销毁容器失败: %s -> %s", container_name, exc)
        return False


async def init_workspace(
    workspace: Path,
    container_name: str,
    source_type: str,
    git_url: str,
    git_ref: str,
) -> None:
    """初始化工作区：git clone 或保持空目录。"""
    if source_type == "git" and git_url:
        await run_cmd(
            "docker",
            "exec",
            container_name,
            "bash",
            "-lc",
            "apt-get update -qq && apt-get install -y -qq git > /dev/null 2>&1",
            timeout=120,
        )
        clone_cmd = f"git clone {git_url} /workspace"
        if git_ref:
            clone_cmd = (
                f"git clone {git_url} /tmp/_clone_src && "
                f"cp -a /tmp/_clone_src/. /workspace/ && "
                f"cd /workspace && git checkout {git_ref}"
            )
        rc, stdout, stderr = await run_cmd(
            "docker",
            "exec",
            container_name,
            "bash",
            "-lc",
            clone_cmd,
            timeout=300,
        )
        if rc != 0:
            raise RuntimeError(f"Git clone 失败: {stderr or stdout}")
        logger.info(
            "[CodeDelivery] Git clone 完成: %s (ref=%s)", git_url, git_ref or "default"
        )
