"""群聊自动回复与 prompt 构建。"""

from __future__ import annotations


import asyncio
import logging
import time
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal, Optional

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
    from Undefined.automations.service import AutomationService
    from Undefined.utils.sender import MessageSender

logger = logging.getLogger(__name__)


_GROUP_STRATEGY_FOOTER = """

 【P0 群聊收件人闸门 — 必须先通过，之后才可解释请求或调用工具】
 1. 先逐条判定每个 <message> 是说给谁听的，再判断内容；话题、语气和你的能力都不能反过来证明收件人是 Undefined。
 2. 每条群消息都有系统生成的 bot_trigger：
    - bot_trigger="mention"：系统确认该条 @ 了 Undefined（含已识别的假 @）→ 【必须回复】
    - bot_trigger="poke"：系统确认该条拍了拍 Undefined → 【必须回复】
    - bot_trigger="none"：系统未检测到显式 @/拍一拍；这不等于绝对没在叫你，但必须另有明确直接证据，绝不能靠人称猜测
 3. bot_trigger="none" 时，只有以下直接证据可以证明话头转向你：
    - 以 Undefined 或你的常见昵称作呼语并直接向你提问/下指令；仅在第三人称中提到名字不算
    - 当前消息明确回复 Undefined 的上一条发言，或紧接你的上一条发言并直接承接其内容；你只是更早在群里出现过不算
    - 消息明确面向全群征询，且没有 @/回复/上下文把问题定向给某位群友
 4. 以下全部【不是】指向 Undefined 的证据：
    - 「你/你们/我/咱们」等人称，问号、祈使句、命令语气、请求帮忙、询问能力
    - 出现「AI」「bot」「机器人」或 Undefined 名字；讨论相关技术、项目、部署、报错；你刚好会做这件事
    - 发言者是 Null、管理员或高优先级用户；消息被系统送进哪条队列
 5. 出现以下任一情况时，负向证据优先：@/回复其他人、两名群友连续对话、明显承接其他群友、评价第三方、名字只被第三人称提及。此时即使原句写着「你就……」「你能不能……」也不是在叫你。
 6. 闸门结论：
    - 有明确直接证据且无冲突 → 才能继续评估是否回复
    - 明确在对别人说，或证据互相冲突 → 只调用 end
    - 仍拿不准 → 假设不在和你说话，只调用 end
    - 闸门未通过时，禁止 send_message、tool_search、cognitive.*、表情包、业务工具或 Agent；记忆和搜索不能替当前消息创造收件人
 7. 合并批次逐条看 bot_trigger 和各自语境；批次里某一条 @/拍一拍，不会把其他独立消息自动改成对 Undefined 说。

 【通过收件人闸门后的回复策略】
 1. 明确 @、拍一拍、直接呼叫或自然延续与你的对话 → 【回复】。
 2. 群聊里的主动参与只保留给公开、开放的技术或项目讨论：
    - 只在明确面向全群的公开讨论中，且不是别人之间定向交流时，才可以【极低频参与】
    - 技术相关性本身不通过收件人闸门；默认更倾向不参与，不需要你时保持沉默
    - 轻松互动、玩梗、吐槽本身不构成参与许可；只有在你已经决定要回复时，才考虑用表情包增强表达
 3. 回答项目/代码/部署等问题时，直接围绕用户明确提到的对象，必要时先查证；不要引入无关项目名或工具名作背景。
 4. 对于已经决定要回复的场景：
    - 只有明确纯表情包回复才先检索表情包，再用 memes.send_meme_by_uid 单独发一条图片消息
    - 其他需要文字承接、解释、答疑、推进任务、确认操作或表达具体态度的场景，第一轮必须优先把必要文字回复做好并调用 send_message
    - 轻松聊天、吐槽、附和、接梗、表达情绪、被拍一拍、被@后的短回应等场景，文字发送成功后优先考虑在后续响应轮次补一张独立表情包，不要阻塞首条文字回复
    - 不要发送任何敷衍消息（如'懒得掺和'、'哦'等）；不想回复就直接调用 end
    - 不回复时禁止把闸门结论、静默原因、规则自检或拼写声明发到聊天里
    - 严肃答疑、代码排查、长任务推进、隐私/安全拒绝、信息不足追问这类场景默认不补表情包，避免打断信息传递
    - 绝不要刷屏、绝不要每条都回

 每次收到工具结果后、每次发送消息前，都重新执行收件人闸门。简单说：Undefined 不是群聊里「你」的默认指代；先证明话是对你说的，再做事。"""


def _group_bot_trigger(
    *, is_at_bot: bool, is_poke: bool
) -> Literal["mention", "poke", "none"]:
    """Return the explicit bot-addressing signal attached to a group message."""
    if is_poke:
        return "poke"
    if is_at_bot:
        return "mention"
    return "none"


class GroupReplyMixin:
    """群聊自动回复、注入防御与群聊 prompt 格式化。"""

    if TYPE_CHECKING:
        ai: Any
        config: Config
        history_manager: MessageHistoryManager
        onebot: Any
        scheduler: AutomationService
        security: SecurityService
        sender: MessageSender

        async def _dispatch_grouped_request(
            self, items: list[BufferedMessage]
        ) -> None: ...
        async def _send_media(self, tid: int, mtype: str, path: str) -> None: ...

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
        recent_messages_snapshot_raw = request.get("recent_messages_snapshot")
        recent_messages_snapshot: list[dict[str, Any]] | None = (
            recent_messages_snapshot_raw
            if isinstance(recent_messages_snapshot_raw, list)
            else None
        )
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
                await self._send_media(tid, mtype, path)

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
                        recent_messages_snapshot=recent_messages_snapshot,
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
        bot_trigger = _group_bot_trigger(
            is_at_bot=item.is_at_bot,
            is_poke=item.is_poke,
        )
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
            f'bot_trigger="{bot_trigger}" '
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
        is_at_bot: bool = False,
        is_poke: bool = False,
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
        bot_trigger = _group_bot_trigger(
            is_at_bot=is_at_bot,
            is_poke=is_poke,
        )
        safe_text = escape_xml_text_preserving_attachment_tags(text, attachments)
        message_id_attr = ""
        if message_id is not None:
            message_id_attr = f' message_id="{escape_xml_attr(message_id)}"'
        level_attr = f' level="{escape_xml_attr(level)}"' if level else ""
        attachment_xml = (
            f"\n{attachment_refs_to_xml(attachments)}" if attachments else ""
        )
        return f"""{prefix}<message{message_id_attr} sender="{safe_name}" sender_id="{safe_uid}" group_id="{safe_gid}" group_name="{safe_gname}" location="{safe_loc}" bot_trigger="{bot_trigger}" role="{safe_role}" title="{safe_title}"{level_attr} time="{safe_time}">
 <content>{safe_text}</content>{attachment_xml}
 </message>
{_GROUP_STRATEGY_FOOTER}"""
