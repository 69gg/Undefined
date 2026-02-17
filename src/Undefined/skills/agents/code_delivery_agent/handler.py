from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

from .docker_utils import destroy_container, run_cmd

logger = logging.getLogger(__name__)


async def execute(args: dict[str, Any], context: dict[str, Any]) -> str:
    """执行 code_delivery_agent。"""
    user_prompt = str(args.get("prompt", "")).strip()
    target_type = str(args.get("target_type", "")).strip().lower()
    target_id = int(args.get("target_id", 0))

    if not user_prompt:
        return "请提供任务目标描述"
    if target_type not in ("group", "private"):
        return "target_type 必须为 'group' 或 'private'"
    if target_id <= 0:
        return "target_id 必须为正整数"

    config = context.get("config")
    if config and not getattr(config, "code_delivery_enabled", True):
        return "Code Delivery Agent 已禁用"

    # 注入上下文供工具使用
    context["docker_initialized"] = False
    context["init_args"] = {
        "source_type": args.get("source_type", "empty"),
        "git_url": args.get("git_url", ""),
        "git_ref": args.get("git_ref", ""),
    }
    context["target_type"] = target_type
    context["target_id"] = target_id
    context["code_delivery_config"] = {
        "task_root": getattr(config, "code_delivery_task_root", "data/code_delivery"),
        "docker_image": getattr(config, "code_delivery_docker_image", "ubuntu:24.04"),
        "prefix": getattr(
            config, "code_delivery_container_name_prefix", "code_delivery_"
        ),
        "suffix": getattr(config, "code_delivery_container_name_suffix", "_runner"),
        "cleanup_on_finish": getattr(config, "code_delivery_cleanup_on_finish", True),
        "memory_limit": getattr(config, "code_delivery_container_memory_limit", ""),
        "cpu_limit": getattr(config, "code_delivery_container_cpu_limit", ""),
    }

    cleanup_on_finish = context["code_delivery_config"]["cleanup_on_finish"]

    try:
        user_content = f"用户需求：{user_prompt}\n\n请开始工作。"
        result = await _run_agent_with_retry(
            user_content=user_content,
            context=context,
            agent_dir=Path(__file__).parent,
        )
        return result
    except Exception as exc:
        logger.exception("[CodeDelivery] 任务执行失败: %s", exc)
        return f"任务执行失败: {exc}"
    finally:
        if context.get("docker_initialized") and cleanup_on_finish:
            container_name = context.get("container_name")
            task_dir = context.get("task_dir")
            if container_name:
                try:
                    await destroy_container(container_name)
                except Exception as exc:
                    logger.warning("[CodeDelivery] 清理容器失败: %s", exc)
            if task_dir and Path(task_dir).exists():
                try:
                    shutil.rmtree(task_dir)
                    logger.info("[CodeDelivery] 已清理任务目录: %s", task_dir)
                except Exception as exc:
                    logger.warning("[CodeDelivery] 清理任务目录失败: %s", exc)


async def _run_agent_with_retry(
    *,
    user_content: str,
    context: dict[str, Any],
    agent_dir: Path,
) -> str:
    """执行 agent。"""
    from Undefined.skills.agents.runner import run_agent_with_tools

    return await run_agent_with_tools(
        agent_name="code_delivery_agent",
        user_content=user_content,
        empty_user_content_message="请提供任务目标描述",
        default_prompt="你是一个专业的代码交付助手。",
        context=context,
        agent_dir=agent_dir,
        logger=logger,
        max_iterations=50,
        tool_error_prefix="错误",
    )


async def _list_residual_containers(
    *,
    container_name_prefix: str,
    container_name_suffix: str,
) -> list[str]:
    """列出符合命名规则的残留容器名。"""
    try:
        rc, stdout, stderr = await run_cmd(
            "docker", "ps", "-a", "--format", "{{.Names}}", timeout=30
        )
    except Exception as exc:
        logger.warning("[CodeDelivery] 扫描容器失败: %s", exc)
        return []

    if rc != 0:
        logger.warning("[CodeDelivery] 扫描容器失败: %s", stderr or stdout)
        return []

    containers: list[str] = []
    for line in stdout.splitlines():
        name = line.strip()
        if not name:
            continue
        if container_name_prefix and not name.startswith(container_name_prefix):
            continue
        if container_name_suffix and not name.endswith(container_name_suffix):
            continue
        containers.append(name)
    return containers


async def _cleanup_residual(
    task_root: str,
    container_name_prefix: str,
    container_name_suffix: str,
) -> None:
    """清理 code delivery 任务残留目录和容器（启动时调用）。"""
    task_root_path = Path(task_root)
    task_dirs: list[Path] = []

    if task_root_path.exists():
        if task_root_path.is_dir():
            task_dirs = [entry for entry in task_root_path.iterdir() if entry.is_dir()]
        else:
            logger.warning("[CodeDelivery] task_root 不是目录: %s", task_root_path)

    # 基于任务目录名推导容器名，兼容 docker 无法访问的情况。
    container_names = {
        f"{container_name_prefix}{task_dir.name}{container_name_suffix}"
        for task_dir in task_dirs
    }
    container_names.update(
        await _list_residual_containers(
            container_name_prefix=container_name_prefix,
            container_name_suffix=container_name_suffix,
        )
    )

    cleaned_containers = 0
    for container_name in sorted(container_names):
        try:
            removed = await destroy_container(container_name)
            if removed:
                cleaned_containers += 1
        except Exception as exc:
            logger.warning("[CodeDelivery] 清理容器失败: %s -> %s", container_name, exc)

    cleaned_dirs = 0
    for task_dir in task_dirs:
        try:
            shutil.rmtree(task_dir)
            cleaned_dirs += 1
        except Exception as exc:
            logger.warning("[CodeDelivery] 清理任务目录失败: %s -> %s", task_dir, exc)

    logger.info(
        "[CodeDelivery] 启动残留清理: containers=%s task_dirs=%s",
        cleaned_containers,
        cleaned_dirs,
    )
