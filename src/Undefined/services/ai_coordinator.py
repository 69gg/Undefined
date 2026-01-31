import logging
from datetime import datetime
from typing import Any, Optional
from Undefined.config import Config
from Undefined.context import RequestContext
from Undefined.context_resource_registry import collect_context_resources
from Undefined.render import render_html_to_image, render_markdown_to_html
from Undefined.services.queue_manager import QueueManager
from Undefined.utils.history import MessageHistoryManager
from Undefined.utils.sender import MessageSender
from Undefined.utils.scheduler import TaskScheduler
from Undefined.services.security import SecurityService

logger = logging.getLogger(__name__)


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
    ) -> None:
        self.config = config
        self.ai = ai
        self.queue_manager = queue_manager
        self.history_manager = history_manager
        self.sender = sender
        self.onebot = onebot
        self.scheduler = scheduler
        self.security = security

    async def handle_auto_reply(
        self,
        group_id: int,
        sender_id: int,
        text: str,
        message_content: list[dict[str, Any]],
        is_poke: bool = False,
        sender_name: str = "未知用户",
        group_name: str = "未知群聊",
        sender_role: str = "member",
        sender_title: str = "",
    ) -> None:
        """自动回复处理：根据上下文决定是否回复"""
        is_at_bot = is_poke or self._is_at_bot(message_content)

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

        prompt_prefix = (
            "(用户拍了拍你) " if is_poke else ("(用户 @ 了你) " if is_at_bot else "")
        )
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        location = group_name if group_name.endswith("群") else f"{group_name}群"

        full_question = self._build_prompt(
            prompt_prefix,
            sender_name,
            sender_id,
            group_id,
            group_name,
            location,
            sender_role,
            sender_title,
            current_time,
            text,
        )

        request_data = {
            "type": "auto_reply",
            "group_id": group_id,
            "sender_id": sender_id,
            "text": text,
            "full_question": full_question,
            "is_at_bot": is_at_bot,
        }

        if is_at_bot:
            logger.info(f"[AI] 触发原因: {'拍一拍' if is_poke else '@机器人'}")
            await self.queue_manager.add_group_mention_request(
                request_data, model_name=self.config.chat_model.model_name
            )
        else:
            logger.info("[AI] 投递至普通请求队列")
            await self.queue_manager.add_group_normal_request(
                request_data, model_name=self.config.chat_model.model_name
            )

    async def handle_private_reply(
        self,
        user_id: int,
        text: str,
        message_content: list[dict[str, Any]],
        is_poke: bool = False,
        sender_name: str = "未知用户",
    ) -> None:
        """私聊回复处理"""
        if user_id != self.config.superadmin_qq:
            if await self.security.detect_injection(text, message_content):
                logger.warning(f"[Security] 私聊注入攻击: user_id={user_id}")
                await self.history_manager.modify_last_private_message(
                    user_id, "<这句话检测到用户进行注入，已删除>"
                )
                await self._handle_injection_response(user_id, text, is_private=True)
                return

        prompt_prefix = "(用户拍了拍你) " if is_poke else ""
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        full_question = f"""{prompt_prefix}<message sender="{sender_name}" sender_id="{user_id}" location="私聊" time="{current_time}">
<content>{text}</content>
</message>

【私聊消息】
这是私聊消息，用户专门来找你说话。你可以自由选择是否回复：
- 如果想回复，先调用 send_message 工具发送回复内容，然后调用 end 结束对话
- 如果不想回复，直接调用 end 结束对话即可"""

        request_data = {
            "type": "private_reply",
            "user_id": user_id,
            "text": text,
            "full_question": full_question,
        }

        if user_id == self.config.superadmin_qq:
            await self.queue_manager.add_superadmin_request(
                request_data, model_name=self.config.chat_model.model_name
            )
        else:
            await self.queue_manager.add_private_request(
                request_data, model_name=self.config.chat_model.model_name
            )

    async def execute_reply(self, request: dict[str, Any]) -> None:
        """执行回复请求（由 QueueManager 调用）"""
        req_type = request.get("type", "unknown")
        if req_type == "auto_reply":
            await self._execute_auto_reply(request)
        elif req_type == "private_reply":
            await self._execute_private_reply(request)

    async def _execute_auto_reply(self, request: dict[str, Any]) -> None:
        group_id = request["group_id"]
        sender_id = request["sender_id"]
        full_question = request["full_question"]

        # 创建请求上下文
        async with RequestContext(
            request_type="group",
            group_id=group_id,
            sender_id=sender_id,
            user_id=sender_id,
        ) as ctx:

            async def send_msg_cb(message: str, at_user: Optional[int] = None) -> None:
                if at_user:
                    message = f"[CQ:at,qq={at_user}] {message}"
                await self.sender.send_group_message(group_id, message)

            async def get_recent_cb(
                chat_id: str, msg_type: str, start: int, end: int
            ) -> list[dict[str, Any]]:
                return self.history_manager.get_recent(chat_id, msg_type, start, end)

            async def send_private_cb(uid: int, msg: str) -> None:
                await self.sender.send_private_message(uid, msg)

            async def send_img_cb(tid: int, mtype: str, path: str) -> None:
                await self._send_image(tid, mtype, path)

            async def send_like_cb(uid: int, times: int = 1) -> None:
                await self.onebot.send_like(uid, times)

            # 存储资源到上下文
            ai_client = self.ai
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

            try:
                # 保留旧方式（向后兼容）
                self.ai.current_group_id = group_id
                self.ai.current_user_id = sender_id
                self.ai._send_private_message_callback = send_private_cb
                self.ai._send_image_callback = send_img_cb

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
                    },
                )
            except Exception:
                logger.exception("自动回复执行出错")

    async def _execute_private_reply(self, request: dict[str, Any]) -> None:
        user_id = request["user_id"]
        full_question = request["full_question"]

        # 创建请求上下文
        async with RequestContext(
            request_type="private",
            user_id=user_id,
            sender_id=user_id,
        ) as ctx:

            async def send_msg_cb(message: str, at_user: Optional[int] = None) -> None:
                await self.sender.send_private_message(user_id, message)

            async def get_recent_cb(
                chat_id: str, msg_type: str, start: int, end: int
            ) -> list[dict[str, Any]]:
                return self.history_manager.get_recent(chat_id, msg_type, start, end)

            async def send_img_cb(tid: int, mtype: str, path: str) -> None:
                await self._send_image(tid, mtype, path)

            async def send_like_cb(uid: int, times: int = 1) -> None:
                await self.onebot.send_like(uid, times)

            async def send_private_cb(uid: int, msg: str) -> None:
                await self.sender.send_private_message(uid, msg)

            # 存储资源到上下文
            ai_client = self.ai
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

            try:
                # 保留旧方式（向后兼容）
                self.ai.current_group_id = None
                self.ai.current_user_id = user_id
                self.ai._send_image_callback = send_img_cb
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
                    },
                )
                if result:
                    await self.sender.send_private_message(user_id, result)
            except Exception:
                logger.exception("私聊回复执行出错")

    def _is_at_bot(self, content: list[dict[str, Any]]) -> bool:
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
        reply = await self.security.generate_injection_response(text)
        if is_private:
            await self.sender.send_private_message(tid, reply, auto_history=False)
            await self.history_manager.add_private_message(
                tid, "<对注入消息的回复>", "Bot", "Bot"
            )
        else:
            msg = f"[CQ:at,qq={sender_id}] {reply}" if sender_id else reply
            await self.sender.send_group_message(tid, msg, auto_history=False)
            await self.history_manager.add_group_message(
                tid, self.config.bot_qq, "<对注入消息的回复>", "Bot", ""
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
    ) -> str:
        return f"""{prefix}<message sender="{name}" sender_id="{uid}" group_id="{gid}" group_name="{gname}" location="{loc}" role="{role}" title="{title}" time="{time_str}">
<content>{text}</content>
</message>

【回复策略 - 极低频参与】
1. 如果用户 @ 了你或拍了拍你 → 【必须回复】
2. 如果消息中明确提到了你（根据上下文判断用户是在叫你，如提到'bugfix'、'机器人'、'bot'等） → 【必须回复】
3. 如果问题明确涉及 NagaAgent 技术或代码 → 【尽量回复，先读代码再回答】
4. 其他技术问题（与 NagaAgent 无关）→ 【酌情回复，可结合自己知识或搜索】
5. 普通闲聊、水群、吐槽：
   - 【几乎不回复】（99.9% 以上情况直接调用 end 不回复）
   - 不要发送任何敷衍消息（如'懒得掺和'、'哦'等），不想回复就直接调用 end
   - 只有内容极其有趣、特别相关、能提供独特价值时才考虑回复
   - 不要为了"参与"而参与，保持安静
   - 绝不要刷屏、绝不要每条都回

简单说：像个极度安静的群友。被@或明确提到才回应，NagaAgent技术问题尽量回复，其他几乎不理。"""

    async def _send_image(self, tid: int, mtype: str, path: str) -> None:
        # 这里为了简化，直接调用 onebot 发送，逻辑同原 MessageHandler._send_image
        import os

        if not os.path.exists(path):
            return
        abs_path = os.path.abspath(path)
        ext = os.path.splitext(path)[1].lower()
        if ext in [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"]:
            msg = f"[CQ:image,file={abs_path}]"
        elif ext in [".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac"]:
            msg = f"[CQ:record,file={abs_path}]"
        else:
            return

        try:
            if mtype == "group":
                await self.onebot.send_group_message(tid, msg)
            elif mtype == "private":
                await self.onebot.send_private_message(tid, msg)
        except Exception:
            logger.exception("发送媒体文件失败")
