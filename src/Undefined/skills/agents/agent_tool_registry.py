import copy
import json
import logging
from pathlib import Path
from typing import Any, Awaitable, Callable

from Undefined.skills.registry import BaseRegistry
from Undefined.utils.logging import redact_string

logger = logging.getLogger(__name__)


class AgentToolRegistry(BaseRegistry):
    """智能体(Agent)专用工具注册表

    支持加载本地工具以及 Agent 私有的 MCP (Model Context Protocol) 扩展工具。
    """

    def __init__(
        self,
        tools_dir: Path,
        mcp_config_path: Path | None = None,
        *,
        current_agent_name: str | None = None,
        is_main_agent: bool = False,
    ) -> None:
        super().__init__(tools_dir, kind="agent_tool")
        self.mcp_config_path: Path | None = (
            mcp_config_path if mcp_config_path is None else Path(mcp_config_path)
        )
        normalized_agent_name = (
            str(current_agent_name).strip() if current_agent_name is not None else ""
        )
        self.current_agent_name: str | None = normalized_agent_name or None
        self.is_main_agent: bool = bool(is_main_agent)
        self._mcp_registry: Any | None = None
        self._mcp_initialized: bool = False
        self.load_tools()

    def load_tools(self) -> None:
        """加载本地工具、可调用 agent 与可共享主工具。"""
        # 1. 加载本地工具（原有逻辑）
        self.load_items()

        # 2. 扫描并注册可调用的 agent
        callable_agents = self._scan_callable_agents()

        if not self.is_main_agent and not self.current_agent_name:
            logger.info(
                "[AgentToolRegistry] 未提供 current_agent_name，严格模式下不注册任何可调用 agent"
            )

        for agent_name, agent_dir, allowed_callers in callable_agents:
            if not self._is_callable_agent_visible(allowed_callers):
                logger.debug(
                    "[AgentToolRegistry] 当前 agent=%s 无权看到 call_%s，跳过注册",
                    self.current_agent_name,
                    agent_name,
                )
                continue

            # 读取 agent 的 config.json
            agent_config = self._load_agent_config(agent_dir)
            if not agent_config:
                logger.warning(f"无法读取 agent {agent_name} 的配置，跳过注册")
                continue

            # 创建工具 schema
            tool_schema = self._create_agent_tool_schema(agent_name, agent_config)

            # 创建 handler（带访问控制）
            handler = self._create_agent_call_handler(agent_name, allowed_callers)

            # 注册为外部工具
            tool_name = f"call_{agent_name}"
            self.register_external_item(tool_name, tool_schema, handler)

            # 记录允许的调用方
            callers_str = (
                ", ".join(allowed_callers)
                if "*" not in allowed_callers
                else "所有 agent"
            )
            logger.info(
                f"[AgentToolRegistry] 注册可调用 agent: {tool_name}，"
                f"允许调用方: {callers_str}"
            )

        # 3. 扫描并注册可共享的主 tools（skills/tools/*/callable.json）
        callable_main_tools = self._scan_callable_main_tools()
        for tool_name, tool_schema, allowed_callers in callable_main_tools:
            if not self._is_callable_agent_visible(allowed_callers):
                logger.debug(
                    "[AgentToolRegistry] 当前 agent=%s 无权看到共享工具 %s，跳过注册",
                    self.current_agent_name,
                    tool_name,
                )
                continue

            # 本地工具优先，避免改变既有行为
            if tool_name in self._items:
                logger.debug(
                    "[AgentToolRegistry] 共享工具 %s 与本地工具重名，保留本地实现",
                    tool_name,
                )
                continue

            handler = self._create_main_tool_proxy_handler(tool_name, allowed_callers)
            self.register_external_item(tool_name, copy.deepcopy(tool_schema), handler)

            callers_str = (
                ", ".join(allowed_callers)
                if "*" not in allowed_callers
                else "所有 agent"
            )
            logger.info(
                "[AgentToolRegistry] 注册共享主工具: %s，允许调用方: %s",
                tool_name,
                callers_str,
            )

    def _is_callable_agent_visible(self, allowed_callers: list[str]) -> bool:
        """判断目标 callable agent 是否应暴露给当前 agent。"""
        if self.is_main_agent:
            return True

        if not self.current_agent_name:
            return False

        return "*" in allowed_callers or self.current_agent_name in allowed_callers

    def _scan_callable_agents(self) -> list[tuple[str, Path, list[str]]]:
        """扫描所有可被调用的 agent

        返回：[(agent_name, agent_dir, allowed_callers), ...]
        """
        agents_root = self.base_dir.parent.parent
        if not agents_root.exists() or not agents_root.is_dir():
            return []

        callable_agents: list[tuple[str, Path, list[str]]] = []
        for agent_dir in agents_root.iterdir():
            if not agent_dir.is_dir():
                continue
            if agent_dir.name.startswith("_"):
                continue

            # 跳过当前 agent（避免自己调用自己）
            if agent_dir == self.base_dir.parent:
                continue

            callable_json = agent_dir / "callable.json"
            if not callable_json.exists():
                continue

            try:
                with open(callable_json, "r", encoding="utf-8") as f:
                    config = json.load(f)

                if not config.get("enabled", False):
                    continue

                # 读取允许的调用方列表
                allowed_callers = config.get("allowed_callers", [])
                if not isinstance(allowed_callers, list):
                    logger.warning(
                        f"{callable_json} 的 allowed_callers 必须是列表，跳过"
                    )
                    continue

                # 空列表表示不允许任何调用
                if not allowed_callers:
                    logger.info(f"{agent_dir.name} 的 allowed_callers 为空，跳过注册")
                    continue

                callable_agents.append((agent_dir.name, agent_dir, allowed_callers))
            except Exception as e:
                logger.warning(f"读取 {callable_json} 失败: {e}")
                continue

        return callable_agents

    def _find_skills_root(self) -> Path | None:
        """向上查找 skills 根目录。"""
        for candidate in (self.base_dir, *self.base_dir.parents):
            if candidate.name == "skills":
                return candidate
        return None

    def _scan_callable_main_tools(
        self,
    ) -> list[tuple[str, dict[str, Any], list[str]]]:
        """扫描可共享给 Agent 的主工具。

        配置位置：skills/tools/{tool_name}/callable.json
        返回：[(tool_name, tool_schema, allowed_callers), ...]
        """
        skills_root = self._find_skills_root()
        if not skills_root:
            logger.warning(
                "[AgentToolRegistry] 未找到 skills 根目录，跳过共享主工具扫描"
            )
            return []

        tools_root = skills_root / "tools"
        if not tools_root.exists() or not tools_root.is_dir():
            return []

        callable_tools: list[tuple[str, dict[str, Any], list[str]]] = []
        for tool_dir in tools_root.iterdir():
            if not tool_dir.is_dir():
                continue
            if tool_dir.name.startswith("_"):
                continue

            callable_json = tool_dir / "callable.json"
            if not callable_json.exists():
                continue

            config_path = tool_dir / "config.json"
            handler_path = tool_dir / "handler.py"
            if not config_path.exists() or not handler_path.exists():
                logger.warning(
                    "[AgentToolRegistry] 共享工具目录缺少 config.json 或 handler.py: %s",
                    tool_dir,
                )
                continue

            try:
                with open(callable_json, "r", encoding="utf-8") as f:
                    config = json.load(f)

                if not config.get("enabled", False):
                    continue

                allowed_callers = config.get("allowed_callers", [])
                if not isinstance(allowed_callers, list):
                    logger.warning(
                        "%s 的 allowed_callers 必须是列表，跳过",
                        callable_json,
                    )
                    continue

                if not allowed_callers:
                    logger.info(
                        "共享工具 %s 的 allowed_callers 为空，跳过注册",
                        tool_dir.name,
                    )
                    continue

                tool_schema = self._load_tool_config(config_path)
                if not tool_schema:
                    logger.warning("无法读取共享工具配置，跳过: %s", config_path)
                    continue

                tool_name = str(tool_schema.get("function", {}).get("name", "")).strip()
                if not tool_name:
                    logger.warning(
                        "共享工具配置缺少 function.name，跳过: %s", config_path
                    )
                    continue

                callable_tools.append((tool_name, tool_schema, allowed_callers))
            except Exception as e:
                logger.warning("读取 %s 失败: %s", callable_json, e)

        return callable_tools

    def _load_agent_config(self, agent_dir: Path) -> dict[str, Any] | None:
        """读取 agent 的 config.json

        返回：agent 的配置字典，失败返回 None
        """
        config_path = agent_dir / "config.json"
        if not config_path.exists():
            return None

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
                if isinstance(config, dict):
                    return config
                return None
        except Exception as e:
            logger.warning(f"读取 {config_path} 失败: {e}")
            return None

    def _load_tool_config(self, config_path: Path) -> dict[str, Any] | None:
        """读取主工具 config.json。"""
        if not config_path.exists():
            return None

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            if not isinstance(config, dict):
                return None
            function = config.get("function")
            if not isinstance(function, dict) or "name" not in function:
                return None
            return config
        except Exception as e:
            logger.warning("读取 %s 失败: %s", config_path, e)
            return None

    def _create_agent_tool_schema(
        self, agent_name: str, agent_config: dict[str, Any]
    ) -> dict[str, Any]:
        """为可调用的 agent 创建工具 schema

        参数：
            agent_name: agent 名称
            agent_config: agent 的 config.json 内容

        返回：工具 schema 字典
        """
        function_def = agent_config.get("function", {})
        agent_description = function_def.get("description", f"{agent_name} agent")
        agent_parameters = function_def.get(
            "parameters",
            {
                "type": "object",
                "properties": {"prompt": {"type": "string", "description": "任务描述"}},
                "required": ["prompt"],
            },
        )

        tool_name = f"call_{agent_name}"
        tool_description = f"调用 {agent_name}: {agent_description}"

        return {
            "type": "function",
            "function": {
                "name": tool_name,
                "description": tool_description,
                "parameters": agent_parameters,
            },
        }

    def _create_agent_call_handler(
        self, target_agent_name: str, allowed_callers: list[str]
    ) -> Callable[[dict[str, Any], dict[str, Any]], Awaitable[str]]:
        """创建一个通用的 agent 调用 handler，带访问控制

        参数：
            target_agent_name: 目标 agent 的名称
            allowed_callers: 允许调用的 agent 名称列表

        返回：异步 handler 函数
        """

        async def handler(args: dict[str, Any], context: dict[str, Any]) -> str:
            # 1. 检查调用方权限
            current_agent = context.get("agent_name")
            if not current_agent:
                return "错误：无法确定调用方 agent"

            # 检查是否在允许列表中
            if "*" not in allowed_callers and current_agent not in allowed_callers:
                logger.warning(
                    f"[AgentCall] {current_agent} 尝试调用 {target_agent_name}，但未被授权"
                )
                return f"错误：{current_agent} 无权调用 {target_agent_name}"

            # 2. 获取 AI client
            ai_client = context.get("ai_client")
            if not ai_client:
                return "错误：AI client 未在上下文中提供"

            if not hasattr(ai_client, "agent_registry"):
                return "错误：AI client 不支持 agent_registry"

            # 3. 调用目标 agent
            try:
                logger.info(
                    f"[AgentCall] {current_agent} 调用 {target_agent_name}，参数: {args}"
                )
                # 构造被调用方上下文，避免复用调用方身份与历史。
                callee_context = context.copy()
                callee_context["agent_name"] = target_agent_name

                agent_histories = context.get("agent_histories")
                if not isinstance(agent_histories, dict):
                    agent_histories = {}
                    context["agent_histories"] = agent_histories
                callee_history = agent_histories.get(target_agent_name, [])
                if not isinstance(callee_history, list):
                    callee_history = []
                    agent_histories[target_agent_name] = callee_history
                callee_context["agent_history"] = callee_history

                result = await ai_client.agent_registry.execute_agent(
                    target_agent_name, args, callee_context
                )
                agent_prompt = str(args.get("prompt", "")).strip()
                if agent_prompt and result:
                    callee_history.append({"role": "user", "content": agent_prompt})
                    callee_history.append({"role": "assistant", "content": str(result)})
                    agent_histories[target_agent_name] = callee_history
                return str(result)
            except Exception as e:
                logger.exception(f"调用 agent {target_agent_name} 失败")
                return f"调用 {target_agent_name} 失败: {e}"

        return handler

    def _create_main_tool_proxy_handler(
        self, target_tool_name: str, allowed_callers: list[str]
    ) -> Callable[[dict[str, Any], dict[str, Any]], Awaitable[str]]:
        """创建共享主工具代理 handler，带访问控制。"""

        async def handler(args: dict[str, Any], context: dict[str, Any]) -> str:
            current_agent = context.get("agent_name")
            if not current_agent:
                return "错误：无法确定调用方 agent"

            if "*" not in allowed_callers and current_agent not in allowed_callers:
                logger.warning(
                    "[SharedTool] %s 尝试调用 %s，但未被授权",
                    current_agent,
                    target_tool_name,
                )
                return f"错误：{current_agent} 无权调用共享工具 {target_tool_name}"

            ai_client = context.get("ai_client")
            if not ai_client:
                return "错误：AI client 未在上下文中提供"

            tool_registry = getattr(ai_client, "tool_registry", None)
            if tool_registry is None:
                return "错误：AI client 不支持 tool_registry"

            try:
                result = await tool_registry.execute_tool(
                    target_tool_name, args, context
                )
                return str(result)
            except Exception as e:
                logger.exception("调用共享主工具 %s 失败", target_tool_name)
                return f"调用共享工具 {target_tool_name} 失败: {e}"

        return handler

    async def initialize_mcp_tools(self) -> None:
        """异步初始化该 Agent 配置的私有 MCP 工具服务器

        若存在 mcp.json，将尝试加载并将其中的工具注册到当前 Agent 的可用列表中。
        """
        """按需初始化 agent 私有 MCP 工具"""
        if self._mcp_initialized:
            return

        self._mcp_initialized = True

        if not self.mcp_config_path or not self.mcp_config_path.exists():
            return

        try:
            from Undefined.mcp import MCPToolRegistry

            self._mcp_registry = MCPToolRegistry(
                config_path=self.mcp_config_path,
                tool_name_strategy="mcp",
            )
            await self._mcp_registry.initialize()

            for schema in self._mcp_registry.get_tools_schema():
                name = schema.get("function", {}).get("name", "")
                handler = self._mcp_registry._tools_handlers.get(name)
                if name and handler:
                    self.register_external_item(name, schema, handler)

            logger.info(
                f"Agent MCP tools loaded: {len(self._mcp_registry.get_tools_schema())}"
            )

        except ImportError as e:
            logger.warning(f"Agent MCP registry not available: {e}")
            self._mcp_registry = None
        except Exception as e:
            logger.exception(f"Failed to initialize agent MCP tools: {e}")
            self._mcp_registry = None

    def get_tools_schema(self) -> list[dict[str, Any]]:
        return self.get_schema()

    async def execute_tool(
        self, tool_name: str, args: dict[str, Any], context: dict[str, Any]
    ) -> str:
        """执行特定工具或回退到 MCP 注册中心进行查找

        参数:
            tool_name: 工具名称
            args: 调用参数
            context: 执行上下文

        返回:
            工具执行的输出文本
        """
        await self._maybe_send_agent_tool_call_easter_egg(tool_name, context)
        async with self._items_lock:
            item = self._items.get(tool_name)

        if not item:
            ai_client = context.get("ai_client")
            agent_name = context.get("agent_name")
            if (
                ai_client
                and agent_name
                and hasattr(ai_client, "get_active_agent_mcp_registry")
            ):
                registry = ai_client.get_active_agent_mcp_registry(agent_name)
                if registry:
                    logger.info(
                        "[agent_tool] %s 未命中本地工具，回退到 active MCP",
                        tool_name,
                    )
                    result = await registry.execute_tool(tool_name, args, context)
                    return str(result)

        if not item and self._mcp_registry:
            logger.info(
                "[agent_tool] %s 未命中本地工具，回退到 agent MCP",
                tool_name,
            )
            result = await self._mcp_registry.execute_tool(tool_name, args, context)
            return str(result)

        if item:
            logger.debug("[agent_tool] %s 命中本地工具", tool_name)
        return await self.execute(tool_name, args, context)

    async def _maybe_send_agent_tool_call_easter_egg(
        self, tool_name: str, context: dict[str, Any]
    ) -> None:
        agent_name = context.get("agent_name")
        if not agent_name:
            return

        runtime_config = context.get("runtime_config")
        mode = getattr(runtime_config, "easter_egg_agent_call_message_mode", None)
        if runtime_config is None:
            try:
                from Undefined.config import get_config

                mode = get_config(strict=False).easter_egg_agent_call_message_mode
            except Exception:
                mode = None

        mode_text = str(mode).strip().lower() if mode is not None else "none"
        if mode_text not in {"all", "clean"}:
            return

        if mode_text == "clean":
            if context.get("easter_egg_silent"):
                return
            if tool_name in {"send_message", "end"}:
                return

        message = f"{tool_name}，我调用你了，我要调用你了！"
        sender = context.get("sender")
        send_message_callback = context.get("send_message_callback")
        group_id = context.get("group_id")

        try:
            if sender and isinstance(group_id, int) and group_id > 0:
                await sender.send_group_message(group_id, message)
                return
            if send_message_callback:
                await send_message_callback(message)
        except Exception as exc:
            logger.debug("[彩蛋] 发送提示消息失败: %s", redact_string(str(exc)))

    async def close_mcp_tools(self) -> None:
        if self._mcp_registry:
            try:
                await self._mcp_registry.close()
            except Exception as e:
                logger.warning(f"Error closing agent MCP tools: {e}")
            finally:
                self._mcp_registry = None
