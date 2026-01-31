"""AI client entry point."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import logging
import os
from collections import deque
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

import httpx

from Undefined.ai.http import ModelRequester
from Undefined.ai.multimodal import MultimodalAnalyzer
from Undefined.ai.prompts import PromptBuilder
from Undefined.ai.summaries import SummaryService
from Undefined.ai.tokens import TokenCounter
from Undefined.ai.tooling import ToolManager
from Undefined.config import ChatModelConfig, VisionModelConfig, AgentModelConfig
from Undefined.context import RequestContext
from Undefined.context_resource_registry import set_context_resource_scan_paths
from Undefined.end_summary_storage import EndSummaryStorage
from Undefined.memory import MemoryStorage
from Undefined.skills.agents import AgentRegistry
from Undefined.skills.agents.intro_generator import (
    AgentIntroGenConfig,
    AgentIntroGenerator,
)
from Undefined.skills.tools import ToolRegistry
from Undefined.token_usage_storage import TokenUsageStorage
from Undefined.utils.logging import log_debug_json, redact_string

logger = logging.getLogger(__name__)


# 尝试导入 langchain SearxSearchWrapper
try:
    from langchain_community.utilities import SearxSearchWrapper

    _SEARX_AVAILABLE = True
except Exception:
    _SEARX_AVAILABLE = False
    logger.warning(
        "langchain_community 未安装或 SearxSearchWrapper 不可用，搜索功能将禁用"
    )

# 尝试导入 crawl4ai
try:
    importlib.util.find_spec("crawl4ai")
    _CRAWL4AI_AVAILABLE = True
    try:
        _PROXY_CONFIG_AVAILABLE = True
    except (ImportError, AttributeError):
        _PROXY_CONFIG_AVAILABLE = False
except Exception:
    _CRAWL4AI_AVAILABLE = False
    _PROXY_CONFIG_AVAILABLE = False
    logger.warning("crawl4ai 未安装，网页获取功能将禁用")


class AIClient:
    """AI 模型客户端"""

    def __init__(
        self,
        chat_config: ChatModelConfig,
        vision_config: VisionModelConfig,
        agent_config: AgentModelConfig,
        memory_storage: Optional[MemoryStorage] = None,
        end_summary_storage: Optional[EndSummaryStorage] = None,
        bot_qq: int = 0,
    ) -> None:
        self.chat_config = chat_config
        self.vision_config = vision_config
        self.agent_config = agent_config
        self.bot_qq = bot_qq
        self.memory_storage = memory_storage
        self._end_summary_storage = end_summary_storage or EndSummaryStorage()

        self._http_client = httpx.AsyncClient(timeout=120.0)
        self._token_usage_storage = TokenUsageStorage()
        self._requester = ModelRequester(self._http_client, self._token_usage_storage)
        self._token_counter = TokenCounter()

        # 记录最近发送的 50 条消息内容，用于去重
        self.recent_replies: deque[str] = deque(maxlen=50)

        # 私聊发送回调
        self._send_private_message_callback: Optional[
            Callable[[int, str], Awaitable[None]]
        ] = None
        # 发送图片回调
        self._send_image_callback: Optional[
            Callable[[int, str, str], Awaitable[None]]
        ] = None

        # 当前群聊ID和用户ID（用于send_message工具）
        self.current_group_id: Optional[int] = None
        self.current_user_id: Optional[int] = None

        # 初始化工具注册表
        base_dir = Path(__file__).resolve().parents[1]
        self.tool_registry = ToolRegistry(base_dir / "skills" / "tools")
        self.agent_registry = AgentRegistry(base_dir / "skills" / "agents")
        self.tool_manager = ToolManager(self.tool_registry, self.agent_registry)

        # 绑定上下文资源扫描路径（基于注册表 watch_paths）
        scan_paths = [
            p
            for p in (
                self.tool_registry._watch_paths + self.agent_registry._watch_paths
            )
            if p.exists()
        ]
        set_context_resource_scan_paths(scan_paths)

        # 启动 Agent intro 自动生成
        intro_autogen_enabled = os.getenv(
            "AGENT_INTRO_AUTOGEN_ENABLED", "true"
        ).lower() not in {"0", "false", "no"}
        try:
            intro_queue_interval = float(
                os.getenv("AGENT_INTRO_AUTOGEN_QUEUE_INTERVAL", "1.0")
            )
        except ValueError:
            intro_queue_interval = 1.0
        try:
            intro_max_tokens = int(os.getenv("AGENT_INTRO_AUTOGEN_MAX_TOKENS", "700"))
        except ValueError:
            intro_max_tokens = 700
        intro_cache_path = Path(
            os.getenv("AGENT_INTRO_HASH_PATH", ".cache/agent_intro_hashes.json")
        )
        self._agent_intro_generator = AgentIntroGenerator(
            self.agent_registry.base_dir,
            self,
            AgentIntroGenConfig(
                enabled=intro_autogen_enabled,
                queue_interval_seconds=intro_queue_interval,
                max_tokens=intro_max_tokens,
                cache_path=intro_cache_path,
            ),
        )
        self._agent_intro_task = asyncio.create_task(
            self._agent_intro_generator.start()
        )

        # 启动 skills 热重载
        hot_reload_enabled = os.getenv("SKILLS_HOT_RELOAD", "true").lower() not in {
            "0",
            "false",
            "no",
        }
        if hot_reload_enabled:
            try:
                interval = float(os.getenv("SKILLS_HOT_RELOAD_INTERVAL", "2.0"))
                debounce = float(os.getenv("SKILLS_HOT_RELOAD_DEBOUNCE", "0.5"))
            except ValueError:
                interval = 2.0
                debounce = 0.5
            self.tool_registry.start_hot_reload(interval=interval, debounce=debounce)
            self.agent_registry.start_hot_reload(interval=interval, debounce=debounce)

        # 初始化搜索 wrapper
        self._search_wrapper: Optional[Any] = None
        if _SEARX_AVAILABLE:
            searxng_url = os.getenv("SEARXNG_URL", "")
            if searxng_url:
                try:
                    self._search_wrapper = SearxSearchWrapper(
                        searx_host=searxng_url, k=10
                    )
                    logger.info(
                        f"[初始化] SearxSearchWrapper 初始化成功，URL: {redact_string(searxng_url)}"
                    )
                except Exception as exc:
                    logger.warning(f"SearxSearchWrapper 初始化失败: {exc}")
            else:
                logger.info("SEARXNG_URL 未配置，搜索功能禁用")

        if _CRAWL4AI_AVAILABLE:
            logger.info("crawl4ai 可用，网页获取功能已启用")
        else:
            logger.warning("crawl4ai 不可用，网页获取功能将禁用")

        self._prompt_builder = PromptBuilder(
            bot_qq=self.bot_qq,
            memory_storage=self.memory_storage,
            end_summary_storage=self._end_summary_storage,
        )
        self._multimodal = MultimodalAnalyzer(self._requester, self.vision_config)
        self._summary_service = SummaryService(
            self._requester, self.chat_config, self._token_counter
        )

        async def init_mcp_async() -> None:
            try:
                await self.tool_registry.initialize_mcp_toolsets()
            except Exception as exc:
                logger.warning(f"异步初始化 MCP 工具集失败: {exc}")

        self._mcp_init_task = asyncio.create_task(init_mcp_async())

        logger.info("[初始化] AIClient 初始化完成")

    async def close(self) -> None:
        logger.info("[清理] 正在关闭 AIClient HTTP 客户端...")
        await self._http_client.aclose()

        if hasattr(self, "tool_registry"):
            await self.tool_registry.close_mcp_toolsets()
            await self.tool_registry.stop_hot_reload()
        if hasattr(self, "agent_registry"):
            await self.agent_registry.stop_hot_reload()

        if hasattr(self, "_mcp_init_task") and not self._mcp_init_task.done():
            await self._mcp_init_task
        if hasattr(self, "_agent_intro_task") and self._agent_intro_task:
            if not self._agent_intro_task.done():
                await self._agent_intro_task

        logger.info("[清理] AIClient 已关闭")

    def count_tokens(self, text: str) -> int:
        return self._token_counter.count(text)

    async def request_model(
        self,
        model_config: ChatModelConfig | VisionModelConfig | AgentModelConfig,
        messages: list[dict[str, Any]],
        max_tokens: int = 8192,
        call_type: str = "chat",
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str = "auto",
        **kwargs: Any,
    ) -> dict[str, Any]:
        tools = self.tool_manager.maybe_merge_agent_tools(call_type, tools)
        return await self._requester.request(
            model_config=model_config,
            messages=messages,
            max_tokens=max_tokens,
            call_type=call_type,
            tools=tools,
            tool_choice=tool_choice,
            **kwargs,
        )

    def get_active_agent_mcp_registry(self, agent_name: str) -> Any | None:
        return self.tool_manager.get_active_agent_mcp_registry(agent_name)

    async def analyze_multimodal(
        self,
        media_url: str,
        media_type: str = "auto",
        prompt_extra: str = "",
    ) -> dict[str, str]:
        return await self._multimodal.analyze(media_url, media_type, prompt_extra)

    async def describe_image(
        self, image_url: str, prompt_extra: str = ""
    ) -> dict[str, str]:
        return await self._multimodal.describe_image(image_url, prompt_extra)

    async def summarize_chat(self, messages: str, context: str = "") -> str:
        return await self._summary_service.summarize_chat(messages, context)

    async def merge_summaries(self, summaries: list[str]) -> str:
        return await self._summary_service.merge_summaries(summaries)

    def split_messages_by_tokens(self, messages: str, max_tokens: int) -> list[str]:
        return self._summary_service.split_messages_by_tokens(messages, max_tokens)

    async def generate_title(self, summary: str) -> str:
        return await self._summary_service.generate_title(summary)

    async def ask(
        self,
        question: str,
        context: str = "",
        send_message_callback: Callable[[str, int | None], Awaitable[None]]
        | None = None,
        get_recent_messages_callback: Callable[
            [str, str, int, int], Awaitable[list[dict[str, Any]]]
        ]
        | None = None,
        get_image_url_callback: Callable[[str], Awaitable[str | None]] | None = None,
        get_forward_msg_callback: Callable[[str], Awaitable[list[dict[str, Any]]]]
        | None = None,
        send_like_callback: Callable[[int, int], Awaitable[None]] | None = None,
        sender: Any = None,
        history_manager: Any = None,
        onebot_client: Any = None,
        scheduler: Any = None,
        extra_context: dict[str, Any] | None = None,
    ) -> str:
        messages = await self._prompt_builder.build_messages(
            question,
            get_recent_messages_callback=get_recent_messages_callback,
            extra_context=extra_context,
        )

        tools = self.tool_manager.get_openai_tools()
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "[AI消息] 构建完成: messages=%s tools=%s question_len=%s",
                len(messages),
                len(tools),
                len(question),
            )
            log_debug_json(logger, "[AI消息内容]", messages)

        ctx = RequestContext.current()
        tool_context = ctx.get_resources() if ctx else {}
        tool_context["conversation_ended"] = False
        tool_context.setdefault("agent_histories", {})

        if extra_context:
            tool_context.update(extra_context)

        # 注入常用资源（用于工具执行）
        tool_context.setdefault("ai_client", self)
        tool_context.setdefault("search_wrapper", self._search_wrapper)
        tool_context.setdefault("recent_replies", self.recent_replies)
        tool_context.setdefault(
            "send_private_message_callback", self._send_private_message_callback
        )
        tool_context.setdefault("send_image_callback", self._send_image_callback)

        max_iterations = 1000
        iteration = 0
        conversation_ended = False

        while iteration < max_iterations:
            iteration += 1
            logger.info(f"[AI决策] 开始第 {iteration} 轮迭代...")

            try:
                result = await self.request_model(
                    model_config=self.chat_config,
                    messages=messages,
                    max_tokens=8192,
                    call_type="chat",
                    tools=tools,
                    tool_choice="auto",
                )

                choice = result.get("choices", [{}])[0]
                message = choice.get("message", {})
                content: str = message.get("content") or ""
                tool_calls = message.get("tool_calls", [])
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "[AI响应] content_len=%s tool_calls=%s",
                        len(content),
                        len(tool_calls),
                    )
                    if tool_calls:
                        log_debug_json(logger, "[AI工具调用]", tool_calls)

                if content.strip() and tool_calls:
                    logger.debug(
                        "AI 在 content 中返回了内容且存在工具调用，忽略 content，只执行工具调用"
                    )
                    content = ""

                if not tool_calls:
                    logger.info(
                        f"[AI回复] 会话结束，返回最终内容 (长度={len(content)})"
                    )
                    return content

                messages.append(
                    {"role": "assistant", "content": content, "tool_calls": tool_calls}
                )

                tool_tasks = []
                tool_call_ids = []
                tool_names = []

                for tool_call in tool_calls:
                    call_id = tool_call.get("id", "")
                    function = tool_call.get("function", {})
                    function_name = function.get("name", "")
                    raw_args = function.get("arguments")

                    logger.info(f"[工具准备] 准备调用: {function_name} (ID={call_id})")
                    logger.debug(
                        f"[工具参数] {function_name} 参数: {redact_string(str(raw_args))}"
                    )

                    if isinstance(raw_args, dict):
                        function_args = raw_args
                    elif raw_args is None:
                        function_args = {}
                    elif isinstance(raw_args, str) and not raw_args.strip():
                        function_args = {}
                    else:
                        try:
                            function_args = json.loads(raw_args)
                        except json.JSONDecodeError as exc:
                            logger.error(
                                f"[工具错误] 参数解析失败: {raw_args}, 错误: {exc}"
                            )
                            function_args = {}

                    if not isinstance(function_args, dict):
                        function_args = {}

                    tool_call_ids.append(call_id)
                    tool_names.append(function_name)
                    tool_tasks.append(
                        self.tool_manager.execute_tool(
                            function_name, function_args, tool_context
                        )
                    )

                if tool_tasks:
                    logger.info(
                        f"[工具执行] 开始并发执行 {len(tool_tasks)} 个工具调用: {', '.join(tool_names)}"
                    )
                    tool_results = await asyncio.gather(
                        *tool_tasks, return_exceptions=True
                    )

                    for i, tool_result in enumerate(tool_results):
                        call_id = tool_call_ids[i]
                        fname = tool_names[i]

                        if isinstance(tool_result, Exception):
                            logger.error(
                                f"[工具异常] {fname} (ID={call_id}) 执行抛出异常: {tool_result}"
                            )
                            content_str = f"执行失败: {str(tool_result)}"
                        else:
                            content_str = str(tool_result)
                            logger.debug(
                                f"[工具响应] {fname} (ID={call_id}) 返回内容长度: {len(content_str)}"
                            )
                            if logger.isEnabledFor(logging.DEBUG):
                                log_debug_json(
                                    logger,
                                    f"[工具响应体] {fname} (ID={call_id})",
                                    content_str,
                                )

                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": call_id,
                                "name": fname,
                                "content": content_str,
                            }
                        )

                        if tool_context.get("conversation_ended"):
                            conversation_ended = True
                            logger.info(f"[会话状态] 工具 {fname} 触发了会话结束标记")

                if conversation_ended:
                    logger.info("对话已结束（调用 end 工具）")
                    return ""

            except Exception as exc:
                logger.exception(f"ask 失败: {exc}")
                return f"处理失败: {exc}"

        return "达到最大迭代次数，未能完成处理"
