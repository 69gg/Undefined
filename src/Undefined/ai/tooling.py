"""工具与智能体执行辅助函数。"""

from __future__ import annotations

import logging
import time
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from Undefined.context import RequestContext
from Undefined.skills.agents import AgentRegistry
from Undefined.skills.anthropic_skills import AnthropicSkillRegistry
from Undefined.skills.tools import ToolRegistry
from Undefined.utils.logging import log_debug_json, redact_string

logger = logging.getLogger(__name__)


class ToolManager:
    """工具与智能体（Agent）执行管理器

    负责管理 OpenAI 格式的功能架构（Schema）生成的合并，并处理工具和 Agent 的具体执行过程。
    支持 MCP (Model Context Protocol) 工具的动态注入和上下文资源的自动分发。
    """

    def __init__(
        self,
        tool_registry: ToolRegistry,
        agent_registry: AgentRegistry,
        anthropic_skill_registry: AnthropicSkillRegistry | None = None,
    ) -> None:
        """初始化工具管理器

        参数:
            tool_registry: 标准工具注册中心
            agent_registry: Agent 注册中心
            anthropic_skill_registry: Anthropic Agent Skills 注册中心（可选）
        """
        self.tool_registry = tool_registry
        self.agent_registry = agent_registry
        self.anthropic_skill_registry = anthropic_skill_registry
        self._agent_mcp_registry_var: ContextVar[dict[str, Any] | None] = ContextVar(
            "agent_mcp_registry_var", default=None
        )

    def get_openai_tools(self) -> list[dict[str, Any]]:
        """获取所有已加载工具和 Agent 的 OpenAI 兼容工具定义列表"""
        tools = self.tool_registry.get_tools_schema()
        agents = self.agent_registry.get_agents_schema()
        combined = tools + agents

        # 合并 Anthropic Skills（如有）
        if self.anthropic_skill_registry and self.anthropic_skill_registry.has_skills():
            combined = combined + self.anthropic_skill_registry.get_tools_schema()

        return combined

    def merge_tools(
        self,
        base_tools: list[dict[str, Any]] | None,
        extra_tools: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """合并两组工具定义，根据函数名去重"""
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

    def _get_easter_egg_call_mode(self, context: dict[str, Any]) -> str:
        runtime_config = context.get("runtime_config")
        mode = getattr(runtime_config, "easter_egg_agent_call_message_mode", None)
        if runtime_config is None:
            try:
                from Undefined.config import get_config

                mode = get_config(strict=False).easter_egg_agent_call_message_mode
            except Exception:
                mode = None

        text = str(mode).strip().lower() if mode is not None else "none"
        return text if text in {"none", "agent", "tools", "all", "clean"} else "none"

    async def _maybe_send_call_easter_egg(
        self, called_name: str, *, is_agent: bool, context: dict[str, Any]
    ) -> None:
        mode = self._get_easter_egg_call_mode(context)

        if mode == "none":
            return

        if mode == "clean":
            if context.get("easter_egg_silent"):
                return
            if not is_agent and called_name in {"send_message", "end"}:
                return

        if is_agent:
            if mode not in {"agent", "tools", "all", "clean"}:
                return
        else:
            # 仅主 AI 调用 tool 才提示；Agent 内部工具不经过 ToolManager
            if mode not in {"tools", "all", "clean"}:
                return
            if context.get("agent_name"):
                return

        message = f"{called_name}，我调用你了，我要调用你了！"
        sender = context.get("sender")
        group_id = context.get("group_id")

        try:
            if sender and isinstance(group_id, int) and group_id > 0:
                await sender.send_group_message(group_id, message, mark_sent=False)
        except Exception as exc:
            logger.debug("[彩蛋] 发送提示消息失败: %s", redact_string(str(exc)))

    async def execute_tool(
        self,
        function_name: str,
        function_args: dict[str, Any],
        context: dict[str, Any],
    ) -> Any:
        """执行指定的工具或 Agent 项

        参数:
            function_name: 函数/Agent 名称
            function_args: 调用参数字典
            context: 执行上下文字典，会自动注入 RequestContext 中的资源

        返回:
            执行结果
        """
        start_time = time.perf_counter()

        runtime_config = context.get("runtime_config")
        if runtime_config is not None:
            nagaagent_mode_enabled = bool(
                getattr(runtime_config, "nagaagent_mode_enabled", False)
            )
            if (
                not nagaagent_mode_enabled
                and function_name == "naga_code_analysis_agent"
            ):
                return "该功能未启用"

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
        exec_type = "智能体" if is_agent else "工具"

        logger.debug("[%s调用] 准备执行: %s", exec_type, function_name)
        if logger.isEnabledFor(logging.DEBUG):
            log_debug_json(
                logger, f"[{exec_type}调用参数] {function_name}", function_args
            )
            logger.debug(
                "[%s调用上下文] %s",
                exec_type,
                ", ".join(sorted(context.keys())),
            )

        # Anthropic Skill tool 路由
        # 工具名格式: skills<delimiter><name>，如 skills-_-pdf-processing
        delimiter = (
            self.anthropic_skill_registry.dot_delimiter
            if self.anthropic_skill_registry
            else "-_-"
        )
        is_anthropic_skill = function_name.startswith(f"skills{delimiter}")

        try:
            if is_anthropic_skill:
                if self.anthropic_skill_registry:
                    result = await self.anthropic_skill_registry.execute_skill_tool(
                        function_name, function_args, context
                    )
                    duration = time.perf_counter() - start_time
                    logger.info(
                        "[Skill结果] %s 执行成功: elapsed=%.2fs result_len=%d",
                        function_name,
                        duration,
                        len(str(result)),
                    )
                    return result
                else:
                    return f"Anthropic Skills 功能未启用: {function_name}"

            if is_agent:
                await self._maybe_send_call_easter_egg(
                    function_name, is_agent=True, context=context
                )
                mcp_registry = None
                registry_token = None
                mcp_config_path = self._get_agent_mcp_config_path(function_name)
                if mcp_config_path:
                    logger.debug(
                        "[智能体MCP] %s 使用 MCP 配置: %s",
                        function_name,
                        mcp_config_path,
                    )
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
                            "[智能体MCP] %s 已加载工具: count=%s",
                            function_name,
                            len(mcp_registry.get_tools_schema()),
                        )
                    except Exception as exc:
                        logger.warning(
                            "[智能体MCP] %s 初始化失败: %s",
                            function_name,
                            exc,
                        )
                        mcp_registry = None
                        registry_token = None

                agent_histories = context.get("agent_histories", {})
                agent_history = agent_histories.get(function_name, [])
                logger.debug(
                    "[Agent历史] %s 历史长度: %s",
                    function_name,
                    len(agent_history),
                )

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
                await self._maybe_send_call_easter_egg(
                    function_name, is_agent=False, context=context
                )
                result = await self.tool_registry.execute_tool(
                    function_name, function_args, context
                )

            duration = time.perf_counter() - start_time
            result_text = redact_string(str(result))
            res_summary = (
                result_text[:100] + "..." if len(result_text) > 100 else result_text
            )
            logger.info(
                "[%s结果] %s 执行成功: elapsed=%.2fs result=%s",
                exec_type,
                function_name,
                duration,
                res_summary,
            )
            if logger.isEnabledFor(logging.DEBUG):
                log_debug_json(logger, f"[{exec_type}结果详情] {function_name}", result)
            return result
        except Exception as exc:
            duration = time.perf_counter() - start_time
            logger.error(
                "[%s错误] %s 执行失败: elapsed=%.2fs error=%s",
                exec_type,
                function_name,
                duration,
                redact_string(str(exc)),
            )
            raise
