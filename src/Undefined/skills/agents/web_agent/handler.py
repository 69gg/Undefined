from typing import Any, Dict, Callable
import importlib.util
import json
import asyncio
import aiofiles
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class AgentToolRegistry:
    """Agent 内部的工具注册表"""

    def __init__(self, tools_dir: Path) -> None:
        self.tools_dir: Path = (
            tools_dir if isinstance(tools_dir, Path) else Path(tools_dir)
        )
        self._tools_schema: list[dict[str, Any]] = []
        self._tools_handlers: dict[str, Callable[..., Any]] = {}
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

    def get_tools_schema(self) -> list[dict[str, Any]]:
        """获取工具 schema"""
        return self._tools_schema

    async def execute_tool(
        self, tool_name: str, args: dict[str, Any], context: dict[str, Any]
    ) -> str:
        """执行工具"""
        handler = self._tools_handlers.get(tool_name)
        if not handler:
            return f"Tool not found: {tool_name}"

        try:
            if asyncio.iscoroutinefunction(handler):
                result = await handler(args, context)
            else:
                result = handler(args, context)
            return str(result)
        except Exception as e:
            logger.exception(f"Error executing tool {tool_name}")
            return f"Error executing tool {tool_name}: {str(e)}"


async def _load_prompt() -> str:
    """从 prompt.md 文件加载系统提示词"""
    prompt_path: Path = Path(__file__).parent / "prompt.md"
    if prompt_path.exists():
        async with aiofiles.open(prompt_path, "r", encoding="utf-8") as f:
            return await f.read()
    return _get_default_prompt()


def _get_default_prompt() -> str:
    """默认提示词"""
    return "你是一个网络搜索助手..."


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    """执行 web_agent"""
    user_prompt: str = args.get("prompt", "")

    if not user_prompt:
        return "请提供您的搜索需求"

    agent_tools_dir: Path = Path(__file__).parent / "tools"
    tool_registry = AgentToolRegistry(agent_tools_dir)

    tools: list[dict[str, Any]] = tool_registry.get_tools_schema()

    ai_client = context.get("ai_client")
    if not ai_client:
        return "AI client 未在上下文中提供"

    agent_config = ai_client.agent_config

    system_prompt: str = await _load_prompt()

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"用户需求：{user_prompt}"},
    ]

    max_iterations: int = 20
    iteration: int = 0

    while iteration < max_iterations:
        iteration += 1

        try:
            response = await ai_client._http_client.post(
                agent_config.api_url,
                headers={
                    "Authorization": f"Bearer {agent_config.api_key}",
                    "Content-Type": "application/json",
                },
                json=ai_client._build_request_body(
                    model_config=agent_config,
                    messages=messages,
                    max_tokens=agent_config.max_tokens,
                    tools=tools if tools else None,
                    tool_choice="auto",
                ),
            )
            response.raise_for_status()
            result: dict[str, Any] = response.json()

            choice: dict[str, Any] = result.get("choices", [{}])[0]
            message: dict[str, Any] = choice.get("message", {})
            content: str = message.get("content") or ""
            tool_calls: list[dict[str, Any]] = message.get("tool_calls", [])

            if content.strip() and tool_calls:
                content = ""

            if not tool_calls:
                return content

            messages.append(
                {"role": "assistant", "content": content, "tool_calls": tool_calls}
            )

            # 准备并发执行工具
            tool_tasks = []
            tool_call_ids = []

            for tool_call in tool_calls:
                call_id: str = tool_call.get("id", "")
                function: dict[str, Any] = tool_call.get("function", {})
                function_name: str = function.get("name", "")
                function_args_str: str = function.get("arguments", "{}")

                logger.info(f"Agent preparing tool: {function_name}")

                try:
                    function_args: dict[str, Any] = json.loads(function_args_str)
                except json.JSONDecodeError:
                    function_args = {}

                tool_call_ids.append(call_id)
                tool_tasks.append(
                    tool_registry.execute_tool(function_name, function_args, context)
                )

            # 并发执行
            if tool_tasks:
                logger.info(f"Agent executing {len(tool_tasks)} tools in parallel")
                results = await asyncio.gather(*tool_tasks, return_exceptions=True)

                for i, tool_result in enumerate(results):
                    call_id = tool_call_ids[i]
                    content_str: str = ""
                    if isinstance(tool_result, Exception):
                        content_str = f"Error: {str(tool_result)}"
                    else:
                        content_str = str(tool_result)

                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call_id,
                            "content": content_str,
                        }
                    )

        except Exception as e:
            logger.exception(f"Agent execution failed: {e}")
            return f"处理失败: {e}"

    return "达到最大迭代次数"
