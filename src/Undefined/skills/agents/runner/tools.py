# Agent 工具并发调度与 end 工具特殊处理
from __future__ import annotations

import asyncio
import logging
from typing import Any

from Undefined.ai.tooling import END_CO_CALL_REJECT_CONTENT
from Undefined.skills.anthropic_skills import AnthropicSkillRegistry
from Undefined.skills.agents.agent_tool_registry import AgentToolRegistry
from Undefined.utils.tool_calls import parse_tool_arguments


# 按运行时配置过滤不可用工具 schema
def _filter_tools_for_runtime_config(
    agent_name: str,
    tools: list[dict[str, Any]],
    runtime_config: Any | None,
) -> list[dict[str, Any]]:
    # web_agent 在 grok 未启用时从 schema 中剔除 grok_search
    if agent_name != "web_agent" or runtime_config is None:
        return tools

    if bool(getattr(runtime_config, "grok_search_enabled", False)):
        return tools

    filtered: list[dict[str, Any]] = []
    for tool in tools:
        function = tool.get("function") if isinstance(tool, dict) else None
        name = function.get("name") if isinstance(function, dict) else None
        if name == "grok_search":
            continue
        filtered.append(tool)
    return filtered


# 并发执行 tool_calls 并回填 tool 消息
async def execute_assistant_tool_calls(
    *,
    agent_name: str,
    tool_calls: list[dict[str, Any]],
    api_to_internal: dict[str, str],
    messages: list[dict[str, Any]],
    tool_registry: AgentToolRegistry,
    agent_skill_registry: AnthropicSkillRegistry | None,
    context: dict[str, Any],
    logger: logging.Logger,
    tool_error_prefix: str,
) -> bool:
    """并发执行 assistant 的 tool_calls，回填 tool 消息。返回是否已开始工具执行。"""

    tool_tasks: list[asyncio.Future[Any]] = []
    tool_call_ids: list[str] = []
    tool_api_names: list[str] = []
    end_tool_call: dict[str, Any] | None = None
    end_tool_args: dict[str, Any] = {}
    tool_execution_started = False

    for tool_call in tool_calls:
        call_id = str(tool_call.get("id", ""))
        function: dict[str, Any] = tool_call.get("function", {})
        api_function_name = str(function.get("name", ""))
        raw_args = function.get("arguments")

        internal_function_name = api_to_internal.get(
            api_function_name, api_function_name
        )
        logger.info(
            "[Agent:%s] preparing tool=%s",
            agent_name,
            internal_function_name,
        )

        function_args = parse_tool_arguments(
            raw_args,
            logger=logger,
            tool_name=api_function_name,
        )

        if not isinstance(function_args, dict):
            function_args = {}

        # end 工具延后处理：若与其他工具同批调用则返回拒绝
        if internal_function_name == "end":
            if len(tool_calls) > 1:
                logger.warning(
                    "[Agent:%s] end 与其他工具同时调用，"
                    "将先执行其他工具，end 将返回拒绝结果",
                    agent_name,
                )
            end_tool_call = tool_call
            end_tool_args = function_args
            continue

        tool_call_ids.append(call_id)
        tool_api_names.append(api_function_name)

        skill_delimiter = (
            agent_skill_registry.dot_delimiter if agent_skill_registry else "-_-"
        )
        # Anthropic Skill 走独立 registry，其余走 AgentToolRegistry
        is_agent_skill = internal_function_name.startswith(f"skills{skill_delimiter}")
        if is_agent_skill and agent_skill_registry:
            tool_tasks.append(
                asyncio.ensure_future(
                    agent_skill_registry.execute_skill_tool(
                        internal_function_name,
                        function_args,
                        context,
                    )
                )
            )
        else:
            tool_tasks.append(
                asyncio.ensure_future(
                    tool_registry.execute_tool(
                        internal_function_name,
                        function_args,
                        context,
                    )
                )
            )

    if tool_tasks:
        tool_execution_started = True
        logger.info(
            "[Agent:%s] executing tools in parallel: count=%s",
            agent_name,
            len(tool_tasks),
        )
        # 同轮 tool_calls 并发执行，异常转为 tool 消息内容
        results = await asyncio.gather(*tool_tasks, return_exceptions=True)

        for index, tool_result in enumerate(results):
            call_id = tool_call_ids[index]
            api_tool_name = tool_api_names[index]
            if isinstance(tool_result, Exception):
                content_str = f"{tool_error_prefix}: {tool_result}"
            else:
                content_str = str(tool_result)

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "name": api_tool_name,
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
                    "content": END_CO_CALL_REJECT_CONTENT,
                }
            )
            logger.info(
                "[Agent:%s] end 与其他工具同时调用，其它工具已执行，end 已回填拒绝响应",
                agent_name,
            )
        else:
            tool_execution_started = True
            end_result = await tool_registry.execute_tool("end", end_tool_args, context)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": end_call_id,
                    "name": end_api_name,
                    "content": str(end_result),
                }
            )

    return tool_execution_started
