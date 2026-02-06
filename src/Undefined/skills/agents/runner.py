from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import aiofiles

from Undefined.skills.agents.agent_tool_registry import AgentToolRegistry
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

    ai_client = context.get("ai_client")
    if not ai_client:
        return "AI client 未在上下文中提供"

    agent_config = ai_client.agent_config
    system_prompt = await load_prompt_text(agent_dir, default_prompt)
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

                tool_call_ids.append(call_id)
                tool_api_names.append(api_function_name)
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

        except Exception as exc:
            logger.exception("[Agent:%s] execution failed: %s", agent_name, exc)
            return f"处理失败: {exc}"

    return "达到最大迭代次数"
