"""Tool and agent execution helpers."""

from __future__ import annotations

import logging
import time
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from Undefined.context import RequestContext
from Undefined.skills.tools import ToolRegistry
from Undefined.skills.agents import AgentRegistry

logger = logging.getLogger(__name__)


class ToolManager:
    """Handle tool/agent schema and execution."""

    def __init__(
        self, tool_registry: ToolRegistry, agent_registry: AgentRegistry
    ) -> None:
        self.tool_registry = tool_registry
        self.agent_registry = agent_registry
        self._agent_mcp_registry_var: ContextVar[dict[str, Any] | None] = ContextVar(
            "agent_mcp_registry_var", default=None
        )

    def get_openai_tools(self) -> list[dict[str, Any]]:
        tools = self.tool_registry.get_tools_schema()
        agents = self.agent_registry.get_agents_schema()
        return tools + agents

    def merge_tools(
        self,
        base_tools: list[dict[str, Any]] | None,
        extra_tools: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not base_tools:
            return list(extra_tools)

        merged = list(base_tools)
        existing_names = {
            tool.get("function", {}).get("name")
            for tool in base_tools
            if tool.get("function")
        }
        for tool in extra_tools:
            name = tool.get("function", {}).get("name")
            if name and name not in existing_names:
                merged.append(tool)
                existing_names.add(name)
        return merged

    def maybe_merge_agent_tools(
        self,
        call_type: str,
        tools: list[dict[str, Any]] | None,
    ) -> list[dict[str, Any]] | None:
        if not call_type.startswith("agent:"):
            return tools

        agent_name = call_type.split("agent:", 1)[1]
        mcp_registry = self.get_active_agent_mcp_registry(agent_name)
        if mcp_registry:
            mcp_tools = mcp_registry.get_tools_schema()
            if mcp_tools:
                return self.merge_tools(tools, mcp_tools)
        return tools

    def get_active_agent_mcp_registry(self, agent_name: str) -> Any | None:
        registries = self._agent_mcp_registry_var.get()
        if registries:
            return registries.get(agent_name)
        return None

    def _get_agent_mcp_config_path(self, agent_name: str) -> Path | None:
        agent_dir = self.agent_registry.base_dir / agent_name
        mcp_path = agent_dir / "mcp.json"
        if mcp_path.exists():
            return mcp_path
        return None

    async def execute_tool(
        self,
        function_name: str,
        function_args: dict[str, Any],
        context: dict[str, Any],
    ) -> Any:
        """执行工具或 Agent。"""
        start_time = time.perf_counter()

        # 自动注入 RequestContext 资源
        ctx = RequestContext.current()
        if ctx:
            for key, value in ctx.get_resources().items():
                context.setdefault(key, value)
            if ctx.group_id is not None:
                context.setdefault("group_id", ctx.group_id)
            if ctx.user_id is not None:
                context.setdefault("user_id", ctx.user_id)
            if ctx.sender_id is not None:
                context.setdefault("sender_id", ctx.sender_id)
            context.setdefault("request_type", ctx.request_type)
            context.setdefault("request_id", ctx.request_id)

        agents_schema = self.agent_registry.get_agents_schema()
        agent_names = [s.get("function", {}).get("name") for s in agents_schema]
        is_agent = function_name in agent_names
        exec_type = "Agent" if is_agent else "Tool"

        logger.debug(f"[{exec_type}调用] 准备执行 {function_name}")

        try:
            if is_agent:
                mcp_registry = None
                registry_token = None
                mcp_config_path = self._get_agent_mcp_config_path(function_name)
                if mcp_config_path:
                    try:
                        from Undefined.mcp import MCPToolRegistry

                        mcp_registry = MCPToolRegistry(
                            config_path=mcp_config_path,
                            tool_name_strategy="mcp",
                        )
                        await mcp_registry.initialize()
                        current = self._agent_mcp_registry_var.get()
                        new_map = dict(current) if current else {}
                        new_map[function_name] = mcp_registry
                        registry_token = self._agent_mcp_registry_var.set(new_map)
                        logger.info(
                            f"[Agent MCP] {function_name} 加载了 {len(mcp_registry.get_tools_schema())} 个工具"
                        )
                    except Exception as exc:
                        logger.warning(f"[Agent MCP] {function_name} 初始化失败: {exc}")
                        mcp_registry = None
                        registry_token = None

                agent_histories = context.get("agent_histories", {})
                agent_history = agent_histories.get(function_name, [])

                agent_context = context.copy()
                agent_context["agent_history"] = agent_history
                agent_context["agent_name"] = function_name

                try:
                    result = await self.agent_registry.execute_agent(
                        function_name, function_args, agent_context
                    )
                finally:
                    if registry_token is not None:
                        self._agent_mcp_registry_var.reset(registry_token)
                    if mcp_registry:
                        await mcp_registry.close()

                agent_prompt = function_args.get("prompt", "")
                if agent_prompt and result:
                    agent_history.append({"role": "user", "content": agent_prompt})
                    agent_history.append({"role": "assistant", "content": str(result)})
                    agent_histories[function_name] = agent_history
            else:
                result = await self.tool_registry.execute_tool(
                    function_name, function_args, context
                )

            duration = time.perf_counter() - start_time
            res_summary = (
                str(result)[:100] + "..." if len(str(result)) > 100 else str(result)
            )
            logger.info(
                f"[{exec_type}结果] {function_name} 执行成功, 耗时={duration:.2f}s, 结果: {res_summary}"
            )
            return result
        except Exception as exc:
            duration = time.perf_counter() - start_time
            logger.error(
                f"[{exec_type}错误] {function_name} 执行失败, 耗时={duration:.2f}s, 错误: {exc}"
            )
            raise
