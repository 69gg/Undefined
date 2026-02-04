"""MCP (Model Context Protocol) registry.

Responsible for loading MCP config, connecting MCP servers, and exposing tools.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, cast

from Undefined.utils.logging import format_log_payload, log_debug_json
from Undefined.config import get_config

logger = logging.getLogger(__name__)


class MCPToolRegistry:
    """MCP (Model Context Protocol) 工具注册中心

    负责加载 MCP 配置文件，连接并管理 MCP 服务器，并将 MCP 工具转换为标准函数架构。
    """

    def __init__(
        self,
        config_path: str | Path | None = None,
        tool_name_strategy: str = "mcp",
    ) -> None:
        if config_path is None:
            try:
                config_path = get_config(strict=False).mcp_config_path
            except Exception:
                config_path = "config/mcp.json"

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
        """从本地文件加载 MCP 服务器配置

        返回:
            包含 mcpServers 定义的字典
        """
        if not self.config_path.exists():
            logger.warning(f"MCP 配置文件不存在: {self.config_path}")
            return {"mcpServers": {}}

        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            logger.info(f"已加载 MCP 配置: {self.config_path}")
            if logger.isEnabledFor(logging.DEBUG):
                log_debug_json(logger, "[MCP配置]", config)
            return cast(Dict[str, Any], config)
        except json.JSONDecodeError as e:
            logger.error(f"MCP 配置文件格式错误: {e}")
            return {"mcpServers": {}}
        except Exception as e:
            logger.error(f"加载 MCP 配置失败: {e}")
            return {"mcpServers": {}}

    async def initialize(self) -> None:
        """初始化 MCP 客户端并连接所有已配置的服务器列表

        此过程会通过 fastmcp 库连接远端服务并拉取工具定义。
        """
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
        if logger.isEnabledFor(logging.DEBUG):
            log_debug_json(logger, "[MCP服务器列表]", list(mcp_servers.keys()))

        try:
            from fastmcp import Client

            self._mcp_client = Client(config)
            await self._mcp_client.__aenter__()

            if not self._mcp_client.is_connected():
                logger.warning("无法连接到 MCP 服务器")
                self._is_initialized = True
                return

            tools = await self._mcp_client.list_tools()
            if logger.isEnabledFor(logging.DEBUG):
                log_debug_json(logger, "[MCP工具列表]", [t.name for t in tools])
            for tool in tools:
                await self._register_tool(tool)

            logger.info(f"MCP 工具集初始化完成，共加载 {len(tools)} 个工具")

        except ImportError:
            logger.error("fastmcp 库未安装，MCP 功能将不可用")
        except Exception as e:
            logger.exception(f"初始化 MCP 工具集失败: {e}")

        self._is_initialized = True

    async def _register_tool(self, tool: Any) -> None:
        """将单个 MCP 工具注册到本地表并生成执行处理器

        此方法会将 MCP 工具名根据策略(strategy)进行命名空间转换。
        """
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
                    if logger.isEnabledFor(logging.DEBUG):
                        log_debug_json(
                            logger,
                            f"[MCP调用参数] {full_tool_name}",
                            args,
                        )
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
        """获取所有已加载 MCP 工具的 OpenAI 兼容架构定义列表"""
        return self._tools_schema

    async def execute_tool(
        self,
        tool_name: str,
        args: Dict[str, Any],
        context: Dict[str, Any],
    ) -> str:
        """执行指定的 MCP 工具

        参数:
            tool_name: 转换后的工具命名空间全名 (如 'mcp.server.tool')
            args: 调用参数
            context: 执行上下文

        返回:
            工具返回的文本内容或错误说明
        """
        handler = self._tools_handlers.get(tool_name)
        if not handler:
            if logger.isEnabledFor(logging.INFO):
                logger.info(
                    "[MCP工具调用] %s 参数=%s",
                    tool_name,
                    format_log_payload(args),
                )
                logger.info(
                    "[MCP工具返回] %s 结果=%s",
                    tool_name,
                    format_log_payload(f"未找到 MCP 工具: {tool_name}"),
                )
            return f"未找到 MCP 工具: {tool_name}"

        try:
            if logger.isEnabledFor(logging.INFO):
                logger.info(
                    "[MCP工具调用] %s 参数=%s",
                    tool_name,
                    format_log_payload(args),
                )
            start_time = asyncio.get_event_loop().time()
            result = await handler(args, context)
            duration = asyncio.get_event_loop().time() - start_time
            logger.info(f"[MCP工具执行] {tool_name} 耗时={duration:.4f}s")
            if logger.isEnabledFor(logging.DEBUG):
                log_debug_json(logger, f"[MCP工具结果] {tool_name}", result)
            if logger.isEnabledFor(logging.INFO):
                logger.info(
                    "[MCP工具返回] %s 结果=%s",
                    tool_name,
                    format_log_payload(result),
                )
            return str(result)
        except Exception as e:
            logger.exception(f"[MCP工具异常] 执行工具 {tool_name} 时出错")
            error_text = f"执行 MCP 工具 {tool_name} 时出错: {str(e)}"
            if logger.isEnabledFor(logging.INFO):
                logger.info(
                    "[MCP工具返回] %s 结果=%s",
                    tool_name,
                    format_log_payload(error_text),
                )
            return error_text

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
