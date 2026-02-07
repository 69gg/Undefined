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
from Undefined.utils.resources import read_text_resource
from Undefined.utils.xml import escape_xml_attr, escape_xml_text

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
        """
        is_at_bot = is_poke or self._is_at_bot(message_content)
        logger.debug(
            "[自动回复] group=%s sender=%s at_bot=%s text_len=%s",
            group_id,
            sender_id,
            is_at_bot,
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
        logger.debug(
            "[自动回复] full_question_len=%s group=%s sender=%s",
            len(full_question),
            group_id,
            sender_id,
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

        prompt_prefix = "(用户拍了拍你) " if is_poke else ""
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        full_question = f"""{prompt_prefix}<message sender="{escape_xml_attr(sender_name)}" sender_id="{escape_xml_attr(user_id)}" location="私聊" time="{escape_xml_attr(current_time)}">
 <content>{escape_xml_text(text)}</content>
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
        logger.debug(
            "[私聊回复] full_question_len=%s user=%s",
            len(full_question),
            user_id,
        )

        if user_id == self.config.superadmin_qq:
            await self.queue_manager.add_superadmin_request(
                request_data, model_name=self.config.chat_model.model_name
            )
        else:
            await self.queue_manager.add_private_request(
                request_data, model_name=self.config.chat_model.model_name
            )

    async def execute_reply(self, request: dict[str, Any]) -> None:
        """执行排队中的回复请求（由 QueueManager 分发调用）

        参数:
            request: 包含请求类型和必要元数据的请求字典
        """
        """执行回复请求（由 QueueManager 调用）"""
        req_type = request.get("type", "unknown")
        logger.debug("[执行请求] type=%s keys=%s", req_type, list(request.keys()))
        if req_type == "auto_reply":
            await self._execute_auto_reply(request)
        elif req_type == "private_reply":
            await self._execute_private_reply(request)
        elif req_type == "stats_analysis":
            await self._execute_stats_analysis(request)
        elif req_type == "agent_intro_generation":
            await self._execute_agent_intro_generation(request)

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
            logger.debug(
                "[上下文资源] group=%s keys=%s",
                group_id,
                ", ".join(sorted(resources.keys())),
            )

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
            logger.debug(
                "[上下文资源] private user=%s keys=%s",
                user_id,
                ", ".join(sorted(resources.keys())),
            )

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
                    },
                )
                if result:
                    await self.sender.send_private_message(user_id, result)
            except Exception:
                logger.exception("私聊回复执行出错")

    async def _execute_stats_analysis(self, request: dict[str, Any]) -> None:
        """执行 stats 命令的 AI 分析"""
        group_id = request["group_id"]
        request_id = request.get("request_id")
        data_summary = request.get("data_summary", "")

        if not request_id:
            logger.warning("[统计分析] 缺少 request_id，群=%s", group_id)
            return
        try:
            # 加载提示词模板
            try:
                prompt_template = read_text_resource("res/prompts/stats_analysis.txt")
            except Exception:
                logger.warning("[统计分析] 提示词文件不存在，使用默认分析")
                analysis = "AI 分析功能暂时不可用（提示词文件缺失）"
                if self.command_dispatcher:
                    self.command_dispatcher.set_stats_analysis_result(
                        group_id, request_id, analysis
                    )
                return
            full_prompt = prompt_template.format(data_summary=data_summary)

            # 调用 AI 进行分析
            messages = [
                {"role": "system", "content": "你是一位专业的数据分析师。"},
                {"role": "user", "content": full_prompt},
            ]

            result = await self.ai.request_model(
                model_config=self.config.chat_model,
                messages=messages,
                max_tokens=2048,
                call_type="stats_analysis",
            )

            # 提取分析结果
            choices = result.get("choices", [{}])
            if choices:
                content = choices[0].get("message", {}).get("content", "")
                analysis = content.strip()
            else:
                analysis = "AI 分析未能生成结果"

            logger.info(
                "[统计分析] 分析完成: group=%s length=%s request_id=%s",
                group_id,
                len(analysis),
                request_id,
            )

            # 设置分析结果（通知等待的 _handle_stats 方法）
            if self.command_dispatcher:
                self.command_dispatcher.set_stats_analysis_result(
                    group_id, request_id, analysis
                )

        except Exception as exc:
            logger.exception("[统计分析] AI 分析失败: %s", exc)
            # 出错时也通知等待，但返回空字符串
            if self.command_dispatcher:
                self.command_dispatcher.set_stats_analysis_result(
                    group_id, request_id, ""
                )

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
            # 获取提示词
            from Undefined.skills.agents.intro_generator import AgentIntroGenerator

            agent_intro_generator = self.ai._agent_intro_generator
            if not isinstance(agent_intro_generator, AgentIntroGenerator):
                logger.error("[Agent介绍生成] 无法获取 AgentIntroGenerator 实例")
                agent_intro_generator.set_intro_generation_result(request_id, None)
                return

            (
                system_prompt,
                user_prompt,
            ) = await agent_intro_generator.get_intro_prompt_and_context(agent_name)

            # 调用 AI 生成
            messages = [
                {"role": "system", "content": system_prompt or "你是一位智能助手。"},
                {"role": "user", "content": user_prompt},
            ]

            result = await self.ai.request_model(
                model_config=self.ai.agent_config,
                messages=messages,
                max_tokens=agent_intro_generator.config.max_tokens,
                call_type=f"agent:{agent_name}",
            )

            # 提取结果
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

            # 通知结果
            agent_intro_generator.set_intro_generation_result(
                request_id, generated_content if generated_content else None
            )

        except Exception as exc:
            logger.exception(
                "[Agent介绍生成] 生成失败: agent=%s error=%s",
                agent_name,
                exc,
            )
            # 出错时也通知，返回 None
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
        return f"""{prefix}<message sender="{safe_name}" sender_id="{safe_uid}" group_id="{safe_gid}" group_name="{safe_gname}" location="{safe_loc}" role="{safe_role}" title="{safe_title}" time="{safe_time}">
 <content>{safe_text}</content>
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
        """发送图片或语音消息到群聊或私聊"""
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
                await self.sender.send_group_message(tid, msg, auto_history=False)
            elif mtype == "private":
                await self.sender.send_private_message(tid, msg, auto_history=False)
        except Exception:
            logger.exception("发送媒体文件失败")
