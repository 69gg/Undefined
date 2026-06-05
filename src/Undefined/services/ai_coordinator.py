import asyncio
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from Undefined.attachments import (
    attachment_refs_to_xml,
    build_attachment_scope,
    dispatch_pending_file_sends,
    render_message_with_pic_placeholders,
)
from Undefined.config import Config
from Undefined.context import RequestContext
from Undefined.context_resource_registry import collect_context_resources
from Undefined.render import render_html_to_image, render_markdown_to_html
from Undefined.services.model_pool import ModelPoolService
from Undefined.services.queue_manager import QueueManager, QUEUE_LANE_BACKGROUND
from Undefined.services.message_batcher import (
    BufferedMessage,
    MessageBatcher,
    make_scope,
)
from Undefined.utils.history import MessageHistoryManager
from Undefined.utils.sender import MessageSender
from Undefined.utils.scheduler import TaskScheduler
from Undefined.services.security import SecurityService
from Undefined.utils.recent_messages import get_recent_messages_prefer_local
from Undefined.utils.resources import read_text_resource
from Undefined.utils.xml import escape_xml_attr, escape_xml_text

logger = logging.getLogger(__name__)


_STATS_ANALYSIS_PROMPT_PATH = "res/prompts/stats_analysis.txt"
_STATS_ANALYSIS_FALLBACK_PROMPT = (
    "你是一位专业的数据分析师。请根据以下 Token 使用统计数据提供分析：\n\n"
    "{data_summary}\n\n"
    "请从整体概况、趋势、模型效率、成本结构、异常点和优化建议进行总结，"
    "语言简洁，建议可执行。"
)


_GROUP_STRATEGY_FOOTER = """

 【回复策略 - 更克制，纯表情包才前置检索】
 1. 如果用户 @ 了你或拍了拍你 → 【必须回复】
 2. 如果消息中明确提到了你（根据上下文判断用户是否在叫你或维持对话流） → 【必须回复】
 3. 如果问题明确涉及某个项目/代码/部署细节（用户明确点名或上下文明确指向） → 【酌情回复，必要时先查证再回答】
 4. 其他技术问题 → 【酌情回复，直接按用户提到的对象回答，不要引入无关的项目名/工具名作背景】
 5. 先判断当前输入批次（无连续消息说明时就是最后一条消息）是不是在对你说：
    - 先看 sender_id、@/reply、前后文对话对象和当前群聊环境；不要先入为主把"你"、"AI"、"bot"、"机器人"当作在叫 Undefined
    - 泛称或讨论其他 AI/bot/机器人时不算叫你；无法确认指向 Undefined 时默认不回复
    - 如果明显是在和别人说话 → 【不要回复】
    - 如果你不能确定是不是在和你说话 → 【默认不回复】
    - 只有明确在和你说，或多人公开讨论且对话明显开放时，才进入下一步
  6. 群聊里的主动参与只保留给公开、开放的技术或项目讨论：
    - 只在多人公开讨论代码、AI、开发工具、项目进展、技术 bug 等，且不是别人之间定向交流时，才可以【极低频参与】
    - 默认更倾向不参与；不要长篇大论，一两句点到为止；如果别人已经在深入讨论且不需要你，保持沉默
    - 轻松互动、玩梗、吐槽本身不构成参与许可；只有在你已经决定要回复，且本轮明确是纯表情包/纯反应图时，才优先考虑表情包表达
  7. 对于已经决定要回复的场景（包括被@、被拍一拍、轻量答疑，以及少量符合条件的主动参与）：
    - 只有明确纯表情包回复才先检索表情包，再用 memes.send_meme_by_uid 单独发一条图片消息
    - 其他需要文字承接、解释、答疑、推进任务、确认操作或表达具体态度的场景，第一轮必须优先把必要文字回复做好并调用 send_message
    - 如果确实还想补表情包，把 memes.search_memes 和 memes.send_meme_by_uid 放到文字发送后的后续响应轮次，不要阻塞首条文字回复
    - 不要发送任何敷衍消息（如'懒得掺和'、'哦'等）；不想回复就直接调用 end
    - 严肃、任务型、高信息密度场景少发表情包，避免打断信息传递
    - 绝不要刷屏、绝不要每条都回
  8. 对于本来就会回复的场景（私聊、被拍一拍、被@、轻量答疑）：
    - 如果表情包能自然增强语气、缓和语气或让表达更像真人，也只能作为后续可选补充
    - 但不要为了发表情包而牺牲信息传递；信息密度优先时仍以文字为主

 简单说：像个极度安静的群友。主动插话只留给公开、开放的技术或项目讨论；明显对别人说或拿不准时就闭嘴。已经决定要回复时，除非明确是纯表情包回复，否则先把文字回复做好，表情包最后再搜。"""


_PRIVATE_STRATEGY_FOOTER = """

【私聊消息】
这是私聊消息，用户专门来找你说话。你可以自由选择是否回复：
- 如果想回复，先调用 send_message 工具发送回复内容，然后调用 end 结束对话
- 只有明确纯表情包回复时，才先用 memes.search_memes 查表情包，再用 memes.send_meme_by_uid 单独发图；其他场景先把文字回复做好，表情包最后再搜或不搜
- 如果不想回复，直接调用 end 结束对话即可"""


