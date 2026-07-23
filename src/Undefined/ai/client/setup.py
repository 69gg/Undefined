"""AI 客户端生命周期与配置。"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Collection
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional, Protocol, TYPE_CHECKING

import httpx

from Undefined.attachments import AttachmentRegistry
from Undefined.ai.llm import ModelRequester
from Undefined.ai.model_selector import ModelSelector
from Undefined.ai.multimodal import MultimodalAnalyzer
from Undefined.ai.prompts import PromptBuilder
from Undefined.ai.crawl4ai_support import get_crawl4ai_capabilities
from Undefined.ai.summaries import SummaryService
from Undefined.ai.tokens import TokenCounter
from Undefined.ai.tool_search import TOOL_SEARCH_NAME
from Undefined.ai.tooling import ToolManager
from Undefined.config import (
    ChatModelConfig,
    VisionModelConfig,
    AgentModelConfig,
    Config,
    GrokModelConfig,
)
from Undefined.context import RequestContext
from Undefined.utils.paths import PACKAGE_ROOT
from Undefined.context_resource_registry import set_context_resource_scan_paths
from Undefined.end_summary_storage import EndSummaryStorage
from Undefined.memory import MemoryStorage
from Undefined.skills.agents import AgentRegistry
from Undefined.skills.agents.intro_generator import (
    AgentIntroGenConfig,
    AgentIntroGenerator,
)
from Undefined.skills.anthropic_skills import AnthropicSkillRegistry
from Undefined.skills.tools import ToolRegistry
from Undefined.token_usage_storage import TokenUsageStorage
from Undefined.utils.logging import redact_string
from Undefined.utils.xml import XML_CONTENT_BODY_PATTERN, decode_xml_content_text

logger = logging.getLogger(__name__)

_PREFETCH_RESULT_MARKER = "【预先工具结果】"


# 模型返回纯文本但未调用 tool 时，追加到 messages 的纠正提示（不写死具体 tool）
MISSING_TOOL_CALL_RETRY_HINT = (
    "【系统提示】你上一轮输出了纯文本且未调用任何工具。"
    "本环境必须通过工具调用来完成对外动作与结束本轮处理。"
    "请结合上文完整对话历史与已有 tool 返回结果，自行决定下一步应调用的工具；"
    "不要直接以纯文本作为最终对外回复。"
)


_CONTENT_TAG_PATTERN = re.compile(
    rf"<content>({XML_CONTENT_BODY_PATTERN})</content>",
    re.DOTALL | re.IGNORECASE,
)

_INVALID_TOOL_CALL_CONTENT = (
    "无效工具调用：工具名称为空或格式非法，系统已跳过执行。"
    "请使用可用工具名重新调用，或调用 end 结束本轮。"
)


def _build_invalid_tool_call_response(tool_call: Any) -> dict[str, Any]:
    """为模型发出的 malformed tool call 构造 tool 角色回填消息。"""
    call_id = ""
    tool_name = ""
    if isinstance(tool_call, dict):
        call_id = str(tool_call.get("id", "") or "")
        function = tool_call.get("function")
        if isinstance(function, dict):
            tool_name = str(function.get("name", "") or "").strip()
    return {
        "role": "tool",
        "tool_call_id": call_id,
        "name": tool_name,
        "content": _INVALID_TOOL_CALL_CONTENT,
    }


class SendMessageCallback(Protocol):
    def __call__(
        self, message: str, reply_to: int | None = None
    ) -> Awaitable[None]: ...


class SendPrivateMessageCallback(Protocol):
    def __call__(
        self, user_id: int, message: str, reply_to: int | None = None
    ) -> Awaitable[None]: ...


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
        "[初始化] langchain_community 未安装或 SearxSearchWrapper 不可用，搜索功能将禁用"
    )


def _attachment_remote_download_max_bytes(runtime_config: Config) -> int:
    value = int(runtime_config.attachment_remote_download_max_size_mb)
    return max(0, value) * 1024 * 1024


def _attachment_cache_max_bytes(runtime_config: Config) -> int:
    value = int(runtime_config.attachment_cache_max_total_size_mb)
    return max(0, value) * 1024 * 1024


def _attachment_cache_max_age_seconds(runtime_config: Config) -> int:
    value = int(runtime_config.attachment_cache_max_age_days)
    return max(0, value) * 24 * 60 * 60


def _resolve_summary_model_config(
    runtime_config: Config | None,
    fallback: AgentModelConfig,
) -> AgentModelConfig:
    if runtime_config is None:
        # 回退到默认/主配置
        return fallback
    if not getattr(runtime_config, "summary_model_configured", False):
        # 回退到默认/主配置
        return fallback
    summary_model = getattr(runtime_config, "summary_model", None)
    if isinstance(summary_model, AgentModelConfig):
        return summary_model
    # 回退到默认/主配置
    return fallback


class ClientSetupMixin:
    """AI 客户端初始化、配置热更新与资源清理。"""

    def __init__(
        self,
        chat_config: ChatModelConfig,
        vision_config: VisionModelConfig,
        agent_config: AgentModelConfig,
        memory_storage: Optional[MemoryStorage] = None,
        end_summary_storage: Optional[EndSummaryStorage] = None,
        bot_qq: int = 0,
        runtime_config: Config | None = None,
        cognitive_service: Any = None,
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
        self._crawl4ai_capabilities = get_crawl4ai_capabilities()

        self._http_client = httpx.AsyncClient(timeout=480.0, trust_env=False)
        self._token_usage_storage = TokenUsageStorage()
        self._requester = ModelRequester(
            None,
            self._token_usage_storage,
            config_getter=self._get_runtime_config,
        )
        self._token_counter = TokenCounter()
        self._knowledge_manager: Any = None
        self._cognitive_service: Any = cognitive_service
        self._meme_service: Any = None
        if self.runtime_config is not None:
            self.attachment_registry = AttachmentRegistry(
                remote_download_max_bytes=_attachment_remote_download_max_bytes(
                    self.runtime_config
                ),
                max_cache_bytes=_attachment_cache_max_bytes(self.runtime_config),
                max_records=self.runtime_config.attachment_cache_max_records,
                max_age_seconds=_attachment_cache_max_age_seconds(self.runtime_config),
                url_reference_max_records=(
                    self.runtime_config.attachment_url_reference_max_records
                ),
                url_max_length=self.runtime_config.attachment_url_max_length,
                proxy_config=self.runtime_config,
            )
        else:
            self.attachment_registry = AttachmentRegistry()

        self._send_private_message_callback: Optional[SendPrivateMessageCallback] = None
        self._send_image_callback: Optional[
            Callable[[int, str, str], Awaitable[None]]
        ] = None

        # 当前群聊ID和用户ID（用于send_message工具）
        self.current_group_id: Optional[int] = None
        self.current_user_id: Optional[int] = None

        self.tool_registry = ToolRegistry(PACKAGE_ROOT / "skills" / "tools")
        self.agent_registry = AgentRegistry(PACKAGE_ROOT / "skills" / "agents")

        # 初始化 Anthropic Agent Skills 注册表（可选，目录不存在时自动跳过）
        anthropic_skills_dir = PACKAGE_ROOT / "skills" / "anthropic_skills"
        dot_delimiter = self._get_runtime_config().tools_dot_delimiter
        self.anthropic_skill_registry = AnthropicSkillRegistry(
            anthropic_skills_dir,
            dot_delimiter=dot_delimiter,
        )

        self.tool_manager = ToolManager(
            self.tool_registry,
            self.agent_registry,
            anthropic_skill_registry=self.anthropic_skill_registry,
        )

        self.model_selector = ModelSelector()

        # 绑定上下文资源扫描路径（基于注册表 watch_paths）
        scan_paths = [
            p
            for p in (
                self.tool_registry._watch_paths + self.agent_registry._watch_paths
            )
            if p.exists()
        ]
        set_context_resource_scan_paths(scan_paths)
        logger.debug(
            "[初始化] 上下文资源扫描路径已绑定: count=%s",
            len(scan_paths),
        )

        # Agent intro 生成器（延迟初始化，需要外部设置 queue_manager）
        self._agent_intro_generator: Any | None = None
        self._agent_intro_task: asyncio.Task[None] | None = None
        self._intro_refresh_task: asyncio.Task[None] | None = None
        self._queue_manager: Any | None = None
        self._intro_config: Any | None = None
        # 后台 LLM 调用挂起表（走队列的后台请求）
        self._pending_llm_calls: dict[
            str, tuple[asyncio.Event, dict[str, Any] | Exception | None]
        ] = {}

        # 后台任务引用集合（防止被 GC）
        self._background_tasks: set[asyncio.Task[Any]] = set()

        runtime_config = self._get_runtime_config()
        self._intro_config = AgentIntroGenConfig(
            enabled=runtime_config.agent_intro_autogen_enabled,
            queue_interval_seconds=runtime_config.agent_intro_autogen_queue_interval,
            max_tokens=runtime_config.agent_intro_autogen_max_tokens,
            cache_path=Path(runtime_config.agent_intro_hash_path),
        )

        # 启动 skills 热重载
        hot_reload_enabled = runtime_config.skills_hot_reload
        if hot_reload_enabled:
            interval = runtime_config.skills_hot_reload_interval
            debounce = runtime_config.skills_hot_reload_debounce
            self.tool_registry.start_hot_reload(interval=interval, debounce=debounce)
            self.agent_registry.start_hot_reload(interval=interval, debounce=debounce)
            self.anthropic_skill_registry.start_hot_reload(
                interval=interval, debounce=debounce
            )
            logger.info(
                "[初始化] 技能热重载已启用: interval=%.2fs debounce=%.2fs",
                interval,
                debounce,
            )
        else:
            logger.info("[初始化] 技能热重载已禁用")

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
                        "[初始化] SearxSearchWrapper 初始化成功: url=%s k=10",
                        redact_string(searxng_url),
                    )
                except Exception as exc:
                    logger.warning("[初始化] SearxSearchWrapper 初始化失败: %s", exc)
            else:
                logger.info("[初始化] SEARXNG_URL 未配置，搜索功能禁用")

        if self._crawl4ai_capabilities.available:
            logger.info("[初始化] crawl4ai 可用，网页获取功能已启用")
        else:
            detail = self._crawl4ai_capabilities.error
            if detail:
                logger.warning(
                    "[初始化] crawl4ai 不可用，网页获取功能将禁用: %s",
                    detail,
                )
            else:
                logger.warning("[初始化] crawl4ai 不可用，网页获取功能将禁用")

        self._prompt_builder = PromptBuilder(
            bot_qq=self.bot_qq,
            memory_storage=self.memory_storage,
            end_summary_storage=self._end_summary_storage,
            runtime_config_getter=self._get_runtime_config,
            anthropic_skill_registry=self.anthropic_skill_registry,
            cognitive_service=self._cognitive_service,
        )
        self._multimodal = MultimodalAnalyzer(
            self._requester,
            self.vision_config,
            config_getter=self._get_runtime_config,
        )
        self._rebuild_summary_service()

        async def init_mcp_async() -> None:
            try:
                await self.tool_registry.initialize_mcp_toolsets()
            except Exception as exc:
                logger.warning("[初始化] 异步初始化 MCP 工具集失败: %s", exc)

        self._mcp_init_task = asyncio.create_task(init_mcp_async())

        async def load_preferences_async() -> None:
            try:
                await self.model_selector.load_preferences()
            except Exception as exc:
                logger.warning("[初始化] 加载模型偏好失败: %s", exc)

        self._preferences_load_task = asyncio.create_task(load_preferences_async())

        logger.info("[初始化] AIClient 初始化完成")

    async def close(self) -> None:
        logger.info("[清理] 正在关闭 AIClient...")

        intro_gen = getattr(self, "_agent_intro_generator", None)
        if intro_gen is not None:
            await intro_gen.stop()
        intro_refresh_task = getattr(self, "_intro_refresh_task", None)
        if intro_refresh_task is not None and not intro_refresh_task.done():
            intro_refresh_task.cancel()
            try:
                await intro_refresh_task
            except asyncio.CancelledError:
                pass
        self._intro_refresh_task = None
        if hasattr(self, "_agent_intro_task") and self._agent_intro_task:
            if not self._agent_intro_task.done():
                await self._agent_intro_task
        knowledge_manager = getattr(self, "_knowledge_manager", None)
        if knowledge_manager is not None and hasattr(knowledge_manager, "stop"):
            try:
                await knowledge_manager.stop()
            except Exception as exc:
                logger.warning("[清理] 关闭知识库管理器失败: %s", exc)
            self._knowledge_manager = None
        cognitive_service = getattr(self, "_cognitive_service", None)
        if cognitive_service is not None:
            if hasattr(cognitive_service, "stop"):
                try:
                    await cognitive_service.stop()
                except Exception as exc:
                    logger.warning("[清理] 关闭认知记忆服务失败: %s", exc)
            self._cognitive_service = None
            if hasattr(self, "_prompt_builder") and self._prompt_builder is not None:
                self._prompt_builder.set_cognitive_service(None)

        if hasattr(self, "_mcp_init_task") and not self._mcp_init_task.done():
            await self._mcp_init_task

        if hasattr(self, "tool_registry"):
            await self.tool_registry.stop_hot_reload()
            await self.tool_registry.close_mcp_toolsets()
        if hasattr(self, "agent_registry"):
            await self.agent_registry.stop_hot_reload()
        if hasattr(self, "anthropic_skill_registry"):
            await self.anthropic_skill_registry.stop_hot_reload()

        attachment_registry = getattr(self, "attachment_registry", None)
        if attachment_registry is not None and hasattr(attachment_registry, "flush"):
            try:
                await attachment_registry.flush()
            except Exception as exc:
                logger.warning("[清理] 刷新附件注册表失败: %s", exc)

        requester = getattr(self, "_requester", None)
        if requester is not None and hasattr(requester, "aclose"):
            logger.info("[清理] 正在关闭 AIClient 模型 HTTP 客户端...")
            await requester.aclose()

        http_client = getattr(self, "_http_client", None)
        if http_client is not None:
            await http_client.aclose()

        logger.info("[清理] AIClient 已关闭")

    def set_queue_manager(self, queue_manager: Any) -> None:
        """设置队列管理器并启动 Agent intro 生成器。

        参数:
            queue_manager: 队列管理器实例
        """
        if self._queue_manager is not None:
            logger.warning("[AI客户端] queue_manager 已设置，跳过重复设置")
            return

        if queue_manager is None:
            logger.warning("[AI客户端] 传入的 queue_manager 为 None")
            return

        self._queue_manager = queue_manager

        # 启动/刷新 Agent intro 自动生成
        if self._intro_config:
            self.apply_intro_config(self._intro_config)

    def apply_intro_config(self, config: AgentIntroGenConfig) -> None:
        """应用 Agent intro 生成器配置（支持热更新）。"""
        self._intro_config = config
        if self._queue_manager is None:
            return
        existing = self._intro_refresh_task
        if existing is not None and not existing.done():
            existing.cancel()

        async def _run_refresh() -> None:
            try:
                await self._refresh_intro_generator(config)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("[Agent介绍] 刷新 intro 生成器失败")

        task = asyncio.create_task(_run_refresh())

        def _finalize(done_task: asyncio.Task[None]) -> None:
            if getattr(self, "_intro_refresh_task", None) is done_task:
                self._intro_refresh_task = None
            if done_task.cancelled():
                return
            exc = done_task.exception()
            if exc is not None:
                logger.error("[Agent介绍] intro 刷新任务异常结束", exc_info=exc)

        task.add_done_callback(_finalize)
        self._intro_refresh_task = task

    async def _refresh_intro_generator(self, config: AgentIntroGenConfig) -> None:
        if not config.enabled:
            if self._agent_intro_generator is not None:
                await self._agent_intro_generator.stop()
                self._agent_intro_generator = None
            self._agent_intro_task = None
            logger.info("[Agent介绍] 自动生成已关闭")
            return

        if self._queue_manager is None:
            return

        if self._agent_intro_generator is None:
            self._agent_intro_generator = AgentIntroGenerator(
                self.agent_registry.base_dir,
                self,
                self._queue_manager,
                config,
            )
            self._agent_intro_task = asyncio.create_task(
                self._agent_intro_generator.start()
            )
            logger.info(
                "[Agent介绍] 自动生成已启动: interval=%.2fs max_tokens=%s cache=%s",
                config.queue_interval_seconds,
                config.max_tokens,
                config.cache_path,
            )
            return

        if self._agent_intro_generator.config.cache_path != config.cache_path:
            # 缓存路径变更需重建生成器，否则 hash 与落盘目录不一致
            await self._agent_intro_generator.stop()
            self._agent_intro_generator = AgentIntroGenerator(
                self.agent_registry.base_dir,
                self,
                self._queue_manager,
                config,
            )
            self._agent_intro_task = asyncio.create_task(
                self._agent_intro_generator.start()
            )
            logger.info(
                "[Agent介绍] 缓存路径变更，已重启生成器: cache=%s",
                config.cache_path,
            )
            return

        self._agent_intro_generator.config = config

    def set_knowledge_manager(self, manager: Any) -> None:
        self._knowledge_manager = manager

    def set_cognitive_service(self, service: Any) -> None:
        self._cognitive_service = service
        if hasattr(self, "_prompt_builder") and self._prompt_builder is not None:
            self._prompt_builder.set_cognitive_service(service)
        logger.info(
            "[AI客户端] 认知记忆服务已挂载并同步到 PromptBuilder: enabled=%s",
            bool(getattr(service, "enabled", False)) if service is not None else False,
        )

    def set_meme_service(self, service: Any) -> None:
        self._meme_service = service
        resolver = None
        async_resolver = None
        if service is not None and hasattr(service, "resolve_global_image_sync"):
            resolver = service.resolve_global_image_sync
        if service is not None and hasattr(service, "resolve_global_image"):
            async_resolver = service.resolve_global_image
        self.attachment_registry.set_global_image_resolver(resolver)
        self.attachment_registry.set_global_image_resolver_async(async_resolver)
        logger.info(
            "[AI客户端] 表情包服务已挂载: enabled=%s",
            bool(getattr(service, "enabled", False)) if service is not None else False,
        )

    def apply_search_config(self, searxng_url: str) -> None:
        """应用搜索服务配置（支持热更新）。"""
        if not _SEARX_AVAILABLE or _SearxSearchWrapper is None:
            if searxng_url:
                logger.warning(
                    "[配置] 搜索组件不可用，已忽略 SEARXNG_URL=%s",
                    redact_string(searxng_url),
                )
            else:
                logger.info("[配置] 搜索组件不可用，搜索已禁用")
            self._search_wrapper = None
            return

        if not searxng_url:
            self._search_wrapper = None
            logger.info("[配置] SEARXNG_URL 未配置，搜索功能已禁用")
            return

        try:
            self._search_wrapper = _SearxSearchWrapper(searx_host=searxng_url, k=10)
            logger.info(
                "[配置] 搜索服务已更新: url=%s k=10",
                redact_string(searxng_url),
            )
        except Exception as exc:
            logger.warning("[配置] 搜索服务更新失败: %s", exc)
            self._search_wrapper = None
            logger.info("[配置] 搜索服务已回退为禁用")

    def apply_model_configs(
        self,
        *,
        chat_config: ChatModelConfig,
        vision_config: VisionModelConfig,
        agent_config: AgentModelConfig,
        runtime_config: Config,
    ) -> None:
        """应用热更新后的模型配置。"""
        self.chat_config = chat_config
        self.vision_config = vision_config
        self.agent_config = agent_config
        self.runtime_config = runtime_config
        if hasattr(self._requester, "clear_client_cache"):
            self._requester.clear_client_cache()
        self._multimodal = MultimodalAnalyzer(
            self._requester,
            self.vision_config,
            config_getter=self._get_runtime_config,
        )
        self._rebuild_summary_service()
        self.apply_attachment_config(runtime_config)
        logger.info(
            "[配置] AI 模型配置已热更新: chat=%s vision=%s agent=%s",
            self.chat_config.model_name,
            self.vision_config.model_name,
            self.agent_config.model_name,
        )

    def apply_runtime_config(self, runtime_config: Config) -> None:
        """应用不需要重建模型客户端的运行时配置。"""
        self.runtime_config = runtime_config
        if hasattr(self._requester, "clear_client_cache"):
            self._requester.clear_client_cache()
        self._rebuild_summary_service()
        logger.info("[配置] AI 运行时配置已热更新")

    def _rebuild_summary_service(self) -> None:
        self._summary_service = SummaryService(
            self._requester,
            _resolve_summary_model_config(self.runtime_config, self.agent_config),
            self._token_counter,
        )

    def _resolve_summary_model_for_requests(self) -> AgentModelConfig:
        return _resolve_summary_model_config(self.runtime_config, self.agent_config)

    def apply_attachment_config(self, runtime_config: Config) -> None:
        self.attachment_registry.set_limits(
            remote_download_max_bytes=_attachment_remote_download_max_bytes(
                runtime_config
            ),
            max_cache_bytes=_attachment_cache_max_bytes(runtime_config),
            max_records=runtime_config.attachment_cache_max_records,
            max_age_seconds=_attachment_cache_max_age_seconds(runtime_config),
            url_reference_max_records=(
                runtime_config.attachment_url_reference_max_records
            ),
            url_max_length=runtime_config.attachment_url_max_length,
            proxy_config=runtime_config,
        )

    def count_tokens(self, text: str) -> int:
        return self._token_counter.count(text)

    def _get_runtime_config(self) -> Config:
        if self.runtime_config is not None:
            return self.runtime_config
        from Undefined.config import get_config

        return get_config(strict=False)

    def _find_chat_config_by_name(self, model_name: str) -> ChatModelConfig:
        """根据模型名查找配置（主模型或池中模型）"""
        if model_name == self.chat_config.model_name:
            return self.chat_config
        if self.chat_config.pool and self.chat_config.pool.enabled:
            for entry in self.chat_config.pool.models:
                if entry.model_name == model_name:
                    return self.model_selector._entry_to_chat_config(
                        # entry, self.chat_config
                        entry,
                        self.chat_config,
                    )
        return self.chat_config

    def _get_prefetch_tool_names(self) -> list[str]:
        runtime_config = self._get_runtime_config()
        return list(runtime_config.prefetch_tools)

    def _filter_tools_for_runtime_config(
        self,
        tools: list[dict[str, Any]],
        *,
        group_id: int | None = None,
        user_id: int | None = None,
        request_type: str | None = None,
    ) -> list[dict[str, Any]]:
        runtime_config = self._get_runtime_config()
        from Undefined.config.naga_policy import resolve_naga_session_allowed
        from Undefined.context import RequestContext

        # 未显式传入会话信息时，回退到 RequestContext（覆盖 request_model 等路径）
        if group_id is None and user_id is None and request_type is None:
            ctx = RequestContext.current()
            if ctx is not None:
                request_type = str(ctx.request_type or "") or None
                if ctx.group_id is not None:
                    try:
                        group_id = int(ctx.group_id)
                    except (TypeError, ValueError):
                        group_id = None
                uid = ctx.user_id if ctx.user_id is not None else ctx.sender_id
                if uid is not None:
                    try:
                        user_id = int(uid)
                    except (TypeError, ValueError):
                        user_id = None

        music_enabled = bool(
            str(getattr(runtime_config, "lxmusic2api_api_key", "") or "").strip()
        )
        runtime_tools: list[dict[str, Any]] = []
        for tool in tools:
            function = tool.get("function") if isinstance(tool, dict) else None
            name = function.get("name") if isinstance(function, dict) else None
            if (
                not music_enabled
                and isinstance(name, str)
                and name.startswith("music.")
            ):
                continue
            runtime_tools.append(tool)

        enabled = resolve_naga_session_allowed(
            runtime_config,
            request_type=request_type,
            group_id=group_id,
            user_id=user_id,
        )
        if enabled:
            return runtime_tools

        # 关闭 NagaAgent 模式时：隐藏相关 Agent，避免被模型误调用。
        filtered: list[dict[str, Any]] = []
        for tool in runtime_tools:
            function = tool.get("function") if isinstance(tool, dict) else None
            name = function.get("name") if isinstance(function, dict) else None
            if name == "naga_code_analysis_agent":
                continue
            filtered.append(tool)
        return filtered

    def _prefetch_hide_tools(self) -> bool:
        runtime_config = self._get_runtime_config()
        return runtime_config.prefetch_tools_hide

    def _hide_prefetch_tool_schemas(
        self,
        tools: list[dict[str, Any]] | None,
        completed_names: Collection[str],
    ) -> list[dict[str, Any]] | None:
        """隐藏已成功预取且不再需要模型调用的工具 schema。"""
        if not tools or not self._prefetch_hide_tools():
            return tools

        configured_names = {
            name for name in self._get_prefetch_tool_names() if name != TOOL_SEARCH_NAME
        }
        hidden_names = configured_names.intersection(completed_names)
        if not hidden_names:
            return tools
        return [
            tool
            for tool in tools
            if tool.get("function", {}).get("name") not in hidden_names
        ]

    def _completed_prefetch_tool_names(
        self,
        messages: list[dict[str, Any]],
        call_type: str,
    ) -> set[str]:
        """从请求缓存和已注入结果中恢复成功预取的工具名。"""
        completed: set[str] = set()
        ctx = RequestContext.current()
        if ctx:
            cache: dict[str, list[str]] = ctx.get_resource("prefetch_tools", {}) or {}
            completed.update(cache.get(call_type, []))

        configured_names = {
            name for name in self._get_prefetch_tool_names() if name != TOOL_SEARCH_NAME
        }
        for message in messages:
            if not isinstance(message, dict) or message.get("role") != "system":
                continue
            content = str(message.get("content") or "")
            if not content.startswith(_PREFETCH_RESULT_MARKER):
                continue
            result_lines = content.splitlines()[1:]
            completed.update(
                name
                for name in configured_names
                if any(line.startswith(f"- {name}:") for line in result_lines)
            )
        return completed

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

        completed = self._completed_prefetch_tool_names(messages, call_type)
        visible_tools = self._hide_prefetch_tool_schemas(tools, completed)

        if any(
            message.get("role") == "system"
            and str(message.get("content") or "").startswith(_PREFETCH_RESULT_MARKER)
            for message in messages
            if isinstance(message, dict)
        ):
            return messages, visible_tools

        # 预先调用部分工具，为模型补充稳定上下文（同一 call_type 仅执行一次）
        prefetch_names = [
            name for name in self._get_prefetch_tool_names() if name != TOOL_SEARCH_NAME
        ]
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

        # 分别缓存尝试和成功状态：失败项本轮不重试，但 schema 仍对模型可见。
        ctx = RequestContext.current()
        completed_cache: dict[str, list[str]] = {}
        attempted_cache: dict[str, list[str]] = {}
        attempted: set[str] = set()
        if ctx:
            completed_cache = ctx.get_resource("prefetch_tools", {}) or {}
            attempted_cache = ctx.get_resource("prefetch_tools_attempted", {}) or {}
            attempted = set(attempted_cache.get(call_type, []))

        to_run = [name for name in prefetch_targets if name not in attempted]
        if not to_run:
            return messages, visible_tools

        attempted.update(to_run)
        if ctx:
            attempted_cache[call_type] = sorted(attempted)
            ctx.set_resource("prefetch_tools_attempted", attempted_cache)

        results: list[tuple[str, Any]] = []
        for name in to_run:
            try:
                tool_args: dict[str, Any] = {}
                if name == "get_current_time":
                    tool_args = {"format": "text", "include_lunar": True}

                result = await self.tool_manager.execute_tool(
                    name,
                    tool_args,
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
            completed.add(name)

        if ctx:
            completed_cache[call_type] = sorted(completed)
            ctx.set_resource("prefetch_tools", completed_cache)

        visible_tools = self._hide_prefetch_tool_schemas(tools, completed)
        if not results:
            return messages, visible_tools

        content_lines = [_PREFETCH_RESULT_MARKER]
        for name, result in results:
            result_text = str(result).replace("\n", "\n  ")
            content_lines.append(f"- {name}: {result_text}")
        prefetch_message = {"role": "system", "content": "\n".join(content_lines)}

        insert_idx = 0
        # 紧接在已有 system 消息之后插入 prefetch 结果，保持指令顺序
        for idx, msg in enumerate(messages):
            if msg.get("role") == "system":
                insert_idx = idx + 1
            else:
                break
        new_messages = list(messages)
        new_messages.insert(insert_idx, prefetch_message)

        return new_messages, visible_tools

    async def request_model(
        self,
        model_config: (
            ChatModelConfig | VisionModelConfig | AgentModelConfig | GrokModelConfig
        ),
        messages: list[dict[str, Any]],
        max_tokens: int = 8192,
        call_type: str = "chat",
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str = "auto",
        transport_state: dict[str, Any] | None = None,
        skip_prefetch_tools: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        tools = self.tool_manager.maybe_merge_agent_tools(call_type, tools)
        if tools is not None:
            tools = self._filter_tools_for_runtime_config(tools)
        message_count_for_transport = len(messages)
        # ask() 已在消息链上完成预取时，内层和后续模型轮次都不得再次执行。
        if not skip_prefetch_tools:
            # Responses 续轮时跳过 prefetch，避免重复注入系统消息。
            if isinstance(transport_state, dict) and transport_state.get(
                "previous_response_id"
            ):
                completed = self._completed_prefetch_tool_names(messages, call_type)
                tools = self._hide_prefetch_tool_schemas(tools, completed)
            else:
                messages, tools = await self._maybe_prefetch_tools(
                    messages,
                    tools,
                    call_type,
                )
        return await self._requester.request(
            model_config=model_config,
            messages=messages,
            max_tokens=max_tokens,
            call_type=call_type,
            tools=tools,
            tool_choice=tool_choice,
            transport_state=transport_state,
            message_count_for_transport=message_count_for_transport,
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

    async def judge_meme_image(self, image_url: str) -> dict[str, Any]:
        return await self._multimodal.judge_meme_image(image_url)

    async def describe_meme_image(self, image_url: str) -> dict[str, Any]:
        return await self._multimodal.describe_meme_image(image_url)

    def get_media_history(self, media_key: str) -> list[dict[str, str]]:
        """获取指定媒体键的多模态分析历史 Q&A 记录。"""
        return self._multimodal.get_history(media_key)

    async def save_media_history(
        self, media_key: str, question: str, answer: str
    ) -> None:
        """保存一条多模态分析 Q&A 到历史记录并持久化到磁盘。"""
        await self._multimodal.save_history(media_key, question, answer)

    async def summarize_chat(self, messages: str, context: str = "") -> str:
        return await self._summary_service.summarize_chat(messages, context)

    async def merge_summaries(self, summaries: list[str]) -> str:
        return await self._summary_service.merge_summaries(summaries)

    def split_messages_by_tokens(self, messages: str, max_tokens: int) -> list[str]:
        return self._summary_service.split_messages_by_tokens(messages, max_tokens)

    async def generate_title(self, summary: str) -> str:
        return await self._summary_service.generate_title(summary)

    def _extract_message_excerpt(self, question: str) -> str:
        matched = _CONTENT_TAG_PATTERN.search(question)
        if matched:
            content = decode_xml_content_text(matched.group(1))
        else:
            content = question
        cleaned = " ".join(content.split()).strip()
        if not cleaned:
            return "(无文本内容)"
        if len(cleaned) > 120:
            return cleaned[:117].rstrip() + "..."
        return cleaned

    def _is_end_only_tool_calls(
        self,
        tool_calls: list[dict[str, Any]],
        api_to_internal: dict[str, str],
    ) -> bool:
        # 无 tool_calls 与有 tool_calls 走不同分支
        if not tool_calls:
            return False
        # 逐个处理模型返回的 tool_call
        for tool_call in tool_calls:
            function = tool_call.get("function", {})
            api_name = str(function.get("name", "") or "")
            internal_name = api_to_internal.get(api_name, api_name)
            if internal_name != "end":
                return False
        return True

    async def _save_forward_to_history(
        self,
        content: str,
        pre_context: dict[str, Any],
        history_manager: Any,
    ) -> None:
        """将合并转发消息写入历史记录"""
        if history_manager is None:
            return

        try:
            group_id = pre_context.get("group_id")
            user_id = pre_context.get("user_id")

            if group_id is not None:
                await history_manager.add_group_message(
                    group_id=int(group_id),
                    sender_id=0,
                    text_content=content,
                    sender_card="",
                    sender_nickname="[合并转发内容]",
                    group_name="",
                    role="system",
                    title="",
                    message_id=None,
                )
            elif user_id is not None:
                await history_manager.add_private_message(
                    user_id=int(user_id),
                    text_content=content,
                    display_name="[合并转发内容]",
                    user_name="",
                    message_id=None,
                )
            else:
                logger.debug("[合并转发] 无法写入历史：缺少 group_id 和 user_id")
        except Exception as exc:
            logger.debug("[合并转发] 写入历史失败: %s", exc)
