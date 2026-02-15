from __future__ import annotations

import asyncio
import logging
import shutil
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Docker 容器与工作区管理
# ---------------------------------------------------------------------------

CONTAINER_PREFIX_DEFAULT = "code_delivery_"
CONTAINER_SUFFIX_DEFAULT = "_runner"
TASK_ROOT_DEFAULT = "data/code_delivery"


async def _run_cmd(*args: str, timeout: float = 60) -> tuple[int, str, str]:
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


async def _cleanup_residual(
    task_root: str,
    prefix: str,
    suffix: str,
) -> None:
    """启动前清理残留工作区和容器。"""
    # 清理残留目录
    root = Path(task_root)
    if root.exists():
        for child in root.iterdir():
            if child.is_dir():
                try:
                    shutil.rmtree(child)
                    logger.info("[CodeDelivery] 清理残留目录: %s", child)
                except Exception as exc:
                    logger.warning(
                        "[CodeDelivery] 清理残留目录失败: %s -> %s", child, exc
                    )

    # 清理残留容器（匹配前后缀）
    rc, stdout, _ = await _run_cmd("docker", "ps", "-a", "--format", "{{.Names}}")
    if rc == 0 and stdout:
        for name in stdout.splitlines():
            name = name.strip()
            if name.startswith(prefix) and name.endswith(suffix):
                logger.info("[CodeDelivery] 清理残留容器: %s", name)
                await _run_cmd("docker", "rm", "-f", name)


async def _create_container(
    container_name: str,
    workspace: Path,
    tmpfs_dir: Path,
    docker_image: str,
) -> None:
    """创建并启动 Docker 容器。"""
    rc, stdout, stderr = await _run_cmd(
        "docker",
        "run",
        "-d",
        "--name",
        container_name,
        "-v",
        f"{workspace.resolve()}:/workspace",
        "-v",
        f"{tmpfs_dir.resolve()}:/tmpfs",
        "-w",
        "/workspace",
        docker_image,
        "sleep",
        "infinity",
        timeout=120,
    )
    if rc != 0:
        raise RuntimeError(f"创建容器失败: {stderr or stdout}")
    logger.info("[CodeDelivery] 容器已创建: %s", container_name)


async def _destroy_container(container_name: str) -> None:
    """停止并删除容器。"""
    try:
        await _run_cmd("docker", "rm", "-f", container_name, timeout=30)
        logger.info("[CodeDelivery] 容器已销毁: %s", container_name)
    except Exception as exc:
        logger.warning("[CodeDelivery] 销毁容器失败: %s -> %s", container_name, exc)


