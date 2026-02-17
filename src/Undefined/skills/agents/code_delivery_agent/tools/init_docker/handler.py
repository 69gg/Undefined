from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any


async def execute(args: dict[str, Any], context: dict[str, Any]) -> str:
    """初始化 Docker 容器和工作区。"""
    if context.get("docker_initialized"):
        return "Docker 容器已初始化，无需重复调用"

    init_args = context.get("init_args", {})
    config = context.get("code_delivery_config", {})

    task_id = str(uuid.uuid4())
    task_dir = Path(config["task_root"]) / task_id
    workspace = task_dir / "workspace"
    tmpfs_dir = task_dir / "tmpfs"
    workspace.mkdir(parents=True, exist_ok=True)
    tmpfs_dir.mkdir(parents=True, exist_ok=True)

    container_name = f"{config['prefix']}{task_id}{config['suffix']}"

    from ...docker_utils import create_container, destroy_container, init_workspace

    try:
        await create_container(
            container_name,
            workspace,
            tmpfs_dir,
            config["docker_image"],
            config["memory_limit"],
            config["cpu_limit"],
        )
        context["container_name"] = container_name
        context["task_dir"] = task_dir

        await init_workspace(
            workspace,
            container_name,
            init_args.get("source_type", "empty"),
            init_args.get("git_url", ""),
            init_args.get("git_ref", ""),
        )
    except Exception:
        try:
            await destroy_container(container_name)
        except Exception:
            pass
        import shutil

        if task_dir.exists():
            shutil.rmtree(task_dir, ignore_errors=True)
        raise

    context["docker_initialized"] = True
    context["workspace"] = workspace

    source_type = init_args.get("source_type", "empty")
    if source_type == "git":
        source_info = f"已从 Git 克隆: {init_args.get('git_url')}"
        if init_args.get("git_ref"):
            source_info += f" (ref: {init_args['git_ref']})"
    else:
        source_info = "空目录，可从零开始创建项目"

    return f"Docker 容器初始化完成\n{source_info}\n工作目录: /workspace"
