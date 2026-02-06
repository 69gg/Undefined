"""AI client entry point."""

from __future__ import annotations

import asyncio
import importlib.util
import logging
from collections import deque
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional, TYPE_CHECKING

import httpx

from Undefined.ai.llm import ModelRequester
from Undefined.ai.multimodal import MultimodalAnalyzer
from Undefined.ai.prompts import PromptBuilder
from Undefined.ai.summaries import SummaryService
from Undefined.ai.tokens import TokenCounter
from Undefined.ai.tooling import ToolManager
from Undefined.config import (
    ChatModelConfig,
    VisionModelConfig,
    AgentModelConfig,
    Config,
)
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
from Undefined.utils.tool_calls import parse_tool_arguments

logger = logging.getLogger(__name__)


# 尝试导入 langchain SearxSearchWrapper
if TYPE_CHECKING:
    from langchain_community.utilities import (
        SearxSearchWrapper as SearxSearchWrapperType,
    )
else:
    SearxSearchWrapperType = object

_SearxSearchWrapper: type[SearxSearchWrapperType] | None
try:
    from langchain_community.utilities import SearxSearchWrapper as _SearxSearchWrapper

    _SEARX_AVAILABLE = True
except Exception:
    _SearxSearchWrapper = None
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
        runtime_config: Config | None = None,
    ) -> None:
        """初始化 AI 客户端

        参数:
            chat_config: 对话模型配置
            vision_config: 视觉模型配置
            agent_config: 智能体模型配置
            memory_storage: 长期记忆存储
            end_summary_storage: 短期回忆存储
            bot_qq: 机器人自身的 QQ 号
        """
        self.chat_config = chat_config
        self.vision_config = vision_config
        self.agent_config = agent_config
        self.bot_qq = bot_qq
        self.runtime_config = runtime_config
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
        runtime_config = self._get_runtime_config()
        intro_autogen_enabled = runtime_config.agent_intro_autogen_enabled
        intro_queue_interval = runtime_config.agent_intro_autogen_queue_interval
        intro_max_tokens = runtime_config.agent_intro_autogen_max_tokens
        intro_cache_path = Path(runtime_config.agent_intro_hash_path)
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
        hot_reload_enabled = runtime_config.skills_hot_reload
        if hot_reload_enabled:
            interval = runtime_config.skills_hot_reload_interval
            debounce = runtime_config.skills_hot_reload_debounce
            self.tool_registry.start_hot_reload(interval=interval, debounce=debounce)
            self.agent_registry.start_hot_reload(interval=interval, debounce=debounce)

        # 初始化搜索 wrapper
        self._search_wrapper: Optional[Any] = None
        if _SEARX_AVAILABLE and _SearxSearchWrapper is not None:
            searxng_url = runtime_config.searxng_url
            if searxng_url:
                try:
                    self._search_wrapper = _SearxSearchWrapper(
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
            runtime_config_getter=self._get_runtime_config,
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
        logger.info("[清理] 正在关闭 AIClient...")

        # 1) 停止后台任务（避免关闭 HTTP client 后仍有请求在跑）
        if hasattr(self, "_agent_intro_generator"):
            await self._agent_intro_generator.stop()
        if hasattr(self, "_agent_intro_task") and self._agent_intro_task:
            if not self._agent_intro_task.done():
                await self._agent_intro_task

        # 2) 等待 MCP 初始化完成，再关闭 MCP toolsets
        if hasattr(self, "_mcp_init_task") and not self._mcp_init_task.done():
            await self._mcp_init_task

        if hasattr(self, "tool_registry"):
            await self.tool_registry.stop_hot_reload()
            await self.tool_registry.close_mcp_toolsets()
        if hasattr(self, "agent_registry"):
            await self.agent_registry.stop_hot_reload()

        # 3) 最后关闭共享 HTTP client
        if hasattr(self, "_http_client"):
            logger.info("[清理] 正在关闭 AIClient HTTP 客户端...")
            await self._http_client.aclose()

        logger.info("[清理] AIClient 已关闭")

    def count_tokens(self, text: str) -> int:
        return self._token_counter.count(text)

    def _get_runtime_config(self) -> Config:
        if self.runtime_config is not None:
            return self.runtime_config
        from Undefined.config import get_config

        return get_config(strict=False)

    def _get_prefetch_tool_names(self) -> list[str]:
        runtime_config = self._get_runtime_config()
        return list(runtime_config.prefetch_tools)

    def _prefetch_hide_tools(self) -> bool:
        runtime_config = self._get_runtime_config()
        return runtime_config.prefetch_tools_hide

    def _is_missing_tool_result(self, result: Any) -> bool:
        if not isinstance(result, str):
            return False
        return result.startswith("未找到项目") or result.startswith("未找到 MCP 工具")

    async def _maybe_prefetch_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        call_type: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]] | None]:
        if not tools:
            return messages, tools

        prefetch_names = self._get_prefetch_tool_names()
        if not prefetch_names:
            return messages, tools

        available_names = {
            tool.get("function", {}).get("name")
            for tool in tools
            if tool.get("function")
        }
        prefetch_targets = [name for name in prefetch_names if name in available_names]
        if not prefetch_targets:
            return messages, tools

        ctx = RequestContext.current()
        cache: dict[str, list[str]] = {}
        done: set[str] = set()
        if ctx:
            cache = ctx.get_resource("prefetch_tools", {}) or {}
            done = set(cache.get(call_type, []))

        to_run = [name for name in prefetch_targets if name not in done]
        if not to_run:
            return messages, tools

        results: list[tuple[str, Any]] = []
        for name in to_run:
            try:
                result = await self.tool_manager.execute_tool(
                    name,
                    {},
                    {
                        "runtime_config": self._get_runtime_config(),
                        "easter_egg_silent": True,
                    },
                )
            except Exception as exc:
                logger.warning("[预先调用] %s 执行失败: %s", name, exc)
                continue

            if self._is_missing_tool_result(result):
                logger.warning("[预先调用] %s 未找到对应工具，跳过", name)
                continue

            results.append((name, result))
            done.add(name)

        if not results:
            return messages, tools

        if ctx:
            cache[call_type] = sorted(done)
            ctx.set_resource("prefetch_tools", cache)

        content_lines = ["【预先工具结果】"]
        content_lines.extend([f"- {name}: {result}" for name, result in results])
        prefetch_message = {"role": "system", "content": "\n".join(content_lines)}

        insert_idx = 0
        for idx, msg in enumerate(messages):
            if msg.get("role") == "system":
                insert_idx = idx + 1
            else:
                break
        new_messages = list(messages)
        new_messages.insert(insert_idx, prefetch_message)

        if self._prefetch_hide_tools():
            hidden = set(name for name in done)
            tools = [
                tool
                for tool in tools
                if tool.get("function", {}).get("name") not in hidden
            ]
        return new_messages, tools

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
        messages, tools = await self._maybe_prefetch_tools(messages, tools, call_type)
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
        """发送问题给 AI 并获取回复 (支持工具调用和迭代)

        参数:
            question: 用户输入的问题
            context: 额外的上下文背景
            send_message_callback: 发送消息的回调
            get_recent_messages_callback: 获取上下文历史消息的回调
            get_image_url_callback: 获取图片 URL 的回调
            get_forward_msg_callback: 获取合并转发内容的回调
            send_like_callback: 点赞回调
            sender: 消息发送助手实例
            history_manager: 历史记录管理器实例
            onebot_client: OneBot 客户端实例
            scheduler: 任务调度器实例
            extra_context: 额外的上下文负载

        返回:
            AI 生成的最终文本回复
        """
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
        tool_context.setdefault("runtime_config", self._get_runtime_config())
        tool_context.setdefault("search_wrapper", self._search_wrapper)
        tool_context.setdefault("recent_replies", self.recent_replies)
        tool_context.setdefault(
            "send_private_message_callback", self._send_private_message_callback
        )
        tool_context.setdefault("send_message_callback", send_message_callback)
        tool_context.setdefault("sender", sender)
        tool_context.setdefault("send_image_callback", self._send_image_callback)

        max_iterations = 1000
        iteration = 0
        conversation_ended = False
        ds_cot_enabled = getattr(self.chat_config, "deepseek_new_cot_support", False)
        ds_cot_logged = False
        ds_cot_missing_reason_logged = False

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

                tool_name_map = (
                    result.get("_tool_name_map") if isinstance(result, dict) else None
                )
                api_to_internal: dict[str, str] = {}
                if isinstance(tool_name_map, dict):
                    raw_api_to_internal = tool_name_map.get("api_to_internal")
                    if isinstance(raw_api_to_internal, dict):
                        api_to_internal = {
                            str(k): str(v) for k, v in raw_api_to_internal.items()
                        }

                choice = result.get("choices", [{}])[0]
                message = choice.get("message", {})
                content: str = message.get("content") or ""
                reasoning_content = message.get("reasoning_content")
                tool_calls = message.get("tool_calls", [])
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "[AI响应] content_len=%s tool_calls=%s",
                        len(content),
                        len(tool_calls),
                    )
                    if tool_calls:
                        log_debug_json(logger, "[AI工具调用]", tool_calls)

                log_thinking = self._get_runtime_config().log_thinking
                if ds_cot_enabled and tools and log_thinking and not ds_cot_logged:
                    ds_cot_logged = True
                    logger.info(
                        "[DeepSeek CoT] thinking-mode 工具调用兼容已启用：将回传 reasoning_content 以避免 400"
                    )
                if ds_cot_enabled and reasoning_content and log_thinking:
                    logger.info(
                        "[DeepSeek CoT] 本轮 reasoning_content_len=%s",
                        len(reasoning_content),
                    )
                    logger.info(
                        "[DeepSeek CoT] reasoning_content=%s",
                        redact_string(reasoning_content),
                    )
                if (
                    ds_cot_enabled
                    and log_thinking
                    and tools
                    and getattr(self.chat_config, "thinking_enabled", False)
                    and not reasoning_content
                    and tool_calls
                    and not ds_cot_missing_reason_logged
                ):
                    ds_cot_missing_reason_logged = True
                    message_keys = (
                        ", ".join(sorted(message.keys()))
                        if isinstance(message, dict)
                        else type(message).__name__
                    )
                    logger.info(
                        "[DeepSeek CoT] 未在响应中发现 reasoning_content（可能是模型/服务商不返回思维链）；message_keys=%s",
                        message_keys,
                    )

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

                assistant_message: dict[str, Any] = {
                    "role": "assistant",
                    "content": content,
                    "tool_calls": tool_calls,
                }
                if ds_cot_enabled and reasoning_content is not None:
                    # DeepSeek thinking-mode 的 tool_calls 需要在同一问题的子回合中回传 reasoning_content，
                    # 否则可能触发 400（官方兼容性说明）。
                    assistant_message["reasoning_content"] = reasoning_content
                messages.append(assistant_message)

                tool_tasks = []
                tool_call_ids = []
                tool_api_names: list[str] = []
                tool_internal_names: list[str] = []

                for tool_call in tool_calls:
                    call_id = tool_call.get("id", "")
                    function = tool_call.get("function", {})
                    api_function_name = function.get("name", "")
                    raw_args = function.get("arguments")

                    internal_function_name = api_to_internal.get(
                        str(api_function_name), str(api_function_name)
                    )

                    if internal_function_name != api_function_name:
                        logger.info(
                            "[工具准备] 准备调用: %s (原名: %s) (ID=%s)",
                            internal_function_name,
                            api_function_name,
                            call_id,
                        )
                    else:
                        logger.info(
                            "[工具准备] 准备调用: %s (ID=%s)",
                            api_function_name,
                            call_id,
                        )
                    logger.debug(
                        f"[工具参数] {api_function_name} 参数: {redact_string(str(raw_args))}"
                    )

                    function_args = parse_tool_arguments(
                        raw_args,
                        logger=logger,
                        tool_name=str(api_function_name),
                    )

                    if not isinstance(function_args, dict):
                        function_args = {}

                    tool_call_ids.append(call_id)
                    tool_api_names.append(str(api_function_name))
                    tool_internal_names.append(str(internal_function_name))
                    tool_tasks.append(
                        self.tool_manager.execute_tool(
                            str(internal_function_name), function_args, tool_context
                        )
                    )

                if tool_tasks:
                    logger.info(
                        "[工具执行] 开始并发执行 %s 个工具调用: %s",
                        len(tool_tasks),
                        ", ".join(tool_internal_names),
                    )
                    tool_results = await asyncio.gather(
                        *tool_tasks, return_exceptions=True
                    )

                    for i, tool_result in enumerate(tool_results):
                        call_id = tool_call_ids[i]
                        api_fname = tool_api_names[i]
                        internal_fname = tool_internal_names[i]

                        if isinstance(tool_result, Exception):
                            logger.error(
                                f"[工具异常] {internal_fname} (ID={call_id}) 执行抛出异常: {tool_result}"
                            )
                            content_str = f"执行失败: {str(tool_result)}"
                        else:
                            content_str = str(tool_result)
                            logger.debug(
                                f"[工具响应] {internal_fname} (ID={call_id}) 返回内容长度: {len(content_str)}"
                            )
                            if logger.isEnabledFor(logging.DEBUG):
                                log_debug_json(
                                    logger,
                                    f"[工具响应体] {internal_fname} (ID={call_id})",
                                    content_str,
                                )

                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": call_id,
                                "name": api_fname,
                                "content": content_str,
                            }
                        )

                        if tool_context.get("conversation_ended"):
                            conversation_ended = True
                            logger.info(
                                f"[会话状态] 工具 {internal_fname} 触发了会话结束标记"
                            )

                if conversation_ended:
                    logger.info("对话已结束（调用 end 工具）")
                    return ""

            except Exception as exc:
                logger.exception(f"ask 失败: {exc}")
                return f"处理失败: {exc}"

        return "达到最大迭代次数，未能完成处理"
