from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import aiofiles

from Undefined.skills.agents.agent_tool_registry import AgentToolRegistry
from Undefined.utils.tool_calls import parse_tool_arguments

logger = logging.getLogger(__name__)


async def _load_prompt() -> str:
    """从 prompt.md 文件加载系统提示词"""
    prompt_path: Path = Path(__file__).parent / "prompt.md"
    if prompt_path.exists():
        async with aiofiles.open(prompt_path, "r", encoding="utf-8") as f:
            return await f.read()
    return _get_default_prompt()


def _get_default_prompt() -> str:
    """默认提示词（当文件不存在时）"""
    return "你是一个专业的代码分析助手..."


async def execute(args: dict[str, Any], context: dict[str, Any]) -> str:
    """执行 code_analysis_agent"""
    user_prompt: str = args.get("prompt", "")

    if not user_prompt:
        return "请提供您的分析需求"

    agent_tools_dir: Path = Path(__file__).parent / "tools"
    tool_registry = AgentToolRegistry(agent_tools_dir)

    tools: list[dict[str, Any]] = tool_registry.get_tools_schema()

    ai_client = context.get("ai_client")
    if not ai_client:
        return "AI client 未在上下文中提供"

    agent_config = ai_client.agent_config

    system_prompt: str = await _load_prompt()
    agent_history = context.get("agent_history", [])

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
    ]

    if agent_history:
        messages.extend(agent_history)

    messages.append({"role": "user", "content": f"用户需求：{user_prompt}"})

    max_iterations: int = 20
    iteration: int = 0
    conversation_ended: bool = False

    while iteration < max_iterations and not conversation_ended:
        iteration += 1

        try:
            result = await ai_client.request_model(
                model_config=agent_config,
                messages=messages,
                max_tokens=agent_config.max_tokens,
                call_type="agent:naga_code_analysis_agent",
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
                        str(k): str(v) for k, v in raw_api_to_internal.items()
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

            # 准备并发执行工具
            tool_tasks = []
            tool_call_ids = []
            tool_api_names: list[str] = []

            for tool_call in tool_calls:
                call_id: str = tool_call.get("id", "")
                function: dict[str, Any] = tool_call.get("function", {})
                api_function_name: str = function.get("name", "")
                raw_args = function.get("arguments")

                internal_function_name = api_to_internal.get(
                    api_function_name, api_function_name
                )

                logger.info("Agent 正在准备工具: %s", internal_function_name)

                function_args = parse_tool_arguments(
                    raw_args, logger=logger, tool_name=api_function_name
                )

                tool_call_ids.append(call_id)
                tool_api_names.append(api_function_name)
                tool_tasks.append(
                    tool_registry.execute_tool(
                        internal_function_name, function_args, context
                    )
                )

            # 并发执行
            if tool_tasks:
                logger.info(f"Agent 正在并发执行 {len(tool_tasks)} 个工具")
                results = await asyncio.gather(*tool_tasks, return_exceptions=True)

                for i, tool_result in enumerate(results):
                    call_id = tool_call_ids[i]
                    api_tool_name = tool_api_names[i]
                    content_str: str = ""
                    if isinstance(tool_result, Exception):
                        content_str = f"错误: {str(tool_result)}"
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

        except Exception as e:
            logger.exception(f"Agent 执行失败: {e}")
            return f"处理失败: {e}"

    return "达到最大迭代次数"
