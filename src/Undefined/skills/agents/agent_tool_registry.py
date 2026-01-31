import logging
from pathlib import Path
from typing import Any

from Undefined.skills.registry import BaseRegistry

logger = logging.getLogger(__name__)


class AgentToolRegistry(BaseRegistry):
    """Agent 内部的工具注册表（支持 agent 私有 MCP 工具）"""

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
                    result = await registry.execute_tool(tool_name, args, context)
                    return str(result)

        if not item and self._mcp_registry:
            result = await self._mcp_registry.execute_tool(tool_name, args, context)
            return str(result)

        return await self.execute(tool_name, args, context)

    async def close_mcp_tools(self) -> None:
        if self._mcp_registry:
            try:
                await self._mcp_registry.close()
            except Exception as e:
                logger.warning(f"Error closing agent MCP tools: {e}")
            finally:
                self._mcp_registry = None
