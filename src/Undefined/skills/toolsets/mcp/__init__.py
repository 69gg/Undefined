"""MCP (Model Context Protocol) 工具集注册表

将 MCP 服务器转换为 toolsets，使 AI 可以调用 MCP 提供的工具。
"""

import json
import logging
import asyncio
from pathlib import Path
from typing import Dict, Any, List, Callable, Awaitable, cast

logger = logging.getLogger(__name__)


class MCPToolSetRegistry:
    """MCP 工具集注册表

    负责加载 MCP 配置，连接 MCP 服务器，并将 MCP 工具转换为 toolsets 格式。
    """

    def __init__(self, config_path: str | Path | None = None) -> None:
        """
        初始化 MCP 工具集注册表。

        参数:
            config_path: MCP 配置文件路径。如果为 None，则尝试从环境变量读取。
        """
        if config_path is None:
            import os

            config_path = os.getenv("MCP_CONFIG_PATH", "config/mcp.json")

        self.config_path: Path = Path(config_path)
        self._tools_schema: List[Dict[str, Any]] = []
        self._tools_handlers: Dict[
            str, Callable[[Dict[str, Any], Dict[str, Any]], Awaitable[str]]
        ] = {}
        self._mcp_clients: Dict[str, Any] = {}  # server_name -> client
        self._server_tools: Dict[str, List[str]] = {}  # server_name -> tool_names
        self._is_initialized: bool = False

    def load_mcp_config(self) -> Dict[str, Any]:
        """加载 MCP 配置文件

        返回:
            MCP 配置字典
        """
        if not self.config_path.exists():
            logger.warning(f"MCP 配置文件不存在: {self.config_path}")
            return {"mcpServers": []}

        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            logger.info(f"已加载 MCP 配置: {self.config_path}")
            return cast(Dict[str, Any], config)
        except json.JSONDecodeError as e:
            logger.error(f"MCP 配置文件格式错误: {e}")
            return {"mcpServers": []}
        except Exception as e:
            logger.error(f"加载 MCP 配置失败: {e}")
            return {"mcpServers": []}

    async def initialize(self) -> None:
        """初始化 MCP 工具集

        加载配置，连接 MCP 服务器，获取工具列表并转换为 toolsets 格式。
        """
        self._tools_schema = []
        self._tools_handlers = {}
        self._mcp_clients = {}
        self._server_tools = {}

        config = self.load_mcp_config()
        servers = config.get("mcpServers", [])

        if not servers:
            logger.info("未配置 MCP 服务器")
            self._is_initialized = True
            return

        logger.info(f"开始初始化 {len(servers)} 个 MCP 服务器...")

        for server_config in servers:
            await self._initialize_server(server_config)

        total_tools = len(self._tools_handlers)
        logger.info(f"MCP 工具集初始化完成，共加载 {total_tools} 个工具")

        # 输出详细统计
        for server_name, tools in self._server_tools.items():
            logger.info(f"  - [{server_name}] ({len(tools)} 个): {', '.join(tools)}")

        self._is_initialized = True

    async def _initialize_server(self, server_config: Dict[str, Any]) -> None:
        """初始化单个 MCP 服务器

        参数:
            server_config: 服务器配置，包含 name、command、args 等字段
        """
        server_name = server_config.get("name")
        if not server_name:
            logger.error("MCP 服务器配置缺少 name 字段")
            return

        try:
            # 延迟导入 fastmcp
            from fastmcp import Client

            # 创建客户端
            client = Client(server_config)

            # 连接并初始化
            async with client:
                if not client.is_connected():
                    logger.warning(f"无法连接到 MCP 服务器: {server_name}")
                    return

                # 获取工具列表
                tools = await client.list_tools()

                # 保存客户端引用（用于后续调用）
                self._mcp_clients[server_name] = client
                self._server_tools[server_name] = []

                # 转换每个工具为 toolsets 格式
                for tool in tools:
                    await self._register_tool(server_name, tool, client)

                logger.info(
                    f"MCP 服务器 [{server_name}] 初始化成功，加载 {len(tools)} 个工具"
                )

        except ImportError:
            logger.error("fastmcp 库未安装，MCP 功能将不可用")
        except Exception as e:
            logger.exception(f"初始化 MCP 服务器 [{server_name}] 失败: {e}")

    async def _register_tool(
        self,
        server_name: str,
        tool: Any,
        client: Any,
    ) -> None:
        """注册单个 MCP 工具

        参数:
            server_name: 服务器名称
            tool: MCP 工具对象
            client: MCP 客户端实例
        """
        try:
            # 获取工具信息
            tool_name = tool.name
            tool_description = tool.description or ""

            # 构建工具参数 schema
            parameters = tool.inputSchema if hasattr(tool, "inputSchema") else {}

            # 构建完整的工具名称：mcp.{server_name}.{tool_name}
            full_tool_name = f"mcp.{server_name}.{tool_name}"

            # 构建 OpenAI function calling 格式的 schema
            schema = {
                "type": "function",
                "function": {
                    "name": full_tool_name,
                    "description": f"[MCP:{server_name}] {tool_description}",
                    "parameters": parameters,
                },
            }

            # 创建异步处理器
            async def handler(args: Dict[str, Any], context: Dict[str, Any]) -> str:
                """MCP 工具处理器"""
                try:
                    # 调用 MCP 工具
                    result = await client.call_tool(tool_name, args)

                    # 解析结果
                    if hasattr(result, "content") and result.content:
                        # 提取文本内容
                        text_parts = []
                        for item in result.content:
                            if hasattr(item, "text"):
                                text_parts.append(item.text)
                        return "\n".join(text_parts) if text_parts else str(result)
                    else:
                        return str(result)

                except Exception as e:
                    logger.exception(f"调用 MCP 工具 {full_tool_name} 失败: {e}")
                    return f"调用 MCP 工具失败: {str(e)}"

            # 注册工具
            self._tools_schema.append(schema)
            self._tools_handlers[full_tool_name] = handler
            self._server_tools[server_name].append(tool_name)

            logger.debug(f"已注册 MCP 工具: {full_tool_name}")

        except Exception as e:
            logger.error(f"注册 MCP 工具失败 [{server_name}/{tool.name}]: {e}")

    def get_tools_schema(self) -> List[Dict[str, Any]]:
        """获取所有 MCP 工具的 Schema"""
        return self._tools_schema

    async def execute_tool(
        self,
        tool_name: str,
        args: Dict[str, Any],
        context: Dict[str, Any],
    ) -> str:
        """执行指定的 MCP 工具

        参数:
            tool_name: 工具名称（格式：mcp.{server_name}.{tool_name}）
            args: 工具参数
            context: 执行上下文

        返回:
            工具执行结果
        """
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
        """关闭所有 MCP 客户端连接"""
        logger.info("正在关闭 MCP 客户端连接...")
        for server_name, client in self._mcp_clients.items():
            try:
                # fastmcp.Client 使用 context manager，连接会自动关闭
                logger.debug(f"已关闭 MCP 服务器 [{server_name}] 连接")
            except Exception as e:
                logger.warning(f"关闭 MCP 服务器 [{server_name}] 连接时出错: {e}")
        self._mcp_clients.clear()
        logger.info("MCP 客户端连接已全部关闭")

    @property
    def is_initialized(self) -> bool:
        """检查是否已初始化"""
        return self._is_initialized
