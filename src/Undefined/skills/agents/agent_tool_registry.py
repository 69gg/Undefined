import logging
from pathlib import Path
from typing import Any

from Undefined.skills.registry import BaseRegistry
from Undefined.utils.logging import redact_string

logger = logging.getLogger(__name__)


class AgentToolRegistry(BaseRegistry):
    """智能体(Agent)专用工具注册表

    支持加载本地工具以及 Agent 私有的 MCP (Model Context Protocol) 扩展工具。
    """

    def __init__(self, tools_dir: Path, mcp_config_path: Path | None = None) -> None:
        super().__init__(tools_dir, kind="agent_tool")
        self.mcp_config_path: Path | None = (
            mcp_config_path if mcp_config_path is None else Path(mcp_config_path)
        )
        self._mcp_registry: Any | None = None
        self._mcp_initialized: bool = False
        self.load_tools()

    def load_tools(self) -> None:
        self.load_items()

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
        if mode_text != "all":
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
                await send_message_callback(message, None)
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
