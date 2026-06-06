"""私聊回复与私聊 prompt 格式化。"""

from __future__ import annotations


import asyncio
import logging
import time
from datetime import datetime
from typing import TYPE_CHECKING, Any

from Undefined.attachments import (
    build_attachment_scope,
    dispatch_pending_file_sends,
    render_message_with_pic_placeholders,
    attachment_refs_to_xml,
)
from Undefined.context import RequestContext
from Undefined.context_resource_registry import collect_context_resources
from Undefined.render import render_html_to_image, render_markdown_to_html
from Undefined.services.message_batcher import BufferedMessage, make_scope
from Undefined.utils.recent_messages import get_recent_messages_prefer_local
from Undefined.utils.xml import escape_xml_attr, escape_xml_text

if TYPE_CHECKING:
    from Undefined.config import Config
    from Undefined.services.message_batcher import BufferedMessage
    from Undefined.services.security import SecurityService
    from Undefined.utils.history import MessageHistoryManager
    from Undefined.utils.scheduler import TaskScheduler
    from Undefined.utils.sender import MessageSender

logger = logging.getLogger(__name__)


_PRIVATE_STRATEGY_FOOTER = """

【私聊消息】
这是私聊消息，用户专门来找你说话。你可以自由选择是否回复：
- 如果想回复，先调用 send_message 工具发送回复内容，然后调用 end 结束对话
- 只有明确纯表情包回复时，才先用 memes.search_memes 查表情包，再用 memes.send_meme_by_uid 单独发图；其他场景先把文字回复做好，表情包最后再搜或不搜
- 如果不想回复，直接调用 end 结束对话即可"""


class PrivateReplyMixin:
    """私聊自动回复与私聊 prompt 格式化。"""

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
        async def _handle_injection_response(
            self,
            tid: int,
            text: str,
            is_private: bool = False,
            sender_id: int | None = None,
        ) -> None: ...
        async def _send_image(self, tid: int, mtype: str, path: str) -> None: ...

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
            # 拍一拍旁路 batcher，立即单条入队
            await self._dispatch_grouped_request([item])
            return

        batcher = getattr(self, "_batcher", None)
        if batcher is not None and batcher.is_enabled_for(is_group=False):
            await batcher.submit(item)
            return

        await self._dispatch_grouped_request([item])

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
