from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import aiofiles

from Undefined.skills.agents.agent_tool_registry import AgentToolRegistry
from Undefined.skills.anthropic_skills import AnthropicSkillRegistry
from Undefined.utils.tool_calls import parse_tool_arguments


async def load_prompt_text(agent_dir: Path, default_prompt: str) -> str:
    """从 agent 目录加载 prompt.md，缺失时返回默认提示词。"""

    prompt_path = agent_dir / "prompt.md"
    if prompt_path.exists():
        async with aiofiles.open(prompt_path, "r", encoding="utf-8") as file:
            return await file.read()
    return default_prompt


async def run_agent_with_tools(
    *,
    agent_name: str,
    user_content: str,
    empty_user_content_message: str,
    default_prompt: str,
    context: dict[str, Any],
    agent_dir: Path,
    logger: logging.Logger,
    max_iterations: int = 20,
    tool_error_prefix: str = "错误",
) -> str:
    """执行通用 Agent 循环。

    该方法统一处理：
    - prompt 加载
    - LLM 迭代决策
    - tool call 并发执行
    - tool 结果回填 messages
    """

    if not user_content.strip():
        return empty_user_content_message

    tool_registry = AgentToolRegistry(agent_dir / "tools")
    tools = tool_registry.get_tools_schema()

    # 发现并加载 agent 私有 Anthropic Skills（可选）
    agent_skills_dir = agent_dir / "anthropic_skills"
    agent_skill_registry: AnthropicSkillRegistry | None = None
    if agent_skills_dir.exists() and agent_skills_dir.is_dir():
        agent_skill_registry = AnthropicSkillRegistry(agent_skills_dir)
        if agent_skill_registry.has_skills():
            # 将 anthropic skill tools 加入 agent 的可用工具列表
            tools = tools + agent_skill_registry.get_tools_schema()
            logger.info(
                "[Agent:%s] 加载了 %d 个私有 Anthropic Skills",
                agent_name,
                len(agent_skill_registry.get_all_skills()),
            )

    ai_client = context.get("ai_client")
    if not ai_client:
        return "AI client 未在上下文中提供"

    agent_config = ai_client.agent_config
    system_prompt = await load_prompt_text(agent_dir, default_prompt)

    # 注入 agent 私有 Anthropic Skills 元数据到 system prompt
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

    messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    if agent_history:
        messages.extend(agent_history)
    messages.append({"role": "user", "content": user_content})

    for iteration in range(1, max_iterations + 1):
        logger.debug("[Agent:%s] iteration=%s", agent_name, iteration)
        try:
            result = await ai_client.request_model(
                model_config=agent_config,
                messages=messages,
                max_tokens=agent_config.max_tokens,
                call_type=f"agent:{agent_name}",
                tools=tools if tools else None,
                tool_choice="auto",
            )

            tool_name_map = (
                result.get("_tool_name_map") if isinstance(result, dict) else None
            )
            api_to_internal: dict[str, str] = {}
            if isinstance(tool_name_map, dict):
                raw_api_to_internal = tool_name_map.get("api_to_internal")
                if isinstance(raw_api_to_internal, dict):
                    api_to_internal = {
                        str(key): str(value)
                        for key, value in raw_api_to_internal.items()
                    }

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

                # 检测 end 工具，暂存后统一处理
                if internal_function_name == "end":
                    if len(tool_calls) > 1:
                        logger.warning(
                            "[Agent:%s] end 与其他工具同时调用，"
                            "将先执行其他工具，并回填 end 跳过结果",
                            agent_name,
                        )
                        end_tool_call = tool_call
                        continue
                    else:
                        end_tool_call = tool_call
                        continue

                tool_call_ids.append(call_id)
                tool_api_names.append(api_function_name)

                # Anthropic Skill tool 路由
                # 工具名格式: skills<delimiter><name>，如 skills-_-pdf-processing
                skill_delimiter = (
                    agent_skill_registry.dot_delimiter
                    if agent_skill_registry
                    else "-_-"
                )
                is_agent_skill = internal_function_name.startswith(
                    f"skills{skill_delimiter}"
                )
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
                logger.info(
                    "[Agent:%s] executing tools in parallel: count=%s",
                    agent_name,
                    len(tool_tasks),
                )
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

            # 处理 end 工具调用
            if end_tool_call:
                end_call_id = str(end_tool_call.get("id", ""))
                end_api_name = end_tool_call.get("function", {}).get("name", "end")
                if tool_tasks:
                    # end 与其他工具同时调用：跳过执行，但仍回填 tool 响应，
                    # 避免 assistant.tool_calls 出现未配对的 tool_call_id。
                    skip_content = (
                        "end 与其他工具同轮调用，本轮未执行 end；"
                        "请根据其他工具结果继续决策。"
                    )
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": end_call_id,
                            "name": end_api_name,
                            "content": skip_content,
                        }
                    )
                    logger.info(
                        "[Agent:%s] end 与其他工具同时调用，已回填跳过响应",
                        agent_name,
                    )
                else:
                    # end 单独调用，正常执行
                    end_args = parse_tool_arguments(
                        end_tool_call.get("function", {}).get("arguments"),
                        logger=logger,
                        tool_name="end",
                    )
                    if not isinstance(end_args, dict):
                        end_args = {}
                    end_result = await tool_registry.execute_tool(
                        "end", end_args, context
                    )
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": end_call_id,
                            "name": end_api_name,
                            "content": str(end_result),
                        }
                    )

        except Exception as exc:
            logger.exception("[Agent:%s] execution failed: %s", agent_name, exc)
            return f"处理失败: {exc}"

    return "达到最大迭代次数"
