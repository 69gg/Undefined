"""群聊自动回复与 prompt 构建。"""

from __future__ import annotations


import asyncio
import logging
import time
from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional

from Undefined.attachments import attachment_refs_to_xml
from Undefined.context import RequestContext
from Undefined.context_resource_registry import collect_context_resources
from Undefined.render import render_html_to_image, render_markdown_to_html
from Undefined.services.message_batcher import BufferedMessage, make_scope
from Undefined.utils.recent_messages import get_recent_messages_prefer_local
from Undefined.utils.xml import (
    escape_xml_attr,
    escape_xml_text_preserving_attachment_tags,
)
from Undefined.utils.message_targets import DeliveryAddress

if TYPE_CHECKING:
    from Undefined.config import Config
    from Undefined.services.message_batcher import BufferedMessage
    from Undefined.services.security import SecurityService
    from Undefined.utils.history import MessageHistoryManager
    from Undefined.utils.scheduler import TaskScheduler
    from Undefined.utils.sender import MessageSender

logger = logging.getLogger(__name__)


_GROUP_STRATEGY_FOOTER = """

 【回复策略 - 克制参与，轻松场景可后补表情包】
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
    - 轻松互动、玩梗、吐槽本身不构成参与许可；只有在你已经决定要回复时，才考虑用表情包增强表达
  7. 对于已经决定要回复的场景（包括被@、被拍一拍、轻量答疑，以及少量符合条件的主动参与）：
    - 只有明确纯表情包回复才先检索表情包，再用 memes.send_meme_by_uid 单独发一条图片消息
    - 其他需要文字承接、解释、答疑、推进任务、确认操作或表达具体态度的场景，第一轮必须优先把必要文字回复做好并调用 send_message
    - 轻松聊天、吐槽、附和、接梗、表达情绪、被拍一拍、被@后的短回应等场景，文字发送成功后优先考虑在后续响应轮次补一张独立表情包，不要阻塞首条文字回复
    - 不要发送任何敷衍消息（如'懒得掺和'、'哦'等）；不想回复就直接调用 end
    - 严肃答疑、代码排查、长任务推进、隐私/安全拒绝、信息不足追问这类场景默认不补表情包，避免打断信息传递
    - 绝不要刷屏、绝不要每条都回
  8. 对于本来就会回复的场景（私聊、被拍一拍、被@、轻量答疑）：
    - 如果表情包能自然增强语气、缓和语气或让表达更像真人，优先作为后续补充
    - 但不要为了发表情包而牺牲信息传递；信息密度优先时仍以文字为主

 简单说：像个极度安静的群友。主动插话只留给公开、开放的技术或项目讨论；明显对别人说或拿不准时就闭嘴。已经决定要回复时，除非明确是纯表情包回复，否则先把文字回复做好；轻松、接梗、情绪回应可以优先后补表情包。"""


class GroupReplyMixin:
    """群聊自动回复、注入防御与群聊 prompt 格式化。"""

    if TYPE_CHECKING:
        ai: Any
        config: Config
        history_manager: MessageHistoryManager
        onebot: Any
        scheduler: TaskScheduler
        security: SecurityService
        sender: MessageSender

        async def _dispatch_grouped_request(
            self, items: list[BufferedMessage]
        ) -> None: ...
        async def _send_image(self, tid: int, mtype: str, path: str) -> None: ...

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
        """群聊自动回复入口：根据消息内容、命中情况和安全检测决定是否回复"""
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
        address: DeliveryAddress | None = None,
    ) -> None:
        """当检测到注入攻击时，生成并发送特定的防御性回复"""
        reply = await self.security.generate_injection_response(text)
        if not reply.strip():
            return
        if is_private:
            resolved_address = address or DeliveryAddress("qq", tid)
            await self.sender.send_address_message(
                resolved_address, reply, auto_history=False
            )
            await self.history_manager.add_private_message(
                tid,
                "<对注入消息的回复>",
                "Bot",
                "Bot",
                transport=(
                    {
                        "channel": resolved_address.channel,
                        "address": resolved_address.canonical,
                    }
                    if resolved_address.channel == "wechat"
                    else None
                ),
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
        safe_text = escape_xml_text_preserving_attachment_tags(
            item.text,
            item.attachments,
        )
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
        safe_text = escape_xml_text_preserving_attachment_tags(text, attachments)
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