class AICoordinator:
    """AI 协调器，处理 AI 回复逻辑、Prompt 构建和队列管理"""

    def __init__(
        self,
        config: Config,
        ai: Any,  # AIClient
        queue_manager: QueueManager,
        history_manager: MessageHistoryManager,
        sender: MessageSender,
        onebot: Any,  # OneBotClient
        scheduler: TaskScheduler,
        security: SecurityService,
        command_dispatcher: Any = None,
    ) -> None:
        self.config = config
        self.ai = ai
        self.queue_manager = queue_manager
        self.history_manager = history_manager
        self.sender = sender
        self.onebot = onebot
        self.scheduler = scheduler
        self.security = security
        self.command_dispatcher = command_dispatcher
        self.model_pool = ModelPoolService(ai, config, sender)
        # batcher 由外部（handlers/message_flow）创建并通过 set_batcher 注入；未注入时所有消息按单条流程直送。
        self._batcher: MessageBatcher | None = None

    def set_batcher(self, batcher: MessageBatcher | None) -> None:
        """注入消息合并器；传 None 等同于禁用合并。"""
        self._batcher = batcher

    @property
    def batcher(self) -> MessageBatcher | None:
        return self._batcher

    async def handle_batched_dispatch(self, items: list[BufferedMessage]) -> None:
        """:class:`MessageBatcher` 的 flush_callback：把一批消息组装为单次请求并入队。"""
        if not items:
            return
        await self._dispatch_grouped_request(items)

    async def handle_auto_reply(
        self,
        group_id: int,
        sender_id: int,
        text: str,
        message_content: list[dict[str, Any]],
        attachments: list[dict[str, str]] | None = None,
        is_poke: bool = False,
        sender_name: str = "未知用户",
        group_name: str = "未知群聊",
        sender_role: str = "member",
        sender_title: str = "",
        sender_level: str = "",
        trigger_message_id: int | None = None,
        is_fake_at: bool = False,
    ) -> None:
        """群聊自动回复入口：根据消息内容、命中情况和安全检测决定是否回复

        参数:
            group_id: 群号
            sender_id: 发送者 QQ
            text: 消息纯文本
            message_content: 结构化原始消息内容
            is_poke: 是否为拍一拍触发
            sender_name: 发送者昵称
            group_name: 群名称
            sender_role: 发送者角色 (owner/admin/member)
            sender_title: 发送者群头衔
            is_fake_at: 是否为假@（纯文本 @昵称）触发
        """
        is_at_bot = is_poke or is_fake_at or self._is_at_bot(message_content)
        logger.debug(
            "[自动回复] group=%s sender=%s at_bot=%s fake_at=%s text_len=%s",
            group_id,
            sender_id,
            is_at_bot,
            is_fake_at,
            len(text),
        )

        if sender_id != self.config.superadmin_qq:
            logger.debug(f"[Security] 注入检测: group={group_id}, user={sender_id}")
            if await self.security.detect_injection(text, message_content):
                logger.warning(
                    f"[Security] 检测到注入攻击: group={group_id}, user={sender_id}"
                )
                await self.history_manager.modify_last_group_message(
                    group_id, sender_id, "<这句话检测到用户进行注入，已删除>"
                )
                if is_at_bot:
                    await self._handle_injection_response(
                        group_id, text, sender_id=sender_id
                    )
                return

        scope = make_scope(group_id=group_id)
        item = BufferedMessage(
            scope=scope,
            sender_id=sender_id,
            text=text,
            message_content=list(message_content),
            attachments=list(attachments or []),
            sender_name=sender_name,
            arrival_time=time.time(),
            is_private=False,
            trigger_message_id=trigger_message_id,
            is_poke=is_poke,
            is_at_bot=is_at_bot,
            is_fake_at=is_fake_at,
            group_id=group_id,
            group_name=group_name,
            sender_role=sender_role,
            sender_title=sender_title,
            sender_level=sender_level,
        )

        # 路由：拍一拍 → 永远旁路；否则按 batcher 启用情况与 @bot 处理规则决定
        if is_poke:
            await self._dispatch_grouped_request([item])
            return

        batcher = getattr(self, "_batcher", None)
        if batcher is not None and batcher.is_enabled_for(is_group=True):
            if is_at_bot and batcher.has_buffer(scope, sender_id):
                # 已有 buffer 时再来一条 @bot：单独立即处理，不打断现有 buffer
                logger.info(
                    "[自动回复] batch 内 @bot 旁路立即处理: group=%s sender=%s",
                    group_id,
                    sender_id,
                )
                await self._dispatch_grouped_request([item])
                return
            await batcher.submit(item)
            return

        await self._dispatch_grouped_request([item])

    async def handle_private_reply(
        self,
        user_id: int,
        text: str,
        message_content: list[dict[str, Any]],
        attachments: list[dict[str, str]] | None = None,
        is_poke: bool = False,
        sender_name: str = "未知用户",
        trigger_message_id: int | None = None,
    ) -> None:
        """处理私聊消息入口，决定回复策略并进行安全检测"""
        logger.debug("[私聊回复] user=%s text_len=%s", user_id, len(text))
        if user_id != self.config.superadmin_qq:
            if await self.security.detect_injection(text, message_content):
                logger.warning(f"[Security] 私聊注入攻击: user_id={user_id}")
                await self.history_manager.modify_last_private_message(
                    user_id, "<这句话检测到用户进行注入，已删除>"
                )
                await self._handle_injection_response(user_id, text, is_private=True)
                return

        scope = make_scope(user_id=user_id)
        item = BufferedMessage(
            scope=scope,
            sender_id=user_id,
            text=text,
            message_content=list(message_content),
            attachments=list(attachments or []),
            sender_name=sender_name,
            arrival_time=time.time(),
            is_private=True,
            trigger_message_id=trigger_message_id,
            is_poke=is_poke,
        )

        if is_poke:
            await self._dispatch_grouped_request([item])
            return

        batcher = getattr(self, "_batcher", None)
        if batcher is not None and batcher.is_enabled_for(is_group=False):
            await batcher.submit(item)
            return

        await self._dispatch_grouped_request([item])

    async def execute_reply(self, request: dict[str, Any]) -> None:
        """执行排队中的回复请求（由 QueueManager 分发调用）

        参数:
            request: 包含请求类型和必要元数据的请求字典
        """
        """执行回复请求（由 QueueManager 调用）"""
        req_type = request.get("type", "unknown")
        logger.debug("[执行请求] type=%s keys=%s", req_type, list(request.keys()))
        batch_token = request.get("_message_batcher_token")
        if bool(getattr(batch_token, "cancelled", False)):
            logger.info(
                "[MessageBatcher] 跳过已取消的投机请求: type=%s scope=%s sender=%s batch=%s",
                req_type,
                getattr(batch_token, "scope", ""),
                getattr(batch_token, "sender_id", ""),
                getattr(batch_token, "batch_id", ""),
            )
            return
        if req_type == "auto_reply":
            await self._execute_auto_reply(request)
        elif req_type == "private_reply":
            await self._execute_private_reply(request)
        elif req_type == "stats_analysis":
            await self._execute_stats_analysis(request)
        elif req_type == "agent_intro_generation":
            await self._execute_agent_intro_generation(request)
        elif req_type in {"queued_llm_call", "background_llm_call"}:
            await self._execute_queued_llm_call(request)

    async def _execute_auto_reply(self, request: dict[str, Any]) -> None:
        group_id = request["group_id"]
        sender_id = request["sender_id"]
        sender_name = str(request.get("sender_name") or "未知用户")
        group_name = str(request.get("group_name") or "未知群聊")
        full_question = request["full_question"]
        trigger_message_id = request.get("trigger_message_id")
        message_ids = [
            str(item).strip()
            for item in request.get("message_ids", [])
            if str(item).strip()
        ]
        # 用于向 batcher 注册 inflight 任务（仅当本请求源自合并桶时生效）
        batcher_scope: str | None = make_scope(group_id=group_id) if group_id else None

        async with RequestContext(
            request_type="group",
            group_id=group_id,
            sender_id=sender_id,
            user_id=sender_id,
        ) as ctx:

            async def send_msg_cb(message: str, reply_to: int | None = None) -> None:
                await self.sender.send_group_message(
                    group_id,
                    message,
                    reply_to=reply_to,
                    history_message=message,
                )

            async def get_recent_cb(
                chat_id: str, msg_type: str, start: int, end: int
            ) -> list[dict[str, Any]]:
                return await get_recent_messages_prefer_local(
                    chat_id=chat_id,
                    msg_type=msg_type,
                    start=start,
                    end=end,
                    onebot_client=self.onebot,
                    history_manager=self.history_manager,
                    bot_qq=self.config.bot_qq,
                    attachment_registry=getattr(self.ai, "attachment_registry", None),
                    group_name_hint=group_name,
                )

            async def send_private_cb(
                uid: int, msg: str, reply_to: int | None = None
            ) -> None:
                await self.sender.send_private_message(uid, msg, reply_to=reply_to)

            async def send_img_cb(tid: int, mtype: str, path: str) -> None:
                await self._send_image(tid, mtype, path)

            async def send_like_cb(uid: int, times: int = 1) -> None:
                await self.onebot.send_like(uid, times)

            ai_client = self.ai
            memory_storage = self.ai.memory_storage
            runtime_config = self.ai.runtime_config
            sender = self.sender
            history_manager = self.history_manager
            onebot_client = self.onebot
            scheduler = self.scheduler
            send_message_callback = send_msg_cb
            get_recent_messages_callback = get_recent_cb
            get_image_url_callback = self.onebot.get_image
            get_forward_msg_callback = self.onebot.get_forward_msg
            send_like_callback = send_like_cb
            send_private_message_callback = send_private_cb
            send_image_callback = send_img_cb
            resource_vars = dict(globals())
            resource_vars.update(locals())
            resources = collect_context_resources(resource_vars)
            for key, value in resources.items():
                if value is not None:
                    ctx.set_resource(key, value)
            if trigger_message_id is not None:
                ctx.set_resource("trigger_message_id", trigger_message_id)
            if message_ids:
                ctx.set_resource("message_ids", list(message_ids))
            if request.get("_queue_lane"):
                ctx.set_resource("queue_lane", request.get("_queue_lane"))
            logger.debug(
                "[上下文资源] group=%s keys=%s",
                group_id,
                ", ".join(sorted(resources.keys())),
            )

            try:
                # 把当前 task 注册到 batcher，使其有能力在新消息到达时取消本次 LLM 调用
                batcher = getattr(self, "_batcher", None)
                current_task = asyncio.current_task()
                registered_task: asyncio.Task[Any] | None = None
                if (
                    batcher is not None
                    and batcher_scope is not None
                    and current_task is not None
                ):
                    batcher.register_inflight(
                        batcher_scope, sender_id, current_task, ctx
                    )
                    registered_task = current_task
                try:
                    await self.ai.ask(
                        full_question,
                        send_message_callback=send_msg_cb,
                        get_recent_messages_callback=get_recent_cb,
                        get_image_url_callback=self.onebot.get_image,
                        get_forward_msg_callback=self.onebot.get_forward_msg,
                        send_like_callback=send_like_cb,
                        sender=self.sender,
                        history_manager=self.history_manager,
                        onebot_client=self.onebot,
                        scheduler=self.scheduler,
                        extra_context={
                            "render_html_to_image": render_html_to_image,
                            "render_markdown_to_html": render_markdown_to_html,
                            "group_id": group_id,
                            "user_id": sender_id,
                            "is_at_bot": bool(request.get("is_at_bot", False)),
                            "sender_name": sender_name,
                            "group_name": group_name,
                            "message_ids": list(message_ids),
                            "batched_count": int(request.get("batched_count", 1) or 1),
                            "current_input_is_batched": int(
                                request.get("batched_count", 1) or 1
                            )
                            > 1,
                        },
                    )
                finally:
                    if (
                        batcher is not None
                        and batcher_scope is not None
                        and registered_task is not None
                    ):
                        batcher.unregister_inflight(
                            batcher_scope, sender_id, registered_task
                        )
            except asyncio.CancelledError:
                # 投机预发送被新消息抢占取消：不写错误日志、不重试
                logger.info(
                    "[自动回复] 任务被取消（投机抢占）: group=%s sender=%s",
                    group_id,
                    sender_id,
                )
                raise
            except Exception:
                logger.exception("自动回复执行出错")
                raise

    async def _execute_private_reply(self, request: dict[str, Any]) -> None:
        user_id = request["user_id"]
        sender_name = str(request.get("sender_name") or "未知用户")
        full_question = request["full_question"]
        trigger_message_id = request.get("trigger_message_id")
        message_ids = [
            str(item).strip()
            for item in request.get("message_ids", [])
            if str(item).strip()
        ]
        batcher_scope: str | None = make_scope(user_id=user_id)

        async with RequestContext(
            request_type="private",
            user_id=user_id,
            sender_id=user_id,
        ) as ctx:

            async def send_msg_cb(message: str, reply_to: int | None = None) -> None:
                await self.sender.send_private_message(
                    user_id, message, reply_to=reply_to
                )

            async def get_recent_cb(
                chat_id: str, msg_type: str, start: int, end: int
            ) -> list[dict[str, Any]]:
                return await get_recent_messages_prefer_local(
                    chat_id=chat_id,
                    msg_type=msg_type,
                    start=start,
                    end=end,
                    onebot_client=self.onebot,
                    history_manager=self.history_manager,
                    bot_qq=self.config.bot_qq,
                    attachment_registry=getattr(self.ai, "attachment_registry", None),
                )

            async def send_img_cb(tid: int, mtype: str, path: str) -> None:
                await self._send_image(tid, mtype, path)

            async def send_like_cb(uid: int, times: int = 1) -> None:
                await self.onebot.send_like(uid, times)

            async def send_private_cb(
                uid: int, msg: str, reply_to: int | None = None
            ) -> None:
                await self.sender.send_private_message(uid, msg, reply_to=reply_to)

            ai_client = self.ai
            memory_storage = self.ai.memory_storage
            runtime_config = self.ai.runtime_config
            sender = self.sender
            history_manager = self.history_manager
            onebot_client = self.onebot
            scheduler = self.scheduler
            send_message_callback = send_msg_cb
            get_recent_messages_callback = get_recent_cb
            get_image_url_callback = self.onebot.get_image
            get_forward_msg_callback = self.onebot.get_forward_msg
            send_like_callback = send_like_cb
            send_private_message_callback = send_private_cb
            send_image_callback = send_img_cb
            resource_vars = dict(globals())
            resource_vars.update(locals())
            resources = collect_context_resources(resource_vars)
            for key, value in resources.items():
                if value is not None:
                    ctx.set_resource(key, value)
            if trigger_message_id is not None:
                ctx.set_resource("trigger_message_id", trigger_message_id)
            if message_ids:
                ctx.set_resource("message_ids", list(message_ids))
            if request.get("_queue_lane"):
                ctx.set_resource("queue_lane", request.get("_queue_lane"))
            logger.debug(
                "[上下文资源] private user=%s keys=%s",
                user_id,
                ", ".join(sorted(resources.keys())),
            )

            try:
                batcher = getattr(self, "_batcher", None)
                current_task = asyncio.current_task()
                registered_task: asyncio.Task[Any] | None = None
                if (
                    batcher is not None
                    and batcher_scope is not None
                    and current_task is not None
                ):
                    batcher.register_inflight(batcher_scope, user_id, current_task, ctx)
                    registered_task = current_task
                try:
                    result = await self.ai.ask(
                        full_question,
                        send_message_callback=send_msg_cb,
                        get_recent_messages_callback=get_recent_cb,
                        get_image_url_callback=self.onebot.get_image,
                        get_forward_msg_callback=self.onebot.get_forward_msg,
                        send_like_callback=send_like_cb,
                        sender=self.sender,
                        history_manager=self.history_manager,
                        onebot_client=self.onebot,
                        scheduler=self.scheduler,
                        extra_context={
                            "render_html_to_image": render_html_to_image,
                            "render_markdown_to_html": render_markdown_to_html,
                            "user_id": user_id,
                            "is_private_chat": True,
                            "sender_name": sender_name,
                            "selected_model_name": request.get("selected_model_name"),
                            "message_ids": list(message_ids),
                            "batched_count": int(request.get("batched_count", 1) or 1),
                            "current_input_is_batched": int(
                                request.get("batched_count", 1) or 1
                            )
                            > 1,
                        },
                    )
                finally:
                    if (
                        batcher is not None
                        and batcher_scope is not None
                        and registered_task is not None
                    ):
                        batcher.unregister_inflight(
                            batcher_scope, user_id, registered_task
                        )
                if result:
                    scope_key = build_attachment_scope(
                        user_id=user_id,
                        request_type="private",
                    )
                    rendered = await render_message_with_pic_placeholders(
                        str(result),
                        registry=self.ai.attachment_registry,
                        scope_key=scope_key,
                        strict=False,
                    )
                    await self.sender.send_private_message(
                        user_id,
                        rendered.delivery_text,
                        history_message=rendered.history_text,
                    )
                    await dispatch_pending_file_sends(
                        rendered,
                        sender=self.sender,
                        target_type="private",
                        target_id=user_id,
                        registry=self.ai.attachment_registry,
                    )
            except asyncio.CancelledError:
                logger.info("[私聊回复] 任务被取消（投机抢占）: user=%s", user_id)
                raise
            except Exception:
                logger.exception("私聊回复执行出错")
                raise

    async def _execute_stats_analysis(self, request: dict[str, Any]) -> None:
        """执行 stats 命令的 AI 分析"""
        group_id = request["group_id"]
        request_id = request.get("request_id")
        data_summary = request.get("data_summary", "")

        if not request_id:
            logger.warning("[统计分析] 缺少 request_id，群=%s", group_id)
            return
        try:
            prompt_template = _STATS_ANALYSIS_FALLBACK_PROMPT
            try:
                loaded_prompt = read_text_resource(_STATS_ANALYSIS_PROMPT_PATH).strip()
                if loaded_prompt:
                    prompt_template = loaded_prompt
            except Exception as exc:
                logger.warning("[统计分析] 读取提示词失败，使用内置模板: %s", exc)

            if "{data_summary}" not in prompt_template:
                logger.warning(
                    "[统计分析] 提示词缺少 {data_summary} 占位符，自动追加",
                )
                prompt_template = f"{prompt_template}\n\n{{data_summary}}"

            safe_data_summary = str(data_summary).strip() or "暂无统计数据摘要"
            try:
                full_prompt = prompt_template.format(data_summary=safe_data_summary)
            except Exception as exc:
                logger.warning("[统计分析] 提示词渲染失败，使用回退模板: %s", exc)
                full_prompt = _STATS_ANALYSIS_FALLBACK_PROMPT.format(
                    data_summary=safe_data_summary
                )

            messages = [
                {"role": "system", "content": "你是一位专业的数据分析师。"},
                {"role": "user", "content": full_prompt},
            ]

            result = await self.ai.submit_queued_llm_call(
                model_config=self.config.chat_model,
                messages=messages,
                max_tokens=2048,
                call_type="stats_analysis",
                queue_lane=request.get("_queue_lane"),
            )

            choices = result.get("choices", [{}])
            if choices:
                content = choices[0].get("message", {}).get("content", "")
                analysis = content.strip()
            else:
                analysis = "AI 分析未能生成结果"

            if not analysis:
                analysis = "AI 分析结果为空，建议稍后重试。"

            logger.info(
                "[统计分析] 分析完成: group=%s length=%s request_id=%s",
                group_id,
                len(analysis),
                request_id,
            )

            if self.command_dispatcher:
                self.command_dispatcher.set_stats_analysis_result(
                    group_id, request_id, analysis
                )

        except Exception as exc:
            logger.exception("[统计分析] AI 分析失败: %s", exc)
            if self.command_dispatcher:
                self.command_dispatcher.set_stats_analysis_result(
                    group_id, request_id, ""
                )

    async def _execute_queued_llm_call(self, request: dict[str, Any]) -> None:
        """执行队列中的 LLM 子请求。"""
        request_id = request.get("request_id", "")
        retry_count = int(request.get("_retry_count", 0) or 0)
        queue_lane = str(request.get("_queue_lane") or QUEUE_LANE_BACKGROUND)
        call_type = str(request.get("call_type", "background") or "background")
        try:
            result = await self.ai.request_model(
                model_config=request["model_config"],
                messages=request["messages"],
                tools=request.get("tools"),
                tool_choice=request.get("tool_choice", "auto"),
                call_type=call_type,
                max_tokens=request.get("max_tokens")
                or getattr(request["model_config"], "max_tokens", 4096),
                transport_state=request.get("transport_state"),
            )
            self.ai.set_llm_call_result(request_id, result)
            if retry_count > 0:
                logger.info(
                    "[queued_llm_retry_success] request_id=%s call_type=%s model=%s lane=%s retry=%s",
                    request_id,
                    call_type,
                    getattr(request["model_config"], "model_name", "default"),
                    queue_lane,
                    retry_count,
                )
        except Exception as exc:
            retry_count = request.get("_retry_count", 0)
            if retry_count >= self.config.ai_request_max_retries:
                self.ai.set_llm_call_result(request_id, exc)
            raise

    async def _execute_agent_intro_generation(self, request: dict[str, Any]) -> None:
        """执行 Agent 自我介绍生成请求"""
        request_id = request.get("request_id")
        agent_name = request.get("agent_name")

        if not request_id or not agent_name:
            logger.warning(
                "[Agent介绍生成] 缺少必要参数: request_id=%s agent_name=%s",
                request_id,
                agent_name,
            )
            return

        try:
            from Undefined.skills.agents.intro_generator import AgentIntroGenerator

            agent_intro_generator = self.ai._agent_intro_generator
            if not isinstance(agent_intro_generator, AgentIntroGenerator):
                logger.error("[Agent介绍生成] 无法获取 AgentIntroGenerator 实例")
                return

            (
                system_prompt,
                user_prompt,
            ) = await agent_intro_generator.get_intro_prompt_and_context(agent_name)

            messages = [
                {"role": "system", "content": system_prompt or "你是一位智能助手。"},
                {"role": "user", "content": user_prompt},
            ]

            result = await self.ai.submit_queued_llm_call(
                model_config=self.ai.agent_config,
                messages=messages,
                max_tokens=agent_intro_generator.config.max_tokens,
                call_type=f"agent:{agent_name}",
                queue_lane=request.get("_queue_lane"),
            )

            choices = result.get("choices", [{}])
            if choices:
                content = choices[0].get("message", {}).get("content", "")
                generated_content = content.strip()
            else:
                generated_content = ""

            logger.info(
                "[Agent介绍生成] 生成完成: agent=%s length=%s request_id=%s",
                agent_name,
                len(generated_content),
                request_id,
            )

            agent_intro_generator.set_intro_generation_result(
                request_id, generated_content if generated_content else None
            )

        except Exception as exc:
            logger.exception(
                "[Agent介绍生成] 生成失败: agent=%s error=%s",
                agent_name,
                exc,
            )
            try:
                agent_intro_generator = self.ai._agent_intro_generator
                agent_intro_generator.set_intro_generation_result(request_id, None)
            except Exception:
                pass

    def _is_at_bot(self, content: list[dict[str, Any]]) -> bool:
        """检查消息内容中是否包含对机器人的 @ 提问"""
        for seg in content:
            if seg.get("type") == "at" and str(
                seg.get("data", {}).get("qq", "")
            ) == str(self.config.bot_qq):
                return True
        return False

    async def _handle_injection_response(
        self,
        tid: int,
        text: str,
        is_private: bool = False,
        sender_id: Optional[int] = None,
    ) -> None:
        """当检测到注入攻击时，生成并发送特定的防御性回复"""
        reply = await self.security.generate_injection_response(text)
        if not reply.strip():
            return
        if is_private:
            await self.sender.send_private_message(tid, reply, auto_history=False)
            await self.history_manager.add_private_message(
                tid, "<对注入消息的回复>", "Bot", "Bot"
            )
        else:
            msg = f"[@{sender_id}] {reply}" if sender_id else reply
            await self.sender.send_group_message(tid, msg, auto_history=False)
            await self.history_manager.add_group_message(
                tid, self.config.bot_qq, "<对注入消息的回复>", "Bot", ""
            )

    def _format_group_message_segment(self, item: BufferedMessage) -> str:
        """格式化群聊单条 ``<message>`` 块。"""
        time_str = datetime.fromtimestamp(item.arrival_time).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        group_name = item.group_name or "未知群聊"
        location = group_name if group_name.endswith("群") else f"{group_name}群"
        safe_name = escape_xml_attr(item.sender_name or "未知用户")
        safe_uid = escape_xml_attr(item.sender_id)
        safe_gid = escape_xml_attr(item.group_id or 0)
        safe_gname = escape_xml_attr(group_name)
        safe_loc = escape_xml_attr(location)
        safe_role = escape_xml_attr(item.sender_role or "member")
        safe_title = escape_xml_attr(item.sender_title or "")
        safe_time = escape_xml_attr(time_str)
        safe_text = escape_xml_text(item.text)
        message_id_attr = ""
        if item.trigger_message_id is not None:
            message_id_attr = (
                f' message_id="{escape_xml_attr(item.trigger_message_id)}"'
            )
        level_attr = (
            f' level="{escape_xml_attr(item.sender_level)}"'
            if item.sender_level
            else ""
        )
        attachment_xml = (
            f"\n{attachment_refs_to_xml(item.attachments)}" if item.attachments else ""
        )
        return (
            f'<message{message_id_attr} sender="{safe_name}" sender_id="{safe_uid}" '
            f'group_id="{safe_gid}" group_name="{safe_gname}" location="{safe_loc}" '
            f'role="{safe_role}" title="{safe_title}"{level_attr} time="{safe_time}">\n'
            f" <content>{safe_text}</content>{attachment_xml}\n"
            f" </message>"
        )

    def _format_private_message_segment(self, item: BufferedMessage) -> str:
        """格式化私聊单条 ``<message>`` 块。"""
        time_str = datetime.fromtimestamp(item.arrival_time).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        safe_name = escape_xml_attr(item.sender_name or "未知用户")
        safe_uid = escape_xml_attr(item.sender_id)
        safe_time = escape_xml_attr(time_str)
        safe_text = escape_xml_text(item.text)
        message_id_attr = ""
        if item.trigger_message_id is not None:
            message_id_attr = (
                f' message_id="{escape_xml_attr(item.trigger_message_id)}"'
            )
        attachment_xml = (
            f"\n{attachment_refs_to_xml(item.attachments)}" if item.attachments else ""
        )
        return (
            f'<message{message_id_attr} sender="{safe_name}" sender_id="{safe_uid}" '
            f'location="私聊" time="{safe_time}">\n'
            f" <content>{safe_text}</content>{attachment_xml}\n"
            f" </message>"
        )

    @staticmethod
    def _build_continuous_messages_note(items: list[BufferedMessage]) -> str:
        """生成"连续消息说明"段。仅在 ``len(items) >= 2`` 时使用。"""
        count = len(items)
        first_t = items[0].arrival_time
        last_t = items[-1].arrival_time
        span = max(0.0, last_t - first_t)
        return (
            f"\n\n 【连续消息说明】以上 {count} 条 <message> 是同一用户在约 "
            f"{span:.1f} 秒内连续发送的消息（按时间先后排列），代表本轮要回应的全部输入：\n"
            f" - 这些 <message> 共同构成【当前输入批次】，不要把同批前几条误判为历史旧任务；"
            f"批次之外的历史消息仍只作为背景，不能回溯拾荒\n"
            f" - 先识别每条的意图，分清是【独立请求】还是【对前一条的修正/否定/补充/打断】\n"
            f'   · 若是【多个独立的不同意图/问题】（如"先帮我查 A，再翻译 B")'
            f" → 每个都要回应，不要遗漏；与平时一样，可以多次 send_message 自然分发\n"
            f'   · 若后发是【对前发的修正/否定/补充/打断】（如"画猫" → "改成狗")'
            f" → 以最后一次明确意图为准，旧的不再执行，可简短说明已采纳更新\n"
            f'   · 拿不准时偏向"独立请求"，宁多勿漏\n'
            f" - 整批在本轮一次性处理完即可，不要为同一意图重复输出（不要"
            f'"中间一波、结尾再来一波"重复相同回复）\n'
            f" - history 中若出现与当前轮 <message> 相同的条目，视为同一来源，不要重复处理"
        )

    def _build_grouped_prompt(self, items: list[BufferedMessage]) -> str:
        """根据 BufferedMessage 列表构造合并后的完整 prompt。"""
        if not items:
            return ""
        is_private = items[0].is_private
        # prefix：拍一拍优先；否则任一 @bot
        any_poke = any(it.is_poke for it in items)
        any_at_bot = any(it.is_at_bot for it in items)
        if any_poke:
            prefix = "(用户拍了拍你) "
        elif any_at_bot:
            prefix = "(用户 @ 了你) "
        else:
            prefix = ""

        if is_private:
            segments = [self._format_private_message_segment(it) for it in items]
        else:
            segments = [self._format_group_message_segment(it) for it in items]
        body = prefix + "\n".join(segments)
        if len(items) >= 2:
            body += self._build_continuous_messages_note(items)
        body += _GROUP_STRATEGY_FOOTER if not is_private else _PRIVATE_STRATEGY_FOOTER
        return body

    @staticmethod
    def _collect_message_ids(items: list[BufferedMessage]) -> list[str]:
        """Collect all known message IDs from a grouped request."""
        message_ids: list[str] = []
        seen: set[str] = set()
        for item in items:
            if item.trigger_message_id is None:
                continue
            message_id = str(item.trigger_message_id).strip()
            if not message_id or message_id in seen:
                continue
            seen.add(message_id)
            message_ids.append(message_id)
        return message_ids

    async def _dispatch_grouped_request(self, items: list[BufferedMessage]) -> None:
        """根据一组 BufferedMessage 决定优先级、构造 prompt 并入队。

        既是单条直送路径的统一出口，也是 :class:`MessageBatcher` 的 flush_callback。
        """
        if not items:
            return
        first = items[0]
        last = items[-1]
        full_question = self._build_grouped_prompt(items)
        message_ids = self._collect_message_ids(items)
        any_poke = any(it.is_poke for it in items)
        any_at_bot = any(it.is_at_bot for it in items)

        if first.is_private:
            user_id = first.sender_id
            request_data: dict[str, Any] = {
                "type": "private_reply",
                "user_id": user_id,
                "sender_name": first.sender_name,
                "text": last.text,
                "full_question": full_question,
                "trigger_message_id": last.trigger_message_id,
                "message_ids": message_ids,
                "batched_count": len(items),
            }
            if first.batch_token is not None:
                request_data["_message_batcher_token"] = first.batch_token
            effective_config = self.model_pool.select_chat_config(
                self.config.chat_model, user_id=user_id
            )
            request_data["selected_model_name"] = effective_config.model_name
            logger.debug(
                "[私聊回复] full_question_len=%s user=%s batched=%s",
                len(full_question),
                user_id,
                len(items),
            )
            if user_id == self.config.superadmin_qq:
                await self.queue_manager.add_superadmin_request(
                    request_data, model_name=effective_config.model_name
                )
            else:
                await self.queue_manager.add_private_request(
                    request_data, model_name=effective_config.model_name
                )
            return

        # 群聊
        group_id = first.group_id or 0
        sender_id = first.sender_id
        request_data = {
            "type": "auto_reply",
            "group_id": group_id,
            "sender_id": sender_id,
            "sender_name": first.sender_name,
            "group_name": first.group_name,
            "text": last.text,
            "full_question": full_question,
            "is_at_bot": any_at_bot,
            "trigger_message_id": last.trigger_message_id,
            "message_ids": message_ids,
            "batched_count": len(items),
        }
        if first.batch_token is not None:
            request_data["_message_batcher_token"] = first.batch_token
        logger.debug(
            "[自动回复] full_question_len=%s group=%s sender=%s batched=%s",
            len(full_question),
            group_id,
            sender_id,
            len(items),
        )
        if sender_id == self.config.superadmin_qq:
            logger.info("[AI] 投递至群聊超级管理员队列 (batched=%s)", len(items))
            await self.queue_manager.add_group_superadmin_request(
                request_data, model_name=self.config.chat_model.model_name
            )
        elif any_at_bot:
            trigger = "拍一拍" if any_poke else "@机器人"
            logger.info("[AI] 触发原因: %s (batched=%s)", trigger, len(items))
            await self.queue_manager.add_group_mention_request(
                request_data, model_name=self.config.chat_model.model_name
            )
        else:
            logger.info("[AI] 投递至普通请求队列 (batched=%s)", len(items))
            await self.queue_manager.add_group_normal_request(
                request_data, model_name=self.config.chat_model.model_name
            )

    def _build_prompt(
        self,
        prefix: str,
        name: str,
        uid: int,
        gid: int,
        gname: str,
        loc: str,
        role: str,
        title: str,
        time_str: str,
        text: str,
        attachments: list[dict[str, str]] | None = None,
        message_id: int | None = None,
        level: str = "",
    ) -> str:
        """构建最终发送给 AI 的结构化 XML 消息 Prompt

        包含回复策略提示、用户信息和原始文本内容。
        """
        safe_name = escape_xml_attr(name)
        safe_uid = escape_xml_attr(uid)
        safe_gid = escape_xml_attr(gid)
        safe_gname = escape_xml_attr(gname)
        safe_loc = escape_xml_attr(loc)
        safe_role = escape_xml_attr(role)
        safe_title = escape_xml_attr(title)
        safe_time = escape_xml_attr(time_str)
        safe_text = escape_xml_text(text)
        message_id_attr = ""
        if message_id is not None:
            message_id_attr = f' message_id="{escape_xml_attr(message_id)}"'
        level_attr = f' level="{escape_xml_attr(level)}"' if level else ""
        attachment_xml = (
            f"\n{attachment_refs_to_xml(attachments)}" if attachments else ""
        )
        return f"""{prefix}<message{message_id_attr} sender="{safe_name}" sender_id="{safe_uid}" group_id="{safe_gid}" group_name="{safe_gname}" location="{safe_loc}" role="{safe_role}" title="{safe_title}"{level_attr} time="{safe_time}">
 <content>{safe_text}</content>{attachment_xml}
 </message>
{_GROUP_STRATEGY_FOOTER}"""

    async def _send_image(self, tid: int, mtype: str, path: str) -> None:
        """发送图片或语音消息到群聊或私聊"""
        import os

        if not os.path.exists(path):
            return
        file_uri = Path(path).resolve().as_uri()
        ext = os.path.splitext(path)[1].lower()
        if ext in [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"]:
            msg = f"[CQ:image,file={file_uri}]"
        elif ext in [".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac"]:
            msg = f"[CQ:record,file={file_uri}]"
        else:
            return

        try:
            if mtype == "group":
                await self.sender.send_group_message(tid, msg, auto_history=False)
            elif mtype == "private":
                await self.sender.send_private_message(tid, msg, auto_history=False)
        except Exception:
            logger.exception("发送媒体文件失败")
