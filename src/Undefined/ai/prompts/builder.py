"""Prompt 消息构建器。"""

from __future__ import annotations

import logging
import asyncio
from collections import deque
from datetime import datetime
from typing import Any, Awaitable, Callable, Literal, Sequence

import aiofiles

from Undefined.context import RequestContext
from Undefined.end_summary_storage import (
    EndSummaryStorage,
    EndSummaryRecord,
    MAX_END_SUMMARIES,
)
from Undefined.memory import MemoryStorage
from Undefined.skills.anthropic_skills import AnthropicSkillRegistry
from Undefined.utils.coerce import safe_int
from Undefined.utils.logging import log_debug_json
from Undefined.utils.resources import read_text_resource
from Undefined.utils.xml import escape_xml_text, format_message_xml
from Undefined.ai.prompts.cognitive import (
    build_cognitive_per_message_queries,
    build_cognitive_query,
    drop_current_message_if_duplicated,
)
from Undefined.ai.prompts.system_context import (
    build_model_config_info,
    select_system_prompt_path,
)
from Undefined.ai.prompts.system_info import build_prompt_system_info

logger = logging.getLogger(__name__)


def _is_display_only_history_record(msg: dict[str, Any]) -> bool:
    if str(msg.get("message", "") or "").strip():
        return False
    webchat = msg.get("webchat")
    if not isinstance(webchat, dict):
        return False
    events = webchat.get("events")
    return (
        bool(webchat.get("display_only")) and isinstance(events, list) and bool(events)
    )


