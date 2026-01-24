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
        self._mcp_client: Any = None
        self._mcp_servers: Dict[str, Any] = {}  # 保存服务器配置
        self._is_initialized: bool = False

    def load_mcp_config(self) -> Dict[str, Any]:
        """加载 MCP 配置文件

        返回:
            MCP 配置字典
        """
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
        """初始化 MCP 工具集

        加载配置，连接 MCP 服务器，获取工具列表并转换为 toolsets 格式。
        """
        self._tools_schema = []
        self._tools_handlers = {}

        config = self.load_mcp_config()
        mcp_servers = config.get("mcpServers", {})

        if not mcp_servers:
            logger.info("未配置 MCP 服务器")
            self._is_initialized = True
            return

        # FastMCP 配置格式: mcpServers 是一个对象，键为服务器名称，值为配置
        if not isinstance(mcp_servers, dict):
            logger.error(
                f"MCP 配置格式错误: mcpServers 应该是一个对象（字典），实际类型为 {type(mcp_servers).__name__}。"
                '正确的格式: {"mcpServers": {"server_name": {"command": "...", "args": [...]}}}'
            )
            self._is_initialized = True
            return

        logger.info(f"开始初始化 {len(mcp_servers)} 个 MCP 服务器...")

        # 保存服务器配置
        self._mcp_servers = mcp_servers

        try:
            # 延迟导入 fastmcp
            from fastmcp import Client

            # 创建客户端，传入完整配置
            self._mcp_client = Client(config)

            # 连接并初始化
            await self._mcp_client.__aenter__()

            if not self._mcp_client.is_connected():
                logger.warning("无法连接到 MCP 服务器")
                self._is_initialized = True
                return

            # 获取所有工具列表
            tools = await self._mcp_client.list_tools()

            # 转换每个工具为 toolsets 格式
            for tool in tools:
                await self._register_tool(tool)

            logger.info(f"MCP 工具集初始化完成，共加载 {len(tools)} 个工具")

        except ImportError:
            logger.error("fastmcp 库未安装，MCP 功能将不可用")
        except Exception as e:
            logger.exception(f"初始化 MCP 工具集失败: {e}")

        self._is_initialized = True

    async def _register_tool(self, tool: Any) -> None:
        """注册单个 MCP 工具

        参数:
            tool: MCP 工具对象
        """
        try:
            # 获取工具信息
            tool_name = tool.name
            tool_description = tool.description or ""

            # 构建工具参数 schema
            parameters = tool.inputSchema if hasattr(tool, "inputSchema") else {}

            # FastMCP 的行为：
            # - 单服务器：工具名不带前缀（如 resolve-library-id）
            # - 多服务器：工具名带服务器前缀（如 context7_resolve-library-id）
            server_name = None
            actual_tool_name = tool_name

            # 检查工具名是否包含服务器前缀
            for name in self._mcp_servers.keys():
                if tool_name.startswith(f"{name}_"):
                    server_name = name
                    # 提取实际的工具名（去掉服务器前缀）
                    actual_tool_name = tool_name[len(name) + 1 :]
                    break

            # 如果只有一个服务器且工具名没有前缀，使用该服务器名
            if server_name is None and len(self._mcp_servers) == 1:
                server_name = list(self._mcp_servers.keys())[0]
                # FastMCP 调用时使用原始工具名（不带前缀）
                original_tool_name = tool_name
            elif server_name:
                # 多服务器，工具名已包含前缀
                original_tool_name = tool_name
            else:
                # 无法确定服务器，直接使用原始工具名
                original_tool_name = tool_name

            # 构建完整的工具名称：mcp.{server_name}.{tool_name}
            if server_name:
                full_tool_name = f"mcp.{server_name}.{actual_tool_name}"
            else:
                full_tool_name = f"mcp.{actual_tool_name}"

            # 构建 OpenAI function calling 格式的 schema
            schema = {
                "type": "function",
                "function": {
                    "name": full_tool_name,
                    "description": f"[MCP] {tool_description}",
                    "parameters": parameters,
                },
            }

            # 创建异步处理器
            async def handler(args: Dict[str, Any], context: Dict[str, Any]) -> str:
                """MCP 工具处理器"""
                try:
                    # 调用 MCP 工具（使用 FastMCP 期望的工具名）
                    result = await self._mcp_client.call_tool(original_tool_name, args)

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

            logger.debug(
                f"已注册 MCP 工具: {full_tool_name} (原始: {original_tool_name})"
            )

        except Exception as e:
            logger.error(f"注册 MCP 工具失败 [{tool.name}]: {e}")

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
            tool_name: 工具名称（格式：mcp.{server_name}_{tool_name}）
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
        """关闭 MCP 客户端连接"""
        logger.info("正在关闭 MCP 客户端连接...")
        if self._mcp_client:
            try:
                # 手动调用 context manager 的退出方法
                await self._mcp_client.__aexit__(None, None, None)
                logger.debug("已关闭 MCP 客户端连接")
            except Exception as e:
                logger.warning(f"关闭 MCP 客户端连接时出错: {e}")
        self._mcp_client = None
        logger.info("MCP 客户端连接已关闭")

    @property
    def is_initialized(self) -> bool:
        """检查是否已初始化"""
        return self._is_initialized
