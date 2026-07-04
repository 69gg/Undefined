# Agent 运行前上下文准备（工具注册表、模型、消息链）
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import aiofiles

from Undefined.config.models import AgentModelConfig
from Undefined.config.search import KNOWN_SEARCH_TOOLS, order_by_priority
from Undefined.skills.agents.agent_tool_registry import AgentToolRegistry
from Undefined.skills.anthropic_skills import AnthropicSkillRegistry

from Undefined.skills.agents.runner.tools import _filter_tools_for_runtime_config


# 异步读取 agent 目录下的 prompt.md
async def load_prompt_text(agent_dir: Path, default_prompt: str) -> str:
    """从 agent 目录加载 prompt.md，缺失时返回默认提示词。"""

    prompt_path = agent_dir / "prompt.md"
    if prompt_path.exists():
        async with aiofiles.open(prompt_path, "r", encoding="utf-8") as file:
            return await file.read()
    return default_prompt


def _tool_names(tools: list[dict[str, Any]]) -> set[str]:
    names: set[str] = set()
    for tool in tools:
        function = tool.get("function") if isinstance(tool, dict) else None
        name = function.get("name") if isinstance(function, dict) else None
        if isinstance(name, str) and name:
            names.add(name)
    return names


def _build_web_agent_search_priority_prompt(
    runtime_config: Any | None,
    tools: list[dict[str, Any]],
) -> str:
    available_names = _tool_names(tools)
    priority = list(getattr(runtime_config, "search_priority", []) or [])
    ordered = order_by_priority(priority, available_names)
    if not ordered:
        return ""

    return "\n".join(
        [
            "【搜索工具优先级】",
            f"- 当前可用搜索工具优先级：{' > '.join(ordered)}。",
            "- 搜索类任务优先考虑排在前面的工具；当前一个工具不可用、不适合、结果不足或需要交叉验证时，再使用后面的工具。",
            "- 关闭的搜索工具不会出现在可用工具列表中；不要提议或假装调用未提供的工具。",
        ]
    )


def _append_web_agent_runtime_prompt(
    agent_name: str,
    system_prompt: str,
    runtime_config: Any | None,
    tools: list[dict[str, Any]],
) -> str:
    if agent_name != "web_agent":
        return system_prompt
    if not (_tool_names(tools) & KNOWN_SEARCH_TOOLS):
        return system_prompt
    priority_prompt = _build_web_agent_search_priority_prompt(runtime_config, tools)
    if not priority_prompt:
        return system_prompt
    return f"{system_prompt.rstrip()}\n\n{priority_prompt}"


@dataclass
# 类：PreparedAgentRun
class PreparedAgentRun:
    tool_registry: AgentToolRegistry
    agent_skill_registry: AnthropicSkillRegistry | None
    tools: list[dict[str, Any]]
    agent_config: AgentModelConfig
    messages: list[dict[str, Any]]
    ai_client: Any
    queue_lane: Any
    max_pre_tool_retries: int


# 准备 Agent 运行上下文：工具、模型、消息链
async def prepare_agent_run(
    *,
    agent_name: str,
    user_content: str,
    context_messages: list[dict[str, str]] | None,
    default_prompt: str,
    context: dict[str, Any],
    agent_dir: Path,
    logger: Any,
) -> PreparedAgentRun | str:
    # 为当前 Agent 实例化私有工具注册表（含 callable agent 扫描）
    tool_registry = AgentToolRegistry(
        agent_dir / "tools",
        current_agent_name=agent_name,
        is_main_agent=False,
    )
    tools = tool_registry.get_tools_schema()
    runtime_config = context.get("runtime_config")
    tools = _filter_tools_for_runtime_config(agent_name, tools, runtime_config)

    agent_skills_dir = agent_dir / "anthropic_skills"
    agent_skill_registry: AnthropicSkillRegistry | None = None
    # 可选：加载 Agent 目录下的 Anthropic Skills 并追加 tool schema
    if agent_skills_dir.exists() and agent_skills_dir.is_dir():
        agent_skill_registry = AnthropicSkillRegistry(agent_skills_dir)
        if agent_skill_registry.has_skills():
            tools = tools + agent_skill_registry.get_tools_schema()
            logger.info(
                "[Agent:%s] 加载了 %d 个私有 Anthropic Skills",
                agent_name,
                len(agent_skill_registry.get_all_skills()),
            )

    ai_client = context.get("ai_client")
    if not ai_client:
        return "AI client 未在上下文中提供"

    model_config_override = context.get("model_config_override")
    if isinstance(model_config_override, AgentModelConfig):
        agent_config = model_config_override
    else:
        agent_config = ai_client.agent_config
        group_id = context.get("group_id", 0) or 0
        user_id = context.get("user_id", 0) or 0
        global_enabled = runtime_config.model_pool_enabled if runtime_config else False
        # 多模型池：按群/私聊上下文选择 Agent 专用模型配置
        agent_config = ai_client.model_selector.select_agent_config(
            agent_config,
            group_id=group_id,
            user_id=user_id,
            global_enabled=global_enabled,
        )
    system_prompt = await load_prompt_text(agent_dir, default_prompt)
    system_prompt = _append_web_agent_runtime_prompt(
        agent_name,
        system_prompt,
        runtime_config,
        tools,
    )

    if agent_skill_registry and agent_skill_registry.has_skills():
        skills_xml = agent_skill_registry.build_metadata_xml()
        if skills_xml:
            system_prompt = (
                f"{system_prompt}\n\n"
                f"【可用的 Anthropic Skills】\n"
                f"{skills_xml}\n\n"
                f"注意：以上是你可用的 Anthropic Agent Skills。"
                f"当任务与某个 skill 相关时，"
                f"可以调用对应的 skill tool（tool_name 字段）"
                f"来获取该领域的详细指令和知识。"
            )

    agent_history = context.get("agent_history", [])

    # 组装 LLM 消息链：system → agent 历史 → 上下文 → 当前用户输入
    messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    if agent_history:
        messages.extend(agent_history)
    if context_messages:
        messages.extend(context_messages)
    messages.append({"role": "user", "content": user_content})

    queue_lane = context.get("queue_lane")
    max_pre_tool_retries = max(
        0, int(getattr(runtime_config, "ai_request_max_retries", 0) or 0)
    )

    return PreparedAgentRun(
        tool_registry=tool_registry,
        agent_skill_registry=agent_skill_registry,
        tools=tools,
        agent_config=agent_config,
        messages=messages,
        ai_client=ai_client,
        queue_lane=queue_lane,
        max_pre_tool_retries=max_pre_tool_retries,
    )