class PromptBuilder:
    """Prompt 构建器。

    协调系统提示词、记忆、认知上下文与历史消息，产出 LLM messages 列表。
    """

    def __init__(
        self,
        bot_qq: int,
        memory_storage: MemoryStorage | None,
        end_summary_storage: EndSummaryStorage,
        system_prompt_path: str = "res/prompts/undefined.xml",
        runtime_config_getter: Callable[[], Any] | None = None,
        anthropic_skill_registry: AnthropicSkillRegistry | None = None,
        cognitive_service: Any = None,
    ) -> None:
        """初始化 Prompt 构建器

        参数:
            bot_qq: 机器人 QQ 号
            memory_storage: 长期记忆存储 (可选)
            end_summary_storage: 短期回忆存储
            system_prompt_path: 系统提示词文件路径
            anthropic_skill_registry: Anthropic Skills 注册中心（可选）
        """
        self._bot_qq = bot_qq
        self._memory_storage = memory_storage
        self._end_summary_storage = end_summary_storage
        self._system_prompt_path = system_prompt_path
        self._runtime_config_getter = runtime_config_getter
        self._anthropic_skill_registry = anthropic_skill_registry
        self._cognitive_service = cognitive_service
        self._end_summaries: deque[EndSummaryRecord] = deque(maxlen=MAX_END_SUMMARIES)
        self._summaries_loaded = False

    def set_cognitive_service(self, service: Any = None) -> None:
        """更新认知记忆服务引用（支持运行时注入/替换）。"""
        self._cognitive_service = service
        logger.info(
            "[Prompt] 认知服务引用已更新: enabled=%s",
            bool(getattr(service, "enabled", False)) if service is not None else False,
        )

    def _build_cognitive_query(
        self, question: str, extra_context: dict[str, Any] | None = None
    ) -> tuple[str, bool]:
        """兼容旧测试/调用方：委托至 cognitive.build_cognitive_query。"""
        return build_cognitive_query(question, extra_context)

    def _build_model_config_info(self, runtime_config: Any) -> str:
        """兼容旧测试/调用方：委托至 system_context.build_model_config_info。"""
        return build_model_config_info(runtime_config)

    @property
    def end_summaries(self) -> deque[EndSummaryRecord]:
        """暴露短期摘要缓存，供工具执行上下文共享。"""
        return self._end_summaries

    async def _ensure_summaries_loaded(self) -> None:
        if not self._summaries_loaded:
            loaded_summaries = await self._end_summary_storage.load()
            self._end_summaries.extend(loaded_summaries)
            self._summaries_loaded = True
            logger.debug(f"[AI初始化] 已加载 {len(loaded_summaries)} 条 End 摘要")

    async def _load_each_rules(self) -> str:
        path = "res/IMPORTANT/each.md"
        try:
            return read_text_resource(path)
        except Exception:
            pass
        try:
            async with aiofiles.open(path, "r", encoding="utf-8") as f:
                return await f.read()
        except Exception:
            return ""

    def _resolve_session_scope(
        self, extra_context: dict[str, Any] | None
    ) -> tuple[str | None, int | None, int | None]:
        """从 RequestContext / extra_context 解析 request_type, group_id, user_id。"""
        request_type: str | None = None
        group_id: int | None = None
        user_id: int | None = None

        ctx = RequestContext.current()
        if ctx is not None:
            request_type = str(ctx.request_type or "") or None
            if ctx.group_id is not None:
                group_id = int(ctx.group_id)
            if ctx.user_id is not None:
                user_id = int(ctx.user_id)
            elif ctx.sender_id is not None and group_id is None:
                user_id = int(ctx.sender_id)

        # RequestContext 已给出的字段不可被 extra_context 覆盖；仅补齐缺失项
        if isinstance(extra_context, dict):
            if request_type is None and extra_context.get("request_type") is not None:
                request_type = str(extra_context.get("request_type") or "") or None
            if group_id is None and extra_context.get("group_id") is not None:
                try:
                    group_id = int(extra_context["group_id"])
                except (TypeError, ValueError):
                    pass
            if user_id is None and extra_context.get("user_id") is not None:
                try:
                    user_id = int(extra_context["user_id"])
                except (TypeError, ValueError):
                    pass
            elif (
                user_id is None
                and extra_context.get("sender_id") is not None
                and group_id is None
            ):
                try:
                    user_id = int(extra_context["sender_id"])
                except (TypeError, ValueError):
                    pass

        return request_type, group_id, user_id

    def _resolve_nagaagent_active(self, extra_context: dict[str, Any] | None) -> bool:
        if self._runtime_config_getter is None:
            return False
        try:
            runtime_config = self._runtime_config_getter()
        except Exception:
            return False
        if runtime_config is None:
            return False
        from Undefined.config.naga_policy import resolve_naga_session_allowed

        request_type, group_id, user_id = self._resolve_session_scope(extra_context)
        return resolve_naga_session_allowed(
            runtime_config,
            request_type=request_type,
            group_id=group_id,
            user_id=user_id,
        )

    async def _load_system_prompt(self, *, nagaagent_active: bool | None = None) -> str:
        system_prompt_path = select_system_prompt_path(
            default_path=self._system_prompt_path,
            runtime_config_getter=self._runtime_config_getter,
            nagaagent_active=nagaagent_active,
        )
        try:
            return read_text_resource(system_prompt_path)
        except Exception as exc:
            logger.debug("读取系统提示词失败，尝试本地路径: %s", exc)
        async with aiofiles.open(system_prompt_path, "r", encoding="utf-8") as f:
            return await f.read()

    @staticmethod
    def _format_current_input_batch(question: str) -> str:
        """Format the only live user input block for this turn."""
        return (
            "【当前输入批次】\n"
            "<current_input_batch>\n"
            f"{question}\n"
            "</current_input_batch>\n\n"
            "注意：以上才是本轮正在发生、允许你回应和写入 end.observations 的当前输入。"
            "历史消息、认知记忆、侧写、短期行动记录和系统说明都只是只读背景，"
            "只能用于消歧、防重复和理解上下文，不能作为 end.observations 的新事实来源。"
        )

    @staticmethod
    def _format_deferred_tool_names(
        deferred_tool_names: Sequence[str] | None,
    ) -> str:
        """Build the compact, stable deferred-tool directory for the model."""
        if not deferred_tool_names or isinstance(deferred_tool_names, str):
            return ""
        names = sorted(
            {str(name).strip() for name in deferred_tool_names if str(name).strip()}
        )
        if not names:
            return ""
        escaped_names = "\n".join(escape_xml_text(name) for name in names)
        return (
            f"<available_deferred_tools>\n{escaped_names}\n</available_deferred_tools>"
        )

    async def build_messages(
        self,
        question: str,
        get_recent_messages_callback: Callable[
            [str, str, int, int], Awaitable[list[dict[str, Any]]]
        ]
        | None = None,
        extra_context: dict[str, Any] | None = None,
        deferred_tool_names: Sequence[str] | None = None,
    ) -> list[dict[str, Any]]:
        """构建发送给 AI 的消息列表

        参数:
            question: 当前用户消息
            get_recent_messages_callback: 获取历史消息的回调函数
            extra_context: 额外的上下文信息 (如 group_id, user_id)
            deferred_tool_names: 可通过 tool_search 按需加载的工具名称

        返回:
            构建好的消息列表 (role/content 结构)
        """
        webchat_event_callback = (
            extra_context.get("webchat_event_callback")
            if isinstance(extra_context, dict)
            else None
        )
        if not callable(webchat_event_callback):
            webchat_event_callback = None

        async def emit_webchat_stage(stage: str, detail: Any | None = None) -> None:
            if webchat_event_callback is None:
                return
            payload: dict[str, Any] = {"stage": stage}
            if detail is not None:
                payload["detail"] = detail
            await webchat_event_callback("stage", payload)

        nagaagent_active = self._resolve_nagaagent_active(extra_context)
        system_prompt = await self._load_system_prompt(
            nagaagent_active=nagaagent_active
        )
        logger.debug(
            "[Prompt] system_prompt_len=%s path=%s nagaagent_active=%s",
            len(system_prompt),
            select_system_prompt_path(
                default_path=self._system_prompt_path,
                runtime_config_getter=self._runtime_config_getter,
                nagaagent_active=nagaagent_active,
            ),
            nagaagent_active,
        )

        if self._bot_qq != 0:
            bot_qq_info = (
                f"<!-- 机器人QQ号: {self._bot_qq} -->\n"
                f"<!-- 你现在知道自己的QQ号是 {self._bot_qq}，请记住这个信息用于防止无限循环 -->\n\n"
            )
            system_prompt = bot_qq_info + system_prompt

        messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]

        # 注入当前运行环境配置信息，让 AI 知道自己的模型名称等非隐私信息
        if self._runtime_config_getter is not None:
            try:
                runtime_config = self._runtime_config_getter()
                config_info = build_model_config_info(runtime_config)
                if config_info:
                    messages.append(
                        {
                            "role": "system",
                            "content": config_info,
                        }
                    )
                    logger.debug(
                        "[Prompt] 已注入运行环境配置信息，长度=%s",
                        len(config_info),
                    )
            except Exception as exc:
                logger.debug("读取运行环境配置失败: %s", exc)

        # 注入群聊关键词自动回复机制说明，避免模型误判历史中的系统彩蛋消息。
        is_group_context = False
        ctx = RequestContext.current()
        if ctx and ctx.group_id is not None:
            is_group_context = True
        elif extra_context and extra_context.get("group_id") is not None:
            is_group_context = True

        keyword_reply_enabled = False
        repeat_enabled = False
        repeat_threshold = 3
        inverted_question_enabled = False
        if self._runtime_config_getter is not None:
            try:
                runtime_config = self._runtime_config_getter()
                keyword_reply_enabled = bool(
                    getattr(runtime_config, "keyword_reply_enabled", False)
                )
                repeat_enabled = bool(getattr(runtime_config, "repeat_enabled", False))
                repeat_threshold = int(getattr(runtime_config, "repeat_threshold", 3))
                inverted_question_enabled = bool(
                    getattr(runtime_config, "inverted_question_enabled", False)
                )
            except Exception as exc:
                logger.debug("读取彩蛋功能配置失败: %s", exc)

        if is_group_context and keyword_reply_enabled:
            messages.append(
                {
                    "role": "system",
                    "content": (
                        "【系统行为说明 — 关键词自动回复】\n"
                        '当前群聊已开启关键词自动回复彩蛋（例如触发词"心理委员"）。'
                        "该功能由 handlers/message_flow 中的独立代码路径处理，"
                        "在消息到达你之前就已完成发送。\n\n"
                        '发送后，历史中会出现以"[系统关键词自动回复] "开头的消息。'
                        "这些消息完全由系统代码生成（固定文案如'受着''那咋了'等），"
                        "不经过你的工具调用，与你的决策无关。\n\n"
                        "阅读历史时请识别该前缀，避免误判为人格漂移或上下文异常。"
                        "除非用户主动询问，否则不要主动解释此机制。"
                    ),
                }
            )

        if is_group_context and repeat_enabled:
            repeat_desc = (
                "【系统行为说明】\n"
                f"当前群聊已开启复读彩蛋：当群聊中连续出现{repeat_threshold}条内容相同且来自不同人的消息时，"
                "系统会自动复读一条相同的消息，并在历史中写入"
                '以"[系统复读] "开头的消息。'
            )
            if inverted_question_enabled:
                repeat_desc += (
                    "\n此外，若复读触发时消息内容仅由问号组成（如?或???），"
                    "系统会发送对应数量的倒问号（¿）代替。"
                )
            repeat_desc += (
                "\n\n这类消息属于系统预设机制，不代表你在该轮主动决策。"
                "阅读历史时请识别该前缀，避免误判为人格漂移或上下文异常。"
                "除非用户主动询问，否则不要主动解释此机制。"
            )
            messages.append({"role": "system", "content": repeat_desc})

        # 注入 Anthropic Skills 元数据（Level 1: 始终加载 name + description）
        if (
            self._anthropic_skill_registry
            and self._anthropic_skill_registry.has_skills()
        ):
            skills_xml = self._anthropic_skill_registry.build_metadata_xml()
            if skills_xml:
                messages.append(
                    {
                        "role": "system",
                        "content": (
                            "【可用的 Anthropic Skills】\n"
                            f"{skills_xml}\n\n"
                            "注意：以上是可用的 Anthropic Agent Skills 列表。"
                            "当用户的请求与某个 skill 相关时，"
                            "你可以调用对应的 skill tool（tool_name 字段）"
                            "来获取该领域的详细指令和知识。"
                        ),
                    }
                )
                logger.debug(
                    "[Prompt] 已注入 %d 个 Anthropic Skills 元数据",
                    len(self._anthropic_skill_registry.get_all_skills()),
                )

        deferred_tools_xml = self._format_deferred_tool_names(deferred_tool_names)
        if deferred_tools_xml:
            messages.append({"role": "system", "content": deferred_tools_xml})
            logger.debug(
                "[Prompt] 已注入 %d 个延迟工具名称",
                len(deferred_tools_xml.splitlines()) - 2,
            )

        each_rules = await self._load_each_rules()
        if each_rules:
            messages.append(
                {
                    "role": "system",
                    "content": f"【强制规则 - 必须在进行任何操作前仔细阅读并严格遵守】\n{each_rules}",
                }
            )

        deferred_messages: list[dict[str, Any]] = []
        # 缓存友好：固定/低频系统块排在前面；按轮变化的记忆、认知、摘要、历史延迟注入。

        if self._memory_storage:
            await emit_webchat_stage("checking_long_term_memory")
            memories = self._memory_storage.get_all()
            if memories:
                memory_lines = [f"- {mem.fact}" for mem in memories]
                memory_text = "\n".join(memory_lines)
                deferred_messages.append(
                    {
                        "role": "system",
                        "content": (
                            "【memory.* 手动长期记忆（可编辑）】\n"
                            f"{memory_text}\n\n"
                            "注意：以上是你通过 memory.add 等工具主动维护的长期事实清单。"
                            "它与认知记忆（cognitive.* / end.observations 产生的事件与侧写）是两套机制。"
                            "请根据任务选择合适的记忆工具，避免混用。"
                        ),
                    }
                )
                logger.info(f"[AI会话] 已注入 {len(memories)} 条长期记忆")
                if logger.isEnabledFor(logging.DEBUG):
                    log_debug_json(
                        logger, "[AI会话] 注入长期记忆", [mem.fact for mem in memories]
                    )

        await self._ensure_summaries_loaded()
        if self._cognitive_service and getattr(
            self._cognitive_service, "enabled", False
        ):
            recent_action_inject_k = 30
            if self._runtime_config_getter is not None:
                try:
                    runtime_config = self._runtime_config_getter()
                    cog_cfg = getattr(runtime_config, "cognitive", None)
                    if cog_cfg is not None and hasattr(
                        cog_cfg, "recent_end_summaries_inject_k"
                    ):
                        recent_action_inject_k = int(
                            getattr(cog_cfg, "recent_end_summaries_inject_k")
                        )
                except Exception:
                    pass
            if recent_action_inject_k < 0:
                recent_action_inject_k = 0

            ctx = RequestContext.current()
            resolved_group_id = (
                str(ctx.group_id)
                if ctx and ctx.group_id is not None
                else (str(extra_context.get("group_id", "")) if extra_context else None)
            )
            resolved_user_id = (
                str(ctx.user_id)
                if ctx and ctx.user_id is not None
                else (str(extra_context.get("user_id", "")) if extra_context else None)
            )
            resolved_sender_id = (
                str(ctx.sender_id)
                if ctx and ctx.sender_id is not None
                else (
                    str(extra_context.get("sender_id", "")) if extra_context else None
                )
            )
            resolved_request_type = (
                str(ctx.request_type).strip()
                if ctx and ctx.request_type
                else (
                    str(extra_context.get("request_type", "")).strip()
                    if extra_context
                    else ""
                )
            )
            if not resolved_request_type:
                if resolved_group_id and str(resolved_group_id).strip():
                    resolved_request_type = "group"
                elif resolved_sender_id or resolved_user_id:
                    resolved_request_type = "private"
            cognitive_query, query_enhanced = build_cognitive_query(
                question, extra_context
            )
            recall_queries, recall_queries_enhanced = (
                build_cognitive_per_message_queries(question, extra_context)
            )
            logger.info(
                "[AI会话] 开始自动检索认知记忆: raw_query_len=%s effective_query_len=%s recall_queries=%s query_enhanced=%s recall_enhanced=%s type=%s group=%s user=%s sender=%s",
                len(question),
                len(cognitive_query),
                len(recall_queries),
                query_enhanced,
                recall_queries_enhanced,
                resolved_request_type or "",
                resolved_group_id or "",
                resolved_user_id or "",
                resolved_sender_id or "",
            )
            await emit_webchat_stage("searching_cognitive_memory")
            cognitive_context = await self._cognitive_service.build_context(
                query=cognitive_query,
                recall_queries=recall_queries,
                group_id=resolved_group_id,
                user_id=resolved_user_id,
                sender_id=resolved_sender_id,
                sender_name=str(extra_context.get("sender_name", ""))
                if extra_context
                else None,
                group_name=str(extra_context.get("group_name", ""))
                if extra_context
                else None,
                request_type=resolved_request_type or None,
            )
            if cognitive_context:
                deferred_messages.append(
                    {"role": "system", "content": cognitive_context}
                )
                logger.info(
                    "[AI会话] 已注入认知记忆上下文: context_len=%s",
                    len(cognitive_context),
                )
            else:
                logger.info("[AI会话] 自动检索完成：未命中可注入认知记忆")

            # 额外注入最近 end 行动记录，作为短期“工作记忆”，弥补史官异步入库延迟与向量检索的漏召回。
            if recent_action_inject_k > 0 and self._end_summaries:
                items = list(self._end_summaries)[-recent_action_inject_k:]
                recent_summary_lines: list[str] = []
                for item in items:
                    location_text = ""
                    location = item.get("location")
                    if isinstance(location, dict):
                        location_type = location.get("type")
                        location_name = location.get("name")
                        if (
                            location_type in {"private", "group"}
                            and isinstance(location_name, str)
                            and location_name.strip()
                        ):
                            location_text = (
                                f" ({location_type}: {location_name.strip()})"
                            )
                    recent_summary_lines.append(
                        f"- [{item.get('timestamp', '')}] {item.get('summary', '')}{location_text}"
                    )
                recent_summary_text = "\n".join(recent_summary_lines).strip()
                if recent_summary_text:
                    deferred_messages.append(
                        {
                            "role": "system",
                            "content": (
                                f"【短期行动记录（最近 {len(items)} 条，带时间）】\n"
                                f"{recent_summary_text}\n\n"
                                "注意：以上是你最近在 end 时记录的行动摘要，用于保持短期连续性。"
                                "它可能与认知记忆事件存在重复；优先以更具体、更近期的描述为准。"
                            ),
                        }
                    )
        elif self._end_summaries:
            summary_lines: list[str] = []
            for item in self._end_summaries:
                location_text = ""
                location = item.get("location")
                if isinstance(location, dict):
                    location_type = location.get("type")
                    location_name = location.get("name")
                    if (
                        location_type in {"private", "group"}
                        and isinstance(location_name, str)
                        and location_name.strip()
                    ):
                        location_text = f" ({location_type}: {location_name.strip()})"
                summary_lines.append(
                    f"- [{item['timestamp']}] {item['summary']}{location_text}"
                )
            summary_text = "\n".join(summary_lines)
            deferred_messages.append(
                {
                    "role": "system",
                    "content": (
                        "【这是你之前end时记录的事情】\n"
                        f"{summary_text}\n\n"
                        "注意：以上是你之前在end时记录的事情，用于帮助你记住之前做了什么或以后可能要做什么。"
                    ),
                }
            )
            logger.info(
                f"[AI会话] 已注入 {len(self._end_summaries)} 条短期回忆 (end 摘要)"
            )
            if logger.isEnabledFor(logging.DEBUG):
                log_debug_json(
                    logger, "[AI会话] 注入短期回忆", list(self._end_summaries)
                )

        if get_recent_messages_callback:
            await emit_webchat_stage("loading_chat_history")
            await self._inject_recent_messages(
                deferred_messages, get_recent_messages_callback, extra_context, question
            )

        # 记忆/认知/历史等上下文统一排在主 system 之后、当前消息之前
        messages.extend(deferred_messages)

        if self._runtime_config_getter is not None:
            try:
                system_info = await asyncio.to_thread(
                    self._build_prompt_system_info_from_runtime_config
                )
                if system_info:
                    messages.append({"role": "system", "content": system_info})
                    logger.debug(
                        "[Prompt] 已注入当前系统信息，长度=%s",
                        len(system_info),
                    )
            except Exception as exc:
                logger.debug("读取当前系统信息失败: %s", exc)

        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        messages.append(
            {
                "role": "system",
                "content": f"【当前时间】\n{current_time}\n\n注意：以上是当前的系统时间，供你参考。",
            }
        )

        messages.append(
            {"role": "user", "content": self._format_current_input_batch(question)}
        )
        logger.debug(
            "[Prompt] messages_ready=%s question_len=%s",
            len(messages),
            len(question),
        )
        return messages

    def _build_prompt_system_info_from_runtime_config(self) -> str:
        if self._runtime_config_getter is None:
            return ""
        runtime_config = self._runtime_config_getter()
        system_info_config = getattr(runtime_config, "prompt_system_info", None)
        return build_prompt_system_info(system_info_config)

    def _resolve_chat_scope(
        self, extra_context: dict[str, Any] | None
    ) -> tuple[Literal["group", "private"], int] | None:
        ctx = RequestContext.current()

        # 解析顺序：RequestContext 会话类型 > extra_context 回退
        if ctx and ctx.request_type == "group" and ctx.group_id is not None:
            group_id = safe_int(ctx.group_id)
            if group_id is not None:
                return ("group", group_id)
            return None
        if ctx and ctx.request_type == "private" and ctx.user_id is not None:
            user_id = safe_int(ctx.user_id)
            if user_id is not None:
                return ("private", user_id)
            return None

        if extra_context and extra_context.get("group_id") is not None:
            group_id = safe_int(extra_context.get("group_id"))
            if group_id is not None:
                return ("group", group_id)
            return None
        if extra_context and extra_context.get("user_id") is not None:
            user_id = safe_int(extra_context.get("user_id"))
            if user_id is not None:
                return ("private", user_id)
            return None

        return None

    async def _inject_recent_messages(
        self,
        messages: list[dict[str, Any]],
        get_recent_messages_callback: Callable[
            [str, str, int, int], Awaitable[list[dict[str, Any]]]
        ],
        extra_context: dict[str, Any] | None,
        question: str,
    ) -> None:
        try:
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
            else:
                chat_id = ""
                msg_type = "group"

            recent_limit = 20
            if self._runtime_config_getter is not None:
                try:
                    runtime_config = self._runtime_config_getter()
                    if hasattr(runtime_config, "get_context_recent_messages_limit"):
                        recent_limit = int(
                            runtime_config.get_context_recent_messages_limit()
                        )
                except Exception as exc:
                    logger.debug("读取上下文历史条数配置失败: %s", exc)

            if recent_limit < 0:
                recent_limit = 0
            if recent_limit == 0:
                logger.debug("上下文历史消息注入已关闭 (limit=0)")
                return

            recent_msgs = await get_recent_messages_callback(
                chat_id,
                msg_type,
                0,
                recent_limit,
            )
            recent_msgs = drop_current_message_if_duplicated(recent_msgs, question)
            recent_msgs = [
                msg for msg in recent_msgs if not _is_display_only_history_record(msg)
            ]
            context_lines: list[str] = [format_message_xml(msg) for msg in recent_msgs]

            formatted_context = "\n---\n".join(context_lines)

            if formatted_context:
                messages.append(
                    {
                        "role": "system",
                        "content": (
                            "【历史消息存档】（只读上下文）\n"
                            "以下是之前的聊天记录，仅用于背景理解、实体消歧和防重复检查。"
                            "它们不属于当前输入批次，不是新请求，也不能作为 end.observations 的新事实来源。\n"
                            '<history_archive readonly="true">\n'
                            f"{formatted_context}\n"
                            "</history_archive>\n\n"
                            "注意：每个历史消息之间使用 --- 分隔；后续单独的当前输入块才是本轮正在发生的对话。"
                        ),
                    }
                )
            logger.debug(f"自动预获取了 {len(context_lines)} 条历史消息作为上下文")
            if logger.isEnabledFor(logging.DEBUG):
                log_debug_json(
                    logger,
                    "[Prompt] 历史消息上下文",
                    context_lines,
                )
        except Exception as exc:
            logger.warning(f"自动获取历史消息失败: {exc}")


__all__ = ["PromptBuilder"]
