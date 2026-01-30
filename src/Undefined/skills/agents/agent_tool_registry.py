import asyncio
import importlib.util
import json
import logging
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)


class AgentToolRegistry:
    """Agent 内部的工具注册表（支持 agent 私有 MCP 工具）"""

    def __init__(self, tools_dir: Path, mcp_config_path: Path | None = None) -> None:
        self.tools_dir: Path = (
            tools_dir if isinstance(tools_dir, Path) else Path(tools_dir)
        )
        self.mcp_config_path: Path | None = (
            mcp_config_path if mcp_config_path is None else Path(mcp_config_path)
        )
        self._tools_schema: list[dict[str, Any]] = []
        self._tools_handlers: dict[str, Callable[..., Any]] = {}
        self._mcp_registry: Any | None = None
        self._mcp_initialized: bool = False
        self.load_tools()

    def load_tools(self) -> None:
        """加载 agent 专属工具"""
        if not self.tools_dir.exists():
            logger.warning(f"Agent tools directory does not exist: {self.tools_dir}")
            return

        for item in self.tools_dir.iterdir():
            if item.is_dir() and not item.name.startswith("_"):
                self._load_tool_from_dir(item)

        logger.info(
            f"Agent loaded {len(self._tools_schema)} tools: {list(self._tools_handlers.keys())}"
        )

    def _load_tool_from_dir(self, tool_dir: Path) -> None:
        """从目录加载工具"""
        config_path: Path = tool_dir / "config.json"
        handler_path: Path = tool_dir / "handler.py"

        if not config_path.exists() or not handler_path.exists():
            return

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config: dict[str, Any] = json.load(f)

            if "function" not in config or "name" not in config.get("function", {}):
                return

            tool_name: str = config["function"]["name"]

            spec = importlib.util.spec_from_file_location(
                f"agent_tools.{tool_name}", handler_path
            )
            if spec is None or spec.loader is None:
                return

            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            if not hasattr(module, "execute"):
                return

            self._tools_schema.append(config)
            self._tools_handlers[tool_name] = module.execute

        except Exception as e:
            logger.error(f"Failed to load tool from {tool_dir}: {e}")

    async def initialize_mcp_tools(self) -> None:
        """按需初始化 agent 私有 MCP 工具"""
        if self._mcp_initialized:
            return

        self._mcp_initialized = True

        if not self.mcp_config_path or not self.mcp_config_path.exists():
            return

        try:
            from ..toolsets.mcp import MCPToolSetRegistry

            self._mcp_registry = MCPToolSetRegistry(
                config_path=self.mcp_config_path,
                tool_name_strategy="mcp",
            )
            await self._mcp_registry.initialize()

            for schema in self._mcp_registry.get_tools_schema():
                self._tools_schema.append(schema)

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
        """获取工具 schema（包含 agent 私有 MCP 工具）"""
        return self._tools_schema

    async def execute_tool(
        self, tool_name: str, args: dict[str, Any], context: dict[str, Any]
    ) -> str:
        """执行工具"""
        handler = self._tools_handlers.get(tool_name)
        if handler:
            try:
                if asyncio.iscoroutinefunction(handler):
                    result = await handler(args, context)
                else:
                    result = handler(args, context)
                return str(result)
            except Exception as e:
                logger.exception(f"Error executing tool {tool_name}")
                return f"Error executing tool {tool_name}: {str(e)}"

        if self._mcp_registry:
            result = await self._mcp_registry.execute_tool(tool_name, args, context)
            return str(result)

        return f"Tool not found: {tool_name}"

    async def close_mcp_tools(self) -> None:
        """关闭 agent 私有 MCP 客户端"""
        if self._mcp_registry:
            try:
                await self._mcp_registry.close()
            except Exception as e:
                logger.warning(f"Error closing agent MCP tools: {e}")
            finally:
                self._mcp_registry = None
