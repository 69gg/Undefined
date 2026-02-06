"""Prompt building utilities."""

from __future__ import annotations

import logging
from collections import deque
from datetime import datetime
from typing import Any, Callable, Awaitable

import aiofiles

from Undefined.context import RequestContext
from Undefined.end_summary_storage import EndSummaryStorage
from Undefined.memory import MemoryStorage
from Undefined.utils.logging import log_debug_json
from Undefined.utils.resources import read_text_resource
from Undefined.utils.xml import escape_xml_attr, escape_xml_text

logger = logging.getLogger(__name__)


class PromptBuilder:
    """Construct system/user messages with memory, history, and time."""

    def __init__(
        self,
        bot_qq: int,
        memory_storage: MemoryStorage | None,
        end_summary_storage: EndSummaryStorage,
        system_prompt_path: str = "res/prompts/undefined.xml",
        runtime_config_getter: Callable[[], Any] | None = None,
    ) -> None:
        """初始化 Prompt 构建器

        参数:
            bot_qq: 机器人 QQ 号
            memory_storage: 长期记忆存储 (可选)
            end_summary_storage: 短期回忆存储
            system_prompt_path: 系统提示词文件路径
        """
        self._bot_qq = bot_qq
        self._memory_storage = memory_storage
        self._end_summary_storage = end_summary_storage
        self._system_prompt_path = system_prompt_path
        self._runtime_config_getter = runtime_config_getter
        self._end_summaries: deque[str] = deque(maxlen=100)
        self._summaries_loaded = False

    async def _ensure_summaries_loaded(self) -> None:
        if not self._summaries_loaded:
            loaded_summaries = await self._end_summary_storage.load()
            self._end_summaries.extend(loaded_summaries)
            self._summaries_loaded = True
            logger.debug(f"[AI初始化] 已加载 {len(loaded_summaries)} 条 End 摘要")

    async def _load_system_prompt(self) -> str:
        try:
            return read_text_resource(self._system_prompt_path)
        except Exception as exc:
            logger.debug("读取系统提示词失败，尝试本地路径: %s", exc)
        async with aiofiles.open(self._system_prompt_path, "r", encoding="utf-8") as f:
            return await f.read()

    async def build_messages(
        self,
        question: str,
        get_recent_messages_callback: Callable[
            [str, str, int, int], Awaitable[list[dict[str, Any]]]
        ]
        | None = None,
        extra_context: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """构建发送给 AI 的消息列表

        参数:
            question: 当前用户消息
            get_recent_messages_callback: 获取历史消息的回调函数
            extra_context: 额外的上下文信息 (如 group_id, user_id)

        返回:
            构建好的消息列表 (role/content 结构)
        """
        system_prompt = await self._load_system_prompt()
        logger.debug(
            "[Prompt] system_prompt_len=%s path=%s",
            len(system_prompt),
            self._system_prompt_path,
        )

        if self._bot_qq != 0:
            bot_qq_info = (
                f"<!-- 机器人QQ号: {self._bot_qq} -->\n"
                f"<!-- 你现在知道自己的QQ号是 {self._bot_qq}，请记住这个信息用于防止无限循环 -->\n\n"
            )
            system_prompt = bot_qq_info + system_prompt

        messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]

        if self._memory_storage:
            memories = self._memory_storage.get_all()
            if memories:
                memory_lines = [f"- {mem.fact}" for mem in memories]
                memory_text = "\n".join(memory_lines)
                messages.append(
                    {
                        "role": "system",
                        "content": (
                            "【这是你之前想要记住的东西】\n"
                            f"{memory_text}\n\n"
                            "注意：以上是你之前主动保存的记忆，用于帮助你更好地理解用户和上下文。就事论事，就人论人，不做会话隔离。"
                        ),
                    }
                )
                logger.info(f"[AI会话] 已注入 {len(memories)} 条长期记忆")
                if logger.isEnabledFor(logging.DEBUG):
                    log_debug_json(
                        logger, "[AI会话] 注入长期记忆", [mem.fact for mem in memories]
                    )

        await self._ensure_summaries_loaded()
        if self._end_summaries:
            summary_text = "\n".join([f"- {s}" for s in self._end_summaries])
            messages.append(
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
            await self._inject_recent_messages(
                messages, get_recent_messages_callback, extra_context
            )

        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        messages.append(
            {
                "role": "system",
                "content": f"【当前时间】\n{current_time}\n\n注意：以上是当前的系统时间，供你参考。",
            }
        )

        messages.append({"role": "user", "content": f"【当前消息】\n{question}"})
        logger.debug(
            "[Prompt] messages_ready=%s question_len=%s",
            len(messages),
            len(question),
        )
        return messages

    async def _inject_recent_messages(
        self,
        messages: list[dict[str, Any]],
        get_recent_messages_callback: Callable[
            [str, str, int, int], Awaitable[list[dict[str, Any]]]
        ],
        extra_context: dict[str, Any] | None,
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
            if recent_limit > 200:
                recent_limit = 200
            if recent_limit == 0:
                logger.debug("上下文历史消息注入已关闭 (limit=0)")
                return

            recent_msgs = await get_recent_messages_callback(
                chat_id,
                msg_type,
                0,
                recent_limit,
            )
            context_lines: list[str] = []
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

                safe_sender = escape_xml_attr(sender_name)
                safe_sender_id = escape_xml_attr(sender_id)
                safe_chat_id = escape_xml_attr(chat_id)
                safe_chat_name = escape_xml_attr(chat_name)
                safe_role = escape_xml_attr(role)
                safe_title = escape_xml_attr(title)
                safe_time = escape_xml_attr(timestamp)
                safe_text = escape_xml_text(str(text))

                if msg_type_val == "group":
                    location = (
                        chat_name if chat_name.endswith("群") else f"{chat_name}群"
                    )
                    safe_location = escape_xml_attr(location)
                    xml_msg = (
                        f'<message sender="{safe_sender}" sender_id="{safe_sender_id}" group_id="{safe_chat_id}" '
                        f'group_name="{safe_chat_name}" location="{safe_location}" role="{safe_role}" title="{safe_title}" '
                        f'time="{safe_time}">\n<content>{safe_text}</content>\n</message>'
                    )
                else:
                    location = "私聊"
                    safe_location = escape_xml_attr(location)
                    xml_msg = (
                        f'<message sender="{safe_sender}" sender_id="{safe_sender_id}" location="{safe_location}" '
                        f'time="{safe_time}">\n<content>{safe_text}</content>\n</message>'
                    )
                context_lines.append(xml_msg)

            formatted_context = "\n---\n".join(context_lines)

            if formatted_context:
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "【历史消息存档】\n"
                            f"{formatted_context}\n\n"
                            "注意：以上是之前的聊天记录，用于提供背景信息。每个消息之间使用 --- 分隔。接下来的用户消息才是当前正在发生的对话。"
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
