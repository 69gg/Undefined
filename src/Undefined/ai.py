"""
AI 模型调用封装"""

import importlib.util
from Undefined.skills.tools import ToolRegistry
from Undefined.skills.agents import AgentRegistry
from Undefined.skills.agents.intro_generator import (
    AgentIntroGenConfig,
    AgentIntroGenerator,
)
from Undefined.context import RequestContext
import base64
import json
import logging
import os
from collections import deque
from datetime import datetime
from typing import Any, Callable, Awaitable, Optional
from pathlib import Path
from contextvars import ContextVar

import aiofiles
import time
import asyncio
import httpx

from Undefined.config import ChatModelConfig, VisionModelConfig, AgentModelConfig
from Undefined.memory import MemoryStorage
from Undefined.end_summary_storage import EndSummaryStorage
from Undefined.token_usage_storage import TokenUsageStorage, TokenUsage


logger = logging.getLogger(__name__)

# 尝试导入 tiktoken，如果网络不可用可能会失败
try:
    import tiktoken

    _TIKTOKEN_AVAILABLE = True
except Exception:
    _TIKTOKEN_AVAILABLE = False
    logger.warning("tiktoken 加载失败，将使用简单的字符估算")

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
    # 尝试导入 ProxyConfig（新版本）以检查更细致的可用性
    try:
        # 这里仅检查模块是否能被导入，不实际使用导入的对象
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
        bot_qq: int = 0,  # 机器人QQ号，用于注入到系统提示词中
    ) -> None:
        self.chat_config = chat_config
        self.vision_config = vision_config
        self.agent_config = agent_config
        self.bot_qq = bot_qq  # 机器人QQ号
        self.memory_storage = memory_storage
        self._end_summary_storage = end_summary_storage or EndSummaryStorage()
        self._http_client = httpx.AsyncClient(timeout=120.0)
        self._tokenizer: Optional[Any] = None
        # 记录最近发送的 50 条消息内容，用于去重
        self.recent_replies: deque[str] = deque(maxlen=50)
        # 媒体分析缓存，避免重复调用 AI 分析同一媒体文件
        self._media_analysis_cache: dict[str, dict[str, str]] = {}
        # 私聊发送回调
        self._send_private_message_callback: Optional[
            Callable[[int, str], Awaitable[None]]
        ] = None
        # 发送图片回调
        self._send_image_callback: Optional[
            Callable[[int, str, str], Awaitable[None]]
        ] = None

        # 延迟加载 end 摘要（使用后台任务）
        self._end_summaries: deque[str] = deque(maxlen=100)
        self._summaries_loaded = False

        # 当前群聊ID和用户ID（用于send_message工具）
        self.current_group_id: Optional[int] = None
        self.current_user_id: Optional[int] = None

        # 初始化工具注册表
        self.tool_registry = ToolRegistry(Path(__file__).parent / "skills" / "tools")

        # 初始化 Agent 注册表
        self.agent_registry = AgentRegistry(Path(__file__).parent / "skills" / "agents")

        # 启动 Agent intro 自动生成（启动时队列）
        intro_autogen_enabled = os.getenv(
            "AGENT_INTRO_AUTOGEN_ENABLED", "true"
        ).lower() not in {
            "0",
            "false",
            "no",
        }
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

        # 启动 skills 热重载（可通过环境变量关闭）
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

        # Agent MCP 注册表（按调用上下文隔离）
        self._agent_mcp_registry_var: ContextVar[dict[str, Any] | None] = ContextVar(
            "agent_mcp_registry_var", default=None
        )

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
                        f"[bold green][初始化][/bold green] SearxSearchWrapper 初始化成功，URL: [cyan]{searxng_url}[/cyan]"
                    )
                except Exception as e:
                    logger.warning(f"SearxSearchWrapper 初始化失败: {e}")
            else:
                logger.info("SEARXNG_URL 未配置，搜索功能禁用")

        # crawl4ai 可用性检查（初始化时不创建实例，使用时动态创建）
        if _CRAWL4AI_AVAILABLE:
            logger.info("crawl4ai 可用，网页获取功能已启用")
        else:
            logger.warning("crawl4ai 不可用，网页获取功能将禁用")

        # 初始化 Token 使用统计存储
        self._token_usage_storage = TokenUsageStorage()
        logger.info("[bold green][初始化][/bold green] Token 使用统计存储已启用")

        # 尝试加载 tokenizer（可能因网络问题失败）
        if _TIKTOKEN_AVAILABLE:
            try:
                self._tokenizer = tiktoken.encoding_for_model("gpt-4")
                logger.info(
                    "[bold green][初始化][/bold green] tiktoken tokenizer 加载成功"
                )
            except Exception as e:
                logger.warning(
                    f"[初始化] tiktoken tokenizer 加载失败: {e}，将使用字符估算"
                )
                self._tokenizer = None

        # 异步初始化 MCP 工具集（在后台任务中完成）
        async def init_mcp_async() -> None:
            try:
                await self.tool_registry.initialize_mcp_toolsets()
            except Exception as e:
                logger.warning(f"异步初始化 MCP 工具集失败: {e}")

        # 创建后台任务初始化 MCP
        self._mcp_init_task = asyncio.create_task(init_mcp_async())

        logger.info("[bold green][初始化][/bold green] AIClient 初始化完成")

    async def _ensure_summaries_loaded(self) -> None:
        """确保 end 摘要已加载（延迟加载）"""
        if not self._summaries_loaded:
            loaded_summaries = await self._end_summary_storage.load()
            self._end_summaries.extend(loaded_summaries)
            self._summaries_loaded = True
            logger.debug(f"[AI初始化] 已加载 {len(loaded_summaries)} 条 End 摘要")

    async def close(self) -> None:
        """关闭 HTTP 客户端和 MCP 连接"""
        logger.info("[清理] 正在关闭 AIClient HTTP 客户端...")
        await self._http_client.aclose()

        # 关闭 MCP 工具集连接
        if hasattr(self, "tool_registry"):
            await self.tool_registry.close_mcp_toolsets()
            await self.tool_registry.stop_hot_reload()
        if hasattr(self, "agent_registry"):
            await self.agent_registry.stop_hot_reload()

        # 等待 MCP 初始化任务完成（如果还在运行）
        if hasattr(self, "_mcp_init_task") and not self._mcp_init_task.done():
            await self._mcp_init_task
        if hasattr(self, "_agent_intro_task") and self._agent_intro_task:
            if not self._agent_intro_task.done():
                await self._agent_intro_task

        logger.info("[清理] AIClient 已关闭")

    def count_tokens(self, text: str) -> int:
        """计算文本的 token 数量

        如果 tiktoken 不可用，使用简单的字符估算（中文约2字符/token，英文约4字符/token）
        """
        if self._tokenizer is not None:
            return len(self._tokenizer.encode(text))

        # 后备方案：简单估算
        # 中文字符约 1.5-2 tokens，英文约 4 字符 1 token
        # 保守估计：平均每 3 个字符算 1 个 token
        return len(text) // 3 + 1

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
        """统一的模型请求接口，自动处理 token 统计和错误处理

        参数:
            model_config: 模型配置
            messages: 消息列表
            max_tokens: 最大 token 数
            call_type: 调用类型（用于统计）
            tools: 工具定义
            tool_choice: 工具选择策略
            **kwargs: 其他传递给 API 的参数

        返回:
            API 响应 JSON 字典
        """
        start_time = time.perf_counter()
        if call_type.startswith("agent:"):
            agent_name = call_type.split("agent:", 1)[1]
            mcp_registry = self.get_active_agent_mcp_registry(agent_name)
            if mcp_registry:
                mcp_tools = mcp_registry.get_tools_schema()
                if mcp_tools:
                    tools = self._merge_tools(tools, mcp_tools)

        request_body = self._build_request_body(
            model_config=model_config,
            messages=messages,
            max_tokens=max_tokens,
            tools=tools,
            tool_choice=tool_choice,
            **kwargs,
        )

        try:
            response = await self._http_client.post(
                model_config.api_url,
                headers={
                    "Authorization": f"Bearer {model_config.api_key}",
                    "Content-Type": "application/json",
                },
                json=request_body,
            )
            response.raise_for_status()
            result: dict[str, Any] = response.json()
            duration = time.perf_counter() - start_time

            # 记录 token 使用统计
            usage = result.get("usage", {})
            prompt_tokens = usage.get("prompt_tokens", 0)
            completion_tokens = usage.get("completion_tokens", 0)
            total_tokens = usage.get("total_tokens", 0)

            logger.info(
                f"[API响应] {call_type} 完成: 耗时={duration:.2f}s, "
                f"Tokens={total_tokens} (P:{prompt_tokens} + C:{completion_tokens}), "
                f"模型={model_config.model_name}"
            )

            # 异步记录到存储
            asyncio.create_task(
                self._token_usage_storage.record(
                    TokenUsage(
                        timestamp=datetime.now().isoformat(),
                        model_name=model_config.model_name,
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        total_tokens=total_tokens,
                        duration_seconds=duration,
                        call_type=call_type,
                        success=True,
                    )
                )
            )

            return result
        except Exception as e:
            logger.exception(f"[API请求失败] {call_type} 调用出错: {e}")
            raise

    def _build_request_body(
        self,
        model_config: ChatModelConfig | VisionModelConfig | AgentModelConfig,
        messages: list[dict[str, Any]],
        max_tokens: int,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str = "auto",
        **kwargs: Any,
    ) -> dict[str, Any]:
        """构建 API 请求体，支持 thinking 参数

        参数:
            model_config: 模型配置
            messages: 消息列表
            max_tokens: 最大 token 数
            tools: 工具定义列表
            tool_choice: 工具选择策略
            **kwargs: 其他参数

        返回:
            请求体字典
        """
        body: dict[str, Any] = {
            "model": model_config.model_name,
            "messages": messages,
            "max_tokens": max_tokens,
        }

        # 添加 thinking 参数（如果启用）
        if model_config.thinking_enabled:
            body["thinking"] = {
                "type": "enabled",
                "budget_tokens": model_config.thinking_budget_tokens,
            }

        # 添加工具参数
        if tools:
            body["tools"] = tools
            body["tool_choice"] = tool_choice

        # 添加其他参数
        body.update(kwargs)

        return body

    def _merge_tools(
        self,
        base_tools: list[dict[str, Any]] | None,
        extra_tools: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not base_tools:
            return list(extra_tools)

        merged = list(base_tools)
        existing_names = {
            tool.get("function", {}).get("name")
            for tool in base_tools
            if tool.get("function")
        }
        for tool in extra_tools:
            name = tool.get("function", {}).get("name")
            if name and name not in existing_names:
                merged.append(tool)
                existing_names.add(name)
        return merged

    def _get_agent_mcp_config_path(self, agent_name: str) -> Path | None:
        agent_dir = self.agent_registry.base_dir / agent_name
        mcp_path = agent_dir / "mcp.json"
        if mcp_path.exists():
            return mcp_path
        return None

    def get_active_agent_mcp_registry(self, agent_name: str) -> Any | None:
        registries = self._agent_mcp_registry_var.get()
        if registries:
            return registries.get(agent_name)
        return None

    def _extract_choices_content(self, result: dict[str, Any]) -> str:
        """从 API 响应中提取 choices 内容

        支持两种格式：
        1. {"choices": [...]}
        2. {"data": {"choices": [...]}}

        参数:
            result: API 响应字典

        返回:
            提取的 content 文本

        引发:
            KeyError: 如果无法找到有效的 choices 数据
        """
        logger.debug(f"提取 choices 内容，响应结构: {list(result.keys())}")

        # 尝试直接获取 choices
        if "choices" in result and len(result["choices"]) > 0:
            choice = result["choices"][0]
            if isinstance(choice, str):
                # choice 直接是字符串
                return choice
            elif isinstance(choice, dict):
                message = choice.get("message")
                content: str | None = None
                if message is None:
                    content = choice.get("content")
                elif isinstance(message, str):
                    content = message
                elif isinstance(message, dict):
                    content = message.get("content")
                else:
                    content = None
                # 如果 content 为空或 None 但有 tool_calls，返回空字符串
                if not content and choice.get("message", {}).get("tool_calls"):
                    return ""
                # 如果 content 不为空，返回内容
                if content:
                    return content
                # 如果 content 为空且没有 tool_calls，返回空字符串
                return ""

        # 尝试从 data 嵌套结构获取
        if "data" in result and isinstance(result["data"], dict):
            data = result["data"]
            if "choices" in data and len(data["choices"]) > 0:
                choice = data["choices"][0]
                # 检查是 message 还是直接使用 content
                if isinstance(choice, str):
                    # choice 直接是字符串
                    return choice
                elif isinstance(choice, dict):
                    if "message" in choice:
                        message = choice["message"]
                        # message 可能是字符串或字典
                        if isinstance(message, str):
                            content = message
                        elif isinstance(message, dict):
                            content = message.get("content")
                        else:
                            content = None
                    else:
                        content = choice.get("content")
                    # 如果 content 为空或 None 但有 tool_calls，返回空字符串
                    if not content and choice.get("message", {}).get("tool_calls"):
                        return ""
                    # 如果 content 不为空，返回内容
                    if content:
                        return content
                    # 如果 content 为空且没有 tool_calls，返回空字符串
                    return ""

        # 如果都失败，抛出详细的错误
        raise KeyError(
            f"无法从 API 响应中提取 choices 内容。"
            f"响应结构: {list(result.keys())}, "
            f"data 键结构: {list(result.get('data', {}).keys()) if isinstance(result.get('data'), dict) else 'N/A'}"
        )

    def _detect_media_type(self, media_url: str, specified_type: str = "auto") -> str:
        """检测媒体类型

        参数:
            media_url: 媒体URL或文件路径
            specified_type: 指定的媒体类型（image/audio/video/auto）

        返回:
            检测到的媒体类型（image/audio/video）
        """
        if specified_type and specified_type != "auto":
            return specified_type

        # 从data URI的MIME类型检测
        if media_url.startswith("data:"):
            data_mime_type = media_url.split(";")[0].split(":")[1]
            if data_mime_type.startswith("image/"):
                return "image"
            elif data_mime_type.startswith("audio/"):
                return "audio"
            elif data_mime_type.startswith("video/"):
                return "video"

        # 从URL扩展名检测
        import mimetypes

        guessed_mime_type, _ = mimetypes.guess_type(media_url)
        if guessed_mime_type:
            if guessed_mime_type.startswith("image/"):
                return "image"
            elif guessed_mime_type.startswith("audio/"):
                return "audio"
            elif guessed_mime_type.startswith("video/"):
                return "video"

        # 从文件扩展名检测（备用方案）
        url_lower = media_url.lower()
        image_extensions = [".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg"]
        audio_extensions = [".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac", ".wma"]
        video_extensions = [".mp4", ".avi", ".mov", ".webm", ".mkv", ".flv", ".wmv"]

        for ext in image_extensions:
            if ext in url_lower:
                return "image"
        for ext in audio_extensions:
            if ext in url_lower:
                return "audio"
        for ext in video_extensions:
            if ext in url_lower:
                return "video"

        # 默认为image（向后兼容）
        return "image"

    def _get_media_mime_type(self, media_type: str, file_path: str = "") -> str:
        """获取媒体类型的MIME类型

        参数:
            media_type: 媒体类型（image/audio/video）
            file_path: 文件路径（可选，用于更精确的MIME类型检测）

        返回:
            MIME类型字符串
        """
        if file_path:
            import mimetypes

            mime_type, _ = mimetypes.guess_type(file_path)
            if mime_type:
                return mime_type

        # 默认MIME类型
        if media_type == "image":
            return "image/jpeg"
        elif media_type == "audio":
            return "audio/mpeg"
        elif media_type == "video":
            return "video/mp4"
        return "application/octet-stream"

    async def analyze_multimodal(
        self, media_url: str, media_type: str = "auto", prompt_extra: str = ""
    ) -> dict[str, str]:
        """使用全模态模型分析媒体内容（图像、音频、视频，带缓存）

        参数:
            media_url: 媒体文件 URL、file_id 或 base64 数据
            media_type: 媒体类型（image/audio/video/auto），默认为auto（自动检测）
            prompt_extra: 额外的分析指令（如"提取图中所有手机号"）

        返回:
            包含 description 和其他字段（ocr_text/transcript/subtitles）的字典
        """
        # 检测媒体类型
        detected_type = self._detect_media_type(media_url, media_type)
        logger.info(
            f"[bold yellow][媒体分析][/bold yellow] 开始分析 [magenta]{detected_type}[/magenta]: [italic]{media_url[:50]}[/italic]..."
        )

        # 生成缓存键
        cache_key = f"{detected_type}:{media_url[:100]}:{prompt_extra}"

        # 构建媒体内容
        if media_url.startswith("data:") or media_url.startswith("http"):
            media_content = media_url
        else:
            # 假设是本地文件路径，读取并转为 base64
            try:
                with open(media_url, "rb") as f:
                    media_data = base64.b64encode(f.read()).decode()
                mime_type = self._get_media_mime_type(detected_type, media_url)
                media_content = f"data:{mime_type};base64,{media_data}"
            except Exception as e:
                logger.error(f"无法读取媒体文件: {e}")
                error_msg = {
                    "image": "[图片无法读取]",
                    "audio": "[音频无法读取]",
                    "video": "[视频无法读取]",
                }.get(detected_type, "[媒体文件无法读取]")
                return {"description": error_msg}

        # 读取提示词
        async with aiofiles.open(
            "res/prompts/analyze_multimodal.txt", "r", encoding="utf-8"
        ) as f:
            prompt = await f.read()

        if prompt_extra:
            prompt += f"\n\n【补充指令】\n{prompt_extra}"

        # 构建OpenAI SDK标准格式的内容
        content_items: list[dict[str, Any]] = [{"type": "text", "text": prompt}]

        if detected_type == "image":
            content_items.append(
                {
                    "type": "image_url",
                    "image_url": {"url": media_content},
                }
            )
        elif detected_type == "audio":
            content_items.append(
                {
                    "type": "audio_url",
                    "audio_url": {"url": media_content},
                }
            )
        elif detected_type == "video":
            content_items.append(
                {
                    "type": "video_url",
                    "video_url": {"url": media_content},
                }
            )

        try:
            result = await self.request_model(
                model_config=self.vision_config,
                messages=[{"role": "user", "content": content_items}],
                max_tokens=8192,
                call_type=f"vision_{detected_type}",
            )

            logger.debug(f"媒体分析 API 响应: {result}")
            content = self._extract_choices_content(result)

            # 解析返回内容
            description = ""
            ocr_text = ""
            transcript = ""
            subtitles = ""

            for line in content.split("\n"):
                line = line.strip()
                if line.startswith("描述：") or line.startswith("描述:"):
                    description = line.split("：", 1)[-1].split(":", 1)[-1].strip()
                elif line.startswith("OCR：") or line.startswith("OCR:"):
                    ocr_text = line.split("：", 1)[-1].split(":", 1)[-1].strip()
                    if ocr_text == "无":
                        ocr_text = ""
                elif line.startswith("转写：") or line.startswith("转写:"):
                    transcript = line.split("：", 1)[-1].split(":", 1)[-1].strip()
                    if transcript == "无":
                        transcript = ""
                elif line.startswith("字幕：") or line.startswith("字幕:"):
                    subtitles = line.split("：", 1)[-1].split(":", 1)[-1].strip()
                    if subtitles == "无":
                        subtitles = ""

            # 构建结果字典
            result_dict = {"description": description or content}
            if detected_type == "image":
                result_dict["ocr_text"] = ocr_text
            elif detected_type == "audio":
                result_dict["transcript"] = transcript
            elif detected_type == "video":
                result_dict["subtitles"] = subtitles

            # 缓存结果
            self._media_analysis_cache[cache_key] = result_dict
            logger.info(f"媒体分析完成并已缓存: {media_url[:50]}... ({detected_type})")

            return result_dict

        except Exception as e:
            logger.exception(f"媒体分析失败: {e}")
            error_msg = {
                "image": "[图片分析失败]",
                "audio": "[音频分析失败]",
                "video": "[视频分析失败]",
            }.get(detected_type, "[媒体分析失败]")
            return {"description": error_msg}

    async def describe_image(
        self, image_url: str, prompt_extra: str = ""
    ) -> dict[str, str]:
        """使用全模态模型描述图片（带缓存，向后兼容方法）

        参数:
            image_url: 图片 URL 或 base64 数据
            prompt_extra: 额外的分析指令（如"提取图中所有手机号"）

        返回:
            包含 description 和 ocr_text 的字典
        """
        # 调用新的多模态分析方法
        result = await self.analyze_multimodal(image_url, "image", prompt_extra)
        # 确保返回格式包含ocr_text字段（向后兼容）
        if "ocr_text" not in result:
            result["ocr_text"] = ""
        return result

    async def summarize_chat(self, messages: str, context: str = "") -> str:
        """总结聊天记录

        参数:
            messages: 聊天记录文本
            context: 额外上下文（如之前的分段总结）

        返回:
            总结文本
        """
        async with aiofiles.open(
            "res/prompts/summarize.txt", "r", encoding="utf-8"
        ) as f:
            system_prompt = await f.read()

        user_message = messages
        if context:
            user_message = f"前文摘要：\n{context}\n\n当前对话记录：\n{messages}"

        try:
            result = await self.request_model(
                model_config=self.chat_config,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                max_tokens=8192,
                call_type="summarize",
            )

            logger.debug(f"[总结] API 响应: {result}")
            content: str = self._extract_choices_content(result)
            return content

        except Exception as e:
            logger.exception(f"[总结] 聊天记录总结失败, 错误: {e}")
            return f"总结失败: {e}"

    async def merge_summaries(self, summaries: list[str]) -> str:
        """合并多个分段总结

        参数:
            summaries: 分段总结列表

        返回:
            合并后的最终总结
        """
        if len(summaries) == 1:
            return summaries[0]

        # 构建分段内容
        segments = []
        for i, s in enumerate(summaries):
            segments.append(f"分段 {i + 1}:\n{s}")
        segments_text = "---".join(segments)

        async with aiofiles.open(
            "res/prompts/merge_summaries.txt", "r", encoding="utf-8"
        ) as f:
            prompt = await f.read()
        prompt += segments_text

        try:
            result = await self.request_model(
                model_config=self.chat_config,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=8192,
                call_type="merge_summaries",
            )

            logger.debug(f"合并总结 API 响应: {result}")
            content: str = self._extract_choices_content(result)
            return content

        except Exception as e:
            logger.exception(f"合并总结失败: {e}")
            return "\n\n---\n\n".join(summaries)

    def split_messages_by_tokens(self, messages: str, max_tokens: int) -> list[str]:
        """按 token 数量分割消息

        参数:
            messages: 完整消息文本
            max_tokens: 每段最大 token 数

        返回:
            分割后的消息列表
        """
        # 预留一些空间给系统提示和响应
        effective_max = max_tokens - 500

        lines = messages.split("\n")
        chunks: list[str] = []
        current_chunk: list[str] = []
        current_tokens = 0

        for line in lines:
            line_tokens = self.count_tokens(line)

            if current_tokens + line_tokens > effective_max and current_chunk:
                chunks.append("\n".join(current_chunk))
                current_chunk = []
                current_tokens = 0

            current_chunk.append(line)
            current_tokens += line_tokens

        if current_chunk:
            chunks.append("\n".join(current_chunk))

        return chunks

    async def generate_title(self, summary: str) -> str:
        """根据总结生成标题

        参数:
            summary: 分析报告摘要

        返回:
            生成的标题
        """

        prompt = """请根据以下 Bug 修复分析报告，生成一个简短、准确的标题（不超过 20 字），用于 FAQ 索引。
只返回标题文本，不要包含任何前缀或引号。

分析报告：
""" + summary[:2000]  # 限制长度

        try:
            result = await self.request_model(
                model_config=self.chat_config,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=100,
                call_type="generate_title",
            )

            logger.debug(f"API 响应: {result}")
            title: str = self._extract_choices_content(result).strip()
            return title

        except Exception as e:
            logger.exception(f"生成标题失败: {e}")
            return "未命名问题"

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
        """使用 AI 回答问题，支持工具调用

        参数:
            question: 用户问题
            context: 额外上下文
            send_message_callback: 发送消息回调函数
            get_recent_messages_callback: 获取最近消息回调函数（参数：chat_id, type, start, end）
            get_image_url_callback: 获取图片 URL 回调函数
            get_forward_msg_callback: 获取合并转发消息回调函数
            send_like_callback: 点赞回调函数
            sender: 消息发送器实例
            history_manager: 历史记录管理器实例
            onebot_client: OneBot 客户端实例
            extra_context: 额外的上下文数据（注入到工具执行环境中）

        返回:
            AI 的回答（如果使用了 send_message 工具，则返回空字符串）
        """
        async with aiofiles.open(
            "res/prompts/undefined.xml", "r", encoding="utf-8"
        ) as f:
            system_prompt = await f.read()

        # 注入机器人QQ号到系统提示词中
        if self.bot_qq != 0:
            # 在系统提示词开头添加机器人QQ号信息
            bot_qq_info = f"<!-- 机器人QQ号: {self.bot_qq} -->\n<!-- 你现在知道自己的QQ号是 {self.bot_qq}，请记住这个信息用于防止无限循环 -->\n\n"
            system_prompt = bot_qq_info + system_prompt

        user_message = question

        # 构建消息历史
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
        ]

        # 0. 注入记忆到 prompt
        if self.memory_storage:
            memories = self.memory_storage.get_all()
            if memories:
                memory_lines = []
                for mem in memories:
                    memory_lines.append(f"- {mem.fact}")
                memory_text = "\n".join(memory_lines)
                messages.append(
                    {
                        "role": "system",
                        "content": f"【这是你之前想要记住的东西】\n{memory_text}\n\n注意：以上是你之前主动保存的记忆，用于帮助你更好地理解用户和上下文。就事论事，就人论人，不做会话隔离。",
                    }
                )
                logger.info(f"[AI会话] 已注入 {len(memories)} 条长期记忆")
                logger.debug(f"[AI会话] 记忆内容: {memory_text}")

        # 0.1 注入end记录到 prompt（延迟加载）
        await self._ensure_summaries_loaded()
        if self._end_summaries:
            summary_text = "\n".join([f"- {s}" for s in self._end_summaries])
            messages.append(
                {
                    "role": "system",
                    "content": f"【这是你之前end时记录的事情】\n{summary_text}\n\n注意：以上是你之前在end时记录的事情，用于帮助你记住之前做了什么或以后可能要做什么。",
                }
            )
            logger.info(
                f"[AI会话] 已注入 {len(self._end_summaries)} 条短期回忆 (end 摘要)"
            )

        # 1. 自动预先获取部分历史消息作为上下文，放在当前问题之前
        if get_recent_messages_callback:
            try:
                # 默认获取 20 条作为背景
                # 优先从 RequestContext 获取（避免并发竞态条件）
                ctx = RequestContext.current()
                if ctx:
                    group_id_from_ctx = ctx.group_id
                    user_id_from_ctx = ctx.user_id
                elif extra_context:
                    group_id_from_ctx = extra_context.get("group_id")
                    user_id_from_ctx = extra_context.get("user_id")
                else:
                    group_id_from_ctx = None
                    user_id_from_ctx = None

                if group_id_from_ctx is not None:
                    chat_id = str(group_id_from_ctx)
                    msg_type = "group"
                elif user_id_from_ctx is not None:
                    chat_id = str(user_id_from_ctx)
                    msg_type = "private"
                # 向后兼容：从全局状态获取
                elif self.current_group_id is not None:
                    chat_id = str(self.current_group_id)
                    msg_type = "group"
                elif self.current_user_id is not None:
                    chat_id = str(self.current_user_id)
                    msg_type = "private"
                else:
                    chat_id = ""
                    msg_type = "group"

                recent_msgs = await get_recent_messages_callback(
                    chat_id, msg_type, 0, 20
                )
                # 格式化消息（使用统一格式）
                context_lines = []
                for msg in recent_msgs:
                    msg_type_val = msg.get("type", "group")
                    sender_name = msg.get("display_name", "未知用户")
                    sender_id = msg.get("user_id", "")
                    chat_id = msg.get("chat_id", "")
                    chat_name = msg.get("chat_name", "未知群聊")
                    timestamp = msg.get("timestamp", "")
                    text = msg.get("message", "")
                    role = msg.get("role", "member")
                    title = msg.get("title", "")

                    if msg_type_val == "group":
                        # 确保群名以"群"结尾
                        location = (
                            chat_name if chat_name.endswith("群") else f"{chat_name}群"
                        )
                        # 格式：包含 group_id, role, title
                        xml_msg = f"""<message sender="{sender_name}" sender_id="{sender_id}" group_id="{chat_id}" group_name="{chat_name}" location="{location}" role="{role}" title="{title}" time="{timestamp}">
<content>{text}</content>
</message>"""
                    else:
                        location = "私聊"
                        # 私聊格式
                        xml_msg = f"""<message sender="{sender_name}" sender_id="{sender_id}" location="{location}" time="{timestamp}">
<content>{text}</content>
</message>"""
                    context_lines.append(xml_msg)

                # 每个消息之间使用 --- 分隔
                formatted_context = "\n---\n".join(context_lines)

                # 插入历史消息作为上下文
                if formatted_context:
                    messages.append(
                        {
                            "role": "user",
                            "content": f"【历史消息存档】\n{formatted_context}\n\n注意：以上是之前的聊天记录，用于提供背景信息。每个消息之间使用 --- 分隔。接下来的用户消息才是当前正在发生的对话。",
                        }
                    )
                logger.debug("自动预获取了 20 条历史消息作为上下文")
            except Exception as e:
                logger.warning(f"自动获取历史消息失败: {e}")

        # 2. 添加当前时间
        current_time = self._get_current_time()
        messages.append(
            {
                "role": "system",
                "content": f"【当前时间】\n{current_time}\n\n注意：以上是当前的系统时间，供你参考。",
            }
        )

        # 3. 添加当前用户请求
        messages.append({"role": "user", "content": f"【当前消息】\n{user_message}"})

        # 获取工具定义
        tools = self._get_openai_tools()

        # 准备工具执行上下文
        tool_context = {
            "send_message_callback": send_message_callback,
            "get_recent_messages_callback": get_recent_messages_callback,
            "get_image_url_callback": get_image_url_callback,
            "get_forward_msg_callback": get_forward_msg_callback,
            "send_like_callback": send_like_callback,
            "send_private_message_callback": self._send_private_message_callback,
            "send_image_callback": self._send_image_callback,
            "recent_replies": self.recent_replies,
            "end_summaries": self._end_summaries,
            "end_summary_storage": self._end_summary_storage,
            "memory_storage": self.memory_storage,
            "search_wrapper": self._search_wrapper,
            "ai_client": self,
            "crawl4ai_available": _CRAWL4AI_AVAILABLE,
            "conversation_ended": False,
            "sender": sender,
            "history_manager": history_manager,
            "onebot_client": onebot_client,
            "scheduler": scheduler,
            "token_usage_storage": self._token_usage_storage,
            "agent_histories": {},  # 存储 Agent 的临时对话记录，键为 agent_name，值为消息列表
        }

        # 合并额外上下文
        if extra_context:
            tool_context.update(extra_context)

        # 工具调用循环
        max_iterations = 1000  # 防止无限循环
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

                # 提取响应
                choice = result.get("choices", [{}])[0]
                message = choice.get("message", {})
                content: str = message.get("content") or ""
                tool_calls = message.get("tool_calls", [])

                # 如果有工具调用，但 content 也不为空，说明 AI 违规在 content 里写了话
                # 忠实地按照 tool 执行，不补发 content
                if content.strip() and tool_calls:
                    logger.debug(
                        "AI 在 content 中返回了内容且存在工具调用，忽略 content，只执行工具调用"
                    )
                    content = ""

                # 如果没有工具调用，返回最终答案
                if not tool_calls:
                    logger.info(
                        f"[AI回复] 会话结束，返回最终内容 (长度={len(content)})"
                    )
                    return content

                # 添加助手响应到消息历史
                messages.append(
                    {"role": "assistant", "content": content, "tool_calls": tool_calls}
                )

                # 定义工具执行任务列表
                tool_tasks = []
                tool_call_ids = []
                tool_names = []

                for tool_call in tool_calls:
                    call_id = tool_call.get("id", "")
                    function = tool_call.get("function", {})
                    function_name = function.get("name", "")
                    function_args_str = function.get("arguments", "{}")

                    logger.info(f"[工具准备] 准备调用: {function_name} (ID={call_id})")
                    logger.debug(
                        f"[工具参数] {function_name} 参数: {function_args_str}"
                    )

                    # 解析参数
                    function_args: dict[str, Any] = {}

                    try:
                        function_args = json.loads(function_args_str)
                    except json.JSONDecodeError as e:
                        logger.error(
                            f"[工具错误] 参数解析失败: {function_args_str}, 错误: {e}"
                        )
                        # 简单的自动修复尝试
                        function_args = {}

                    # 确保 function_args 是字典类型
                    if not isinstance(function_args, dict):
                        function_args = {}

                    # 记录任务信息
                    tool_call_ids.append(call_id)
                    tool_names.append(function_name)

                    # 创建协程任务
                    tool_tasks.append(
                        self._execute_tool(function_name, function_args, tool_context)
                    )

                # 并发执行所有工具
                if tool_tasks:
                    logger.info(
                        f"[工具执行] 开始并发执行 {len(tool_tasks)} 个工具调用: {', '.join(tool_names)}"
                    )
                    tool_results = await asyncio.gather(
                        *tool_tasks, return_exceptions=True
                    )

                    # 处理结果并添加到消息历史
                    for i, tool_result in enumerate(tool_results):
                        call_id = tool_call_ids[i]
                        fname = tool_names[i]
                        content_str = ""

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

                        # 添加 tool response 消息到历史（OpenAI API 协议要求）
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": call_id,
                                "name": fname,
                                "content": content_str,
                            }
                        )

                        # 检查是否结束对话 (任意一个工具触发结束即可)
                        if tool_context.get("conversation_ended"):
                            conversation_ended = True
                            logger.info(f"[会话状态] 工具 {fname} 触发了会话结束标记")

                # 如果对话已结束，退出循环
                if conversation_ended:
                    logger.info("对话已结束（调用 end 工具）")
                    return ""

            except Exception as e:
                logger.exception(f"ask 失败: {e}")
                return f"处理失败: {e}"

        return "达到最大迭代次数，未能完成处理"

    def _get_current_time(self) -> str:
        """获取当前时间"""
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _get_openai_tools(self) -> list[dict[str, Any]]:
        """获取标准 OpenAI 格式的工具定义（包括 tools 和 agents）

        返回:
            工具定义列表
        """
        tools = self.tool_registry.get_tools_schema()
        agents = self.agent_registry.get_agents_schema()
        return tools + agents

    async def _execute_tool(
        self,
        function_name: str,
        function_args: dict[str, Any],
        context: dict[str, Any],
    ) -> str:
        """执行工具或 Agent

        参数:
            function_name: 工具或 Agent 名称
            function_args: 工具参数
            context: 执行上下文

        返回:
            执行结果
        """
        start_time = time.perf_counter()

        # 首先尝试作为 Agent 执行
        agents_schema = self.agent_registry.get_agents_schema()
        agent_names = [s.get("function", {}).get("name") for s in agents_schema]

        is_agent = function_name in agent_names
        exec_type = "Agent" if is_agent else "Tool"

        logger.info(
            f"[{exec_type}调用] 准备执行 {function_name}, 参数: {function_args}"
        )

        try:
            if is_agent:
                mcp_registry = None
                registry_token = None
                mcp_config_path = self._get_agent_mcp_config_path(function_name)
                if mcp_config_path:
                    try:
                        from Undefined.mcp import MCPToolRegistry

                        mcp_registry = MCPToolRegistry(
                            config_path=mcp_config_path,
                            tool_name_strategy="mcp",
                        )
                        await mcp_registry.initialize()
                        current = self._agent_mcp_registry_var.get()
                        new_map = dict(current) if current else {}
                        new_map[function_name] = mcp_registry
                        registry_token = self._agent_mcp_registry_var.set(new_map)
                        logger.info(
                            f"[Agent MCP] {function_name} 加载了 {len(mcp_registry.get_tools_schema())} 个工具"
                        )
                    except Exception as e:
                        logger.warning(
                            f"[Agent MCP] {function_name} MCP 初始化失败: {e}"
                        )
                        mcp_registry = None
                        registry_token = None

                # 获取该 Agent 的临时历史记录
                agent_histories = context.get("agent_histories", {})
                agent_history = agent_histories.get(function_name, [])

                # 将历史记录注入到工具执行上下文中
                agent_context = context.copy()
                agent_context["agent_history"] = agent_history
                agent_context["agent_name"] = function_name

                try:
                    result = await self.agent_registry.execute_agent(
                        function_name, function_args, agent_context
                    )
                finally:
                    if registry_token is not None:
                        self._agent_mcp_registry_var.reset(registry_token)
                    if mcp_registry:
                        await mcp_registry.close()

                # 更新该 Agent 的历史记录 (临时记录)
                # 这里我们记录 Agent 的输入 prompt 和它的输出结果作为一轮对话
                # 注意：agent_args 通常包含 'prompt' 字段
                agent_prompt = function_args.get("prompt", "")
                if agent_prompt and result:
                    agent_history.append({"role": "user", "content": agent_prompt})
                    agent_history.append({"role": "assistant", "content": str(result)})
                    agent_histories[function_name] = agent_history
            else:
                # 否则作为工具执行
                result = await self.tool_registry.execute_tool(
                    function_name, function_args, context
                )

            duration = time.perf_counter() - start_time
            # 结果摘要，如果是字符串则截取
            res_summary = (
                str(result)[:100] + "..." if len(str(result)) > 100 else str(result)
            )
            logger.info(
                f"[{exec_type}结果] {function_name} 执行成功, 耗时={duration:.2f}s, 结果: {res_summary}"
            )
            return result
        except Exception as e:
            duration = time.perf_counter() - start_time
            logger.error(
                f"[{exec_type}错误] {function_name} 执行失败, 耗时={duration:.2f}s, 错误: {e}"
            )
            raise