async def _init_workspace(
    workspace: Path,
    container_name: str,
    source_type: str,
    git_url: str,
    git_ref: str,
) -> None:
    """初始化工作区：git clone 或保持空目录。"""
    if source_type == "git" and git_url:
        # 先在容器内安装 git
        await _run_cmd(
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
            # clone 后 checkout 指定 ref
            clone_cmd = (
                f"git clone {git_url} /tmp/_clone_src && "
                f"cp -a /tmp/_clone_src/. /workspace/ && "
                f"cd /workspace && git checkout {git_ref}"
            )
        rc, stdout, stderr = await _run_cmd(
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


async def _send_failure_notification(
    context: dict[str, Any],
    target_type: str,
    target_id: int,
    task_id: str,
    error_msg: str,
) -> None:
    """向目标发送 LLM 失败通知。"""
    onebot_client = context.get("onebot_client")
    if not onebot_client:
        return
    msg = (
        f"⚠️ 代码交付任务失败\n\n"
        f"任务 ID: {task_id}\n"
        f"失败原因: {error_msg}\n\n"
        f"建议：检查任务描述后重试。"
    )
    try:
        if target_type == "group":
            await onebot_client.send_group_message(target_id, msg)
        else:
            await onebot_client.send_private_message(target_id, msg)
    except Exception as exc:
        logger.warning("[CodeDelivery] 发送失败通知失败: %s", exc)


# ---------------------------------------------------------------------------
# Agent 入口
# ---------------------------------------------------------------------------


async def execute(args: dict[str, Any], context: dict[str, Any]) -> str:
    """执行 code_delivery_agent。"""

    # 解析参数
    user_prompt = str(args.get("prompt", "")).strip()
    source_type = str(args.get("source_type", "empty")).strip().lower()
    git_url = str(args.get("git_url", "")).strip()
    git_ref = str(args.get("git_ref", "")).strip()
    target_type = str(args.get("target_type", "")).strip().lower()
    target_id = int(args.get("target_id", 0))

    if not user_prompt:
        return "请提供任务目标描述"
    if source_type not in ("git", "empty"):
        return "source_type 必须为 'git' 或 'empty'"
    if source_type == "git" and not git_url:
        return "source_type=git 时必须提供 git_url"
    if target_type not in ("group", "private"):
        return "target_type 必须为 'group' 或 'private'"
    if target_id <= 0:
        return "target_id 必须为正整数"

    # 读取配置
    config = context.get("config")
    task_root = TASK_ROOT_DEFAULT
    docker_image = "ubuntu:24.04"
    prefix = CONTAINER_PREFIX_DEFAULT
    suffix = CONTAINER_SUFFIX_DEFAULT
    cleanup_on_finish = True
    llm_max_retries = 5
    notify_on_failure = True

    if config:
        if not getattr(config, "code_delivery_enabled", True):
            return "Code Delivery Agent 已禁用"
        task_root = getattr(config, "code_delivery_task_root", task_root)
        docker_image = getattr(config, "code_delivery_docker_image", docker_image)
        prefix = getattr(config, "code_delivery_container_name_prefix", prefix)
        suffix = getattr(config, "code_delivery_container_name_suffix", suffix)
        cleanup_on_finish = getattr(config, "code_delivery_cleanup_on_finish", True)
        llm_max_retries = getattr(config, "code_delivery_llm_max_retries", 5)
        notify_on_failure = getattr(config, "code_delivery_notify_on_llm_failure", True)

    # 创建任务目录
    task_id = str(uuid.uuid4())
    task_dir = Path(task_root) / task_id
    workspace = task_dir / "workspace"
    tmpfs_dir = task_dir / "tmpfs"
    workspace.mkdir(parents=True, exist_ok=True)
    tmpfs_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "logs").mkdir(exist_ok=True)
    (task_dir / "artifacts").mkdir(exist_ok=True)

    container_name = f"{prefix}{task_id}{suffix}"

    # 注入上下文供子工具使用
    context["task_dir"] = task_dir
    context["workspace"] = workspace
    context["container_name"] = container_name
    context["target_type"] = target_type
    context["target_id"] = target_id

    try:
        # 创建容器
        await _create_container(container_name, workspace, tmpfs_dir, docker_image)

        # 初始化工作区
        await _init_workspace(workspace, container_name, source_type, git_url, git_ref)

        # 组装 user_content
        source_info = (
            f"初始化来源: source_type=git, git_url={git_url}"
            + (f", git_ref={git_ref}" if git_ref else "")
            if source_type == "git"
            else "初始化来源: source_type=empty（空目录，需要从零开始创建项目）"
        )
        user_content = (
            f"用户需求：{user_prompt}\n\n"
            f"{source_info}\n"
            f"交付目标: target_type={target_type}, target_id={target_id}\n\n"
            f"请开始工作。"
        )

        # 使用自定义 runner 支持 LLM 失败重试计数
        result = await _run_agent_with_retry(
            user_content=user_content,
            context=context,
            agent_dir=Path(__file__).parent,
            llm_max_retries=llm_max_retries,
            notify_on_failure=notify_on_failure,
            target_type=target_type,
            target_id=target_id,
            task_id=task_id,
        )
        return result

    except Exception as exc:
        logger.exception("[CodeDelivery] 任务执行失败: %s", exc)
        # 发送失败通知
        if notify_on_failure:
            await _send_failure_notification(
                context, target_type, target_id, task_id, str(exc)
            )
        return f"任务执行失败: {exc}"

    finally:
        # 兜底清理
        if cleanup_on_finish:
            try:
                await _destroy_container(container_name)
            except Exception as exc:
                logger.warning("[CodeDelivery] 清理容器失败: %s", exc)
            try:
                if task_dir.exists():
                    shutil.rmtree(task_dir)
                    logger.info("[CodeDelivery] 已清理任务目录: %s", task_dir)
            except Exception as exc:
                logger.warning("[CodeDelivery] 清理任务目录失败: %s", exc)


async def _run_agent_with_retry(
    *,
    user_content: str,
    context: dict[str, Any],
    agent_dir: Path,
    llm_max_retries: int,
    notify_on_failure: bool,
    target_type: str,
    target_id: int,
    task_id: str,
) -> str:
    """带 LLM 连续失败检测的 agent 执行。

    对 run_agent_with_tools 的包装：在 runner 内部，每次 LLM 请求
    如果连续失败达到 llm_max_retries 次，则发送通知并终止。
    """

    from Undefined.skills.agents.agent_tool_registry import AgentToolRegistry
    from Undefined.skills.agents.runner import load_prompt_text
    from Undefined.utils.tool_calls import parse_tool_arguments

    ai_client = context.get("ai_client")
    if not ai_client:
        return "AI client 未在上下文中提供"

    agent_config = ai_client.agent_config
    system_prompt = await load_prompt_text(agent_dir, "你是一个代码交付助手。")

    tool_registry = AgentToolRegistry(agent_dir / "tools")
    tools = tool_registry.get_tools_schema()

    agent_history = context.get("agent_history", [])
    messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    if agent_history:
        messages.extend(agent_history)
    messages.append({"role": "user", "content": user_content})

    max_iterations = 50  # 代码交付任务通常需要更多轮次
    consecutive_failures = 0

    for iteration in range(1, max_iterations + 1):
        logger.debug("[CodeDelivery] iteration=%s", iteration)
        try:
            result = await ai_client.request_model(
                model_config=agent_config,
                messages=messages,
                max_tokens=agent_config.max_tokens,
                call_type="agent:code_delivery_agent",
                tools=tools if tools else None,
                tool_choice="auto",
            )
            # 请求成功，重置连续失败计数
            consecutive_failures = 0

        except Exception as exc:
            consecutive_failures += 1
            logger.warning(
                "[CodeDelivery] LLM 请求失败 (%d/%d): %s",
                consecutive_failures,
                llm_max_retries,
                exc,
            )
            if consecutive_failures >= llm_max_retries:
                error_msg = f"LLM 连续失败 {consecutive_failures} 次: {exc}"
                if notify_on_failure:
                    await _send_failure_notification(
                        context, target_type, target_id, task_id, error_msg
                    )
                return error_msg
            continue

        tool_name_map = (
            result.get("_tool_name_map") if isinstance(result, dict) else None
        )
        api_to_internal: dict[str, str] = {}
        if isinstance(tool_name_map, dict):
            raw = tool_name_map.get("api_to_internal")
            if isinstance(raw, dict):
                api_to_internal = {str(k): str(v) for k, v in raw.items()}

        choice: dict[str, Any] = result.get("choices", [{}])[0]
        message: dict[str, Any] = choice.get("message", {})
        content: str = message.get("content") or ""
        tool_calls: list[dict[str, Any]] = message.get("tool_calls", [])

        if content.strip() and tool_calls:
            content = ""

        if not tool_calls:
            return content

        messages.append(
            {"role": "assistant", "content": content, "tool_calls": tool_calls}
        )

        tool_tasks: list[asyncio.Future[Any]] = []
        tool_call_ids: list[str] = []
        tool_api_names: list[str] = []
        end_tool_call: dict[str, Any] | None = None
        end_tool_args: dict[str, Any] = {}

        for tool_call in tool_calls:
            call_id = str(tool_call.get("id", ""))
            function: dict[str, Any] = tool_call.get("function", {})
            api_name = str(function.get("name", ""))
            raw_args = function.get("arguments")

            internal_name = api_to_internal.get(api_name, api_name)
            function_args = parse_tool_arguments(
                raw_args, logger=logger, tool_name=api_name
            )
            if not isinstance(function_args, dict):
                function_args = {}

            if internal_name == "end":
                if len(tool_calls) > 1:
                    logger.warning(
                        "[CodeDelivery] end 与其他工具同时调用，先执行其他工具"
                    )
                end_tool_call = tool_call
                end_tool_args = function_args
                continue

            tool_call_ids.append(call_id)
            tool_api_names.append(api_name)
            tool_tasks.append(
                asyncio.ensure_future(
                    tool_registry.execute_tool(internal_name, function_args, context)
                )
            )

        if tool_tasks:
            results = await asyncio.gather(*tool_tasks, return_exceptions=True)
            for idx, tool_result in enumerate(results):
                cid = tool_call_ids[idx]
                aname = tool_api_names[idx]
                if isinstance(tool_result, Exception):
                    content_str = f"错误: {tool_result}"
                else:
                    content_str = str(tool_result)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": cid,
                        "name": aname,
                        "content": content_str,
                    }
                )

        if end_tool_call:
            end_call_id = str(end_tool_call.get("id", ""))
            end_api_name = end_tool_call.get("function", {}).get("name", "end")
            if tool_tasks:
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": end_call_id,
                        "name": end_api_name,
                        "content": (
                            "end 与其他工具同轮调用，本轮未执行 end；"
                            "请根据其他工具结果继续决策。"
                        ),
                    }
                )
            else:
                end_result = await tool_registry.execute_tool(
                    "end", end_tool_args, context
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": end_call_id,
                        "name": end_api_name,
                        "content": str(end_result),
                    }
                )
                # end 执行后返回结果
                return str(end_result)

    return "达到最大迭代次数"
