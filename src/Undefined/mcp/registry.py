"""MCP (Model Context Protocol) registry.

Responsible for loading MCP config, connecting MCP servers, and exposing tools.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, cast

logger = logging.getLogger(__name__)


class MCPToolRegistry:
    """MCP tool registry.

    Loads MCP config, connects MCP servers, and converts MCP tools to function schemas.
    """

    def __init__(
        self,
        config_path: str | Path | None = None,
        tool_name_strategy: str = "mcp",
    ) -> None:
        if config_path is None:
            import os

            config_path = os.getenv("MCP_CONFIG_PATH", "config/mcp.json")

        self.config_path: Path = Path(config_path)
        self.tool_name_strategy = tool_name_strategy
        self._tools_schema: List[Dict[str, Any]] = []
        self._tools_handlers: Dict[
            str, Callable[[Dict[str, Any], Dict[str, Any]], Awaitable[str]]
        ] = {}
        self._mcp_client: Any = None
        self._mcp_servers: Dict[str, Any] = {}
        self._is_initialized: bool = False

    def load_mcp_config(self) -> Dict[str, Any]:
        if not self.config_path.exists():
            logger.warning(f"MCP 配置文件不存在: {self.config_path}")
            return {"mcpServers": {}}

        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            logger.info(f"已加载 MCP 配置: {self.config_path}")
            return cast(Dict[str, Any], config)
        except json.JSONDecodeError as e:
            logger.error(f"MCP 配置文件格式错误: {e}")
            return {"mcpServers": {}}
        except Exception as e:
            logger.error(f"加载 MCP 配置失败: {e}")
            return {"mcpServers": {}}

    async def initialize(self) -> None:
        self._tools_schema = []
        self._tools_handlers = {}

        config = self.load_mcp_config()
        mcp_servers = config.get("mcpServers", {})

        if not mcp_servers:
            logger.info("未配置 MCP 服务器")
            self._is_initialized = True
            return

        if not isinstance(mcp_servers, dict):
            logger.error(
                f"MCP 配置格式错误: mcpServers 应该是一个对象（字典），实际类型为 {type(mcp_servers).__name__}。"
                '正确的格式: {"mcpServers": {"server_name": {"command": "...", "args": [...]}}}'
            )
            self._is_initialized = True
            return

        logger.info(f"开始初始化 {len(mcp_servers)} 个 MCP 服务器...")
        self._mcp_servers = mcp_servers

        try:
            from fastmcp import Client

            self._mcp_client = Client(config)
            await self._mcp_client.__aenter__()

            if not self._mcp_client.is_connected():
                logger.warning("无法连接到 MCP 服务器")
                self._is_initialized = True
                return

            tools = await self._mcp_client.list_tools()
            for tool in tools:
                await self._register_tool(tool)

            logger.info(f"MCP 工具集初始化完成，共加载 {len(tools)} 个工具")

        except ImportError:
            logger.error("fastmcp 库未安装，MCP 功能将不可用")
        except Exception as e:
            logger.exception(f"初始化 MCP 工具集失败: {e}")

        self._is_initialized = True

    async def _register_tool(self, tool: Any) -> None:
        try:
            tool_name = tool.name
            tool_description = tool.description or ""
            parameters = tool.inputSchema if hasattr(tool, "inputSchema") else {}

            if self.tool_name_strategy == "raw":
                original_tool_name = tool_name
                full_tool_name = tool_name
            else:
                server_name = None
                actual_tool_name = tool_name

                for name in self._mcp_servers.keys():
                    if tool_name.startswith(f"{name}_"):
                        server_name = name
                        actual_tool_name = tool_name[len(name) + 1 :]
                        break

                if server_name is None and len(self._mcp_servers) == 1:
                    server_name = list(self._mcp_servers.keys())[0]
                    original_tool_name = tool_name
                elif server_name:
                    original_tool_name = tool_name
                else:
                    original_tool_name = tool_name

                if server_name:
                    full_tool_name = f"mcp.{server_name}.{actual_tool_name}"
                else:
                    full_tool_name = f"mcp.{actual_tool_name}"

            schema = {
                "type": "function",
                "function": {
                    "name": full_tool_name,
                    "description": f"[MCP] {tool_description}",
                    "parameters": parameters,
                },
            }

            async def handler(args: Dict[str, Any], context: Dict[str, Any]) -> str:
                try:
                    result = await self._mcp_client.call_tool(original_tool_name, args)

                    if hasattr(result, "content") and result.content:
                        text_parts = []
                        for item in result.content:
                            if hasattr(item, "text"):
                                text_parts.append(item.text)
                        return "\n".join(text_parts) if text_parts else str(result)
                    return str(result)

                except Exception as e:
                    logger.exception(f"调用 MCP 工具 {full_tool_name} 失败: {e}")
                    return f"调用 MCP 工具失败: {str(e)}"

            self._tools_schema.append(schema)
            self._tools_handlers[full_tool_name] = handler

            logger.debug(
                f"已注册 MCP 工具: {full_tool_name} (原始: {original_tool_name})"
            )

        except Exception as e:
            logger.error(f"注册 MCP 工具失败 [{tool.name}]: {e}")

    def get_tools_schema(self) -> List[Dict[str, Any]]:
        return self._tools_schema

    async def execute_tool(
        self,
        tool_name: str,
        args: Dict[str, Any],
        context: Dict[str, Any],
    ) -> str:
        handler = self._tools_handlers.get(tool_name)
        if not handler:
            return f"未找到 MCP 工具: {tool_name}"

        try:
            start_time = asyncio.get_event_loop().time()
            result = await handler(args, context)
            duration = asyncio.get_event_loop().time() - start_time
            logger.info(f"[MCP工具执行] {tool_name} 耗时={duration:.4f}s")
            return str(result)
        except Exception as e:
            logger.exception(f"[MCP工具异常] 执行工具 {tool_name} 时出错")
            return f"执行 MCP 工具 {tool_name} 时出错: {str(e)}"

    async def close(self) -> None:
        logger.info("正在关闭 MCP 客户端连接...")
        if self._mcp_client:
            try:
                await self._mcp_client.__aexit__(None, None, None)
                logger.debug("已关闭 MCP 客户端连接")
            except Exception as e:
                logger.warning(f"关闭 MCP 客户端连接时出错: {e}")
        self._mcp_client = None
        logger.info("MCP 客户端连接已关闭")

    @property
    def is_initialized(self) -> bool:
        return self._is_initialized


MCPToolSetRegistry = MCPToolRegistry
