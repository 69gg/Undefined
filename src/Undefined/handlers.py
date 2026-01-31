"""消息处理和命令分发"""

import logging
import os
import random
from typing import Any

from Undefined.ai import AIClient
from Undefined.config import Config
from Undefined.faq import FAQStorage
from Undefined.services.queue_manager import QueueManager
from Undefined.onebot import (
    OneBotClient,
    get_message_content,
    get_message_sender_id,
)
from Undefined.utils.common import (
    extract_text,
    parse_message_content_for_history,
    matches_xinliweiyuan,
)
from Undefined.utils.history import MessageHistoryManager
from Undefined.utils.scheduler import TaskScheduler
from Undefined.utils.sender import MessageSender
from Undefined.services.security import SecurityService
from Undefined.services.command import CommandDispatcher
from Undefined.services.ai_coordinator import AICoordinator

from Undefined.scheduled_task_storage import ScheduledTaskStorage

logger = logging.getLogger(__name__)

with open("res/prepared_messages/help_message.txt", "r", encoding="utf-8") as f:
    HELP_MESSAGE = f.read()


class MessageHandler:
    """消息处理器"""

    def __init__(
        self,
        config: Config,
        onebot: OneBotClient,
        ai: AIClient,
        faq_storage: FAQStorage,
        task_storage: ScheduledTaskStorage,
    ) -> None:
        self.config = config
        self.onebot = onebot
        self.ai = ai
        self.faq_storage = faq_storage
        # 初始化 Utils
        self.history_manager = MessageHistoryManager()
        self.sender = MessageSender(onebot, self.history_manager, config.bot_qq)

        # 初始化服务
        self.security = SecurityService(config, ai._http_client)
        self.command_dispatcher = CommandDispatcher(
            config, self.sender, ai, faq_storage, onebot, self.security
        )
        self.ai_coordinator = AICoordinator(
            config,
            ai,
            QueueManager(),
            self.history_manager,
            self.sender,
            onebot,
            TaskScheduler(ai, self.sender, onebot, self.history_manager, task_storage),
            self.security,
        )

        # 启动队列
        self.ai_coordinator.queue_manager.start(self.ai_coordinator.execute_reply)

    async def handle_message(self, event: dict[str, Any]) -> None:
        """处理收到的消息事件"""
        post_type = event.get("post_type", "message")

        # 处理拍一拍事件（效果同被 @）
        if post_type == "notice" and event.get("notice_type") == "poke":
            target_id = event.get("target_id", 0)
            # 只有拍机器人才响应
            if target_id != self.config.bot_qq:
                logger.debug(
                    f"[bold yellow][忽略][/bold yellow] 拍一拍目标不是机器人: target={target_id}"
                )
                return

            poke_group_id: int = event.get("group_id", 0)
            poke_sender_id: int = event.get("user_id", 0)

            logger.info(
                f"[bold cyan][通知事件][/bold cyan] 收到拍一拍: [blue]group={poke_group_id}[/blue], [blue]sender={poke_sender_id}[/blue]"
            )
            logger.debug(f"[通知详情] 拍一拍完整数据: {event}")

            if poke_group_id == 0:
                logger.info("[bold magenta]私聊拍一拍[/bold magenta]，触发私聊回复")
                await self.ai_coordinator.handle_private_reply(
                    poke_sender_id,
                    "(拍了拍你)",
                    [],
                    is_poke=True,
                    sender_name=str(poke_sender_id),
                )
            else:
                logger.info(
                    f"[bold magenta]群聊拍一拍[/bold magenta] (群: {poke_group_id})，触发群聊自动回复"
                )
                await self.ai_coordinator.handle_auto_reply(
                    poke_group_id,
                    poke_sender_id,
                    "(拍了拍你)",
                    [],
                    is_poke=True,
                    sender_name=str(poke_sender_id),
                    group_name=str(poke_group_id),
                )
            return

        # 处理私聊消息
        if event.get("message_type") == "private":
            private_sender_id: int = get_message_sender_id(event)
            private_message_content: list[dict[str, Any]] = get_message_content(event)

            # 获取发送者昵称
            private_sender: dict[str, Any] = event.get("sender", {})
            private_sender_nickname: str = private_sender.get("nickname", "")

            # 获取私聊用户昵称
            user_name = private_sender_nickname
            if not user_name:
                try:
                    user_info = await self.onebot.get_stranger_info(private_sender_id)
                    if user_info:
                        user_name = user_info.get("nickname", "")
                except Exception as e:
                    logger.warning(f"获取用户昵称失败: {e}")

            # 处理图片：在历史记录中仅保留占位符，由 AI 决定是否分析
            processed_message_content = []
            for segment in private_message_content:
                if segment.get("type") == "image":
                    file = segment.get("data", {}).get("file", "") or segment.get(
                        "data", {}
                    ).get("url", "")
                    text_repr = f"[图片: {file}]"
                    processed_message_content.append(
                        {"type": "text", "data": {"text": text_repr}}
                    )
                else:
                    processed_message_content.append(segment)

            # 从处理后的内容中提取文本
            text = extract_text(processed_message_content, self.config.bot_qq)
            logger.info(
                f"[私聊消息] 发送者={private_sender_id} ({user_name}) | 内容: {text[:100]}"
            )

            # 处理图片：在历史记录中仅保留占位符，由 AI 决定是否分析
            processed_message_content = []
            for segment in private_message_content:
                if segment.get("type") == "image":
                    file = segment.get("data", {}).get("file", "") or segment.get(
                        "data", {}
                    ).get("url", "")
                    text_repr = f"[图片: {file}]"
                    processed_message_content.append(
                        {"type": "text", "data": {"text": text_repr}}
                    )
                else:
                    processed_message_content.append(segment)

            # 从处理后的内容中提取文本
            text = extract_text(processed_message_content, self.config.bot_qq)
            logger.info(
                f"[私聊消息] 发送者={private_sender_id} ({user_name}) | 内容: {text[:100]}"
            )

            # 保存私聊消息到历史记录（保存处理后的内容）
            # 使用新的 utils
            parsed_content = await parse_message_content_for_history(
                processed_message_content, self.config.bot_qq, self.onebot.get_msg
            )
            logger.debug(
                f"[历史记录] 保存私聊记录: user={private_sender_id}, content={parsed_content[:50]}..."
            )
            await self.history_manager.add_private_message(
                user_id=private_sender_id,
                text_content=parsed_content,
                display_name=private_sender_nickname,
                user_name=user_name,
            )

            # 如果是 bot 自己的消息，只保存不触发回复，避免无限循环
            if private_sender_id == self.config.bot_qq:
                return

            # 私聊消息直接触发回复
            await self.ai_coordinator.handle_private_reply(
                private_sender_id,
                text,
                processed_message_content,
                sender_name=user_name,
            )
            return

        # 只处理群消息
        if event.get("message_type") != "group":
            return

        group_id: int = event.get("group_id", 0)
        sender_id: int = get_message_sender_id(event)
        message_content: list[dict[str, Any]] = get_message_content(event)

        # 获取发送者信息
        group_sender: dict[str, Any] = event.get("sender", {})
        sender_card: str = group_sender.get("card", "")
        sender_nickname: str = group_sender.get("nickname", "")
        sender_role: str = group_sender.get("role", "member")
        sender_title: str = group_sender.get("title", "")

        # 提取文本内容
        text = extract_text(message_content, self.config.bot_qq)
        logger.info(
            f"[bold blue][群消息][/bold blue] 群: [blue]{group_id}[/blue] | 发送者: [blue]{sender_id}[/blue] ({sender_card or sender_nickname}) | 角色: [yellow]{sender_role}[/yellow] | 内容: [italic]{text[:100]}[/italic]"
        )

        # 提取文本内容
        text = extract_text(message_content, self.config.bot_qq)
        logger.info(
            f"[群消息] 群:{group_id} | 发送者:{sender_id} ({sender_card or sender_nickname}) | 内容: {text[:100]}"
        )

        # 处理图片：在历史记录中仅保留占位符
        processed_message_content = []
        for segment in message_content:
            if segment.get("type") == "image":
                file = segment.get("data", {}).get("file", "") or segment.get(
                    "data", {}
                ).get("url", "")
                text_repr = f"[图片: {file}]"
                processed_message_content.append(
                    {"type": "text", "data": {"text": text_repr}}
                )
            else:
                processed_message_content.append(segment)

        # 保存消息到历史记录 (使用处理后的内容)
        # 获取群聊名
        group_name = ""
        try:
            group_info = await self.onebot.get_group_info(group_id)
            if group_info:
                group_name = group_info.get("group_name", "")
        except Exception as e:
            logger.warning(f"获取群聊名失败: {e}")

        # 使用新的 utils
        parsed_content = await parse_message_content_for_history(
            processed_message_content, self.config.bot_qq, self.onebot.get_msg
        )
        logger.debug(
            f"[bold grey42][历史记录][/bold grey42] 保存群聊记录: group=[blue]{group_id}[/blue], sender=[blue]{sender_id}[/blue], content=[italic]{parsed_content[:50]}[/italic]..."
        )
        await self.history_manager.add_group_message(
            group_id=group_id,
            sender_id=sender_id,
            text_content=parsed_content,
            sender_card=sender_card,
            sender_nickname=sender_nickname,
            group_name=group_name,
            role=sender_role,
            title=sender_title,
        )

        # 如果是 bot 自己的消息，只保存不触发回复，避免无限循环
        if sender_id == self.config.bot_qq:
            return

        # 关键词自动回复：心理委员 (使用原始消息内容提取文本，保证关键词触发不受影响)
        if matches_xinliweiyuan(text):
            rand_val = random.random()
            if rand_val < 0.1:  # 10% 发送图片
                image_path = os.path.abspath("data/img/xlwy.jpg")
                message = f"[CQ:image,file={image_path}]"
                # 50% 概率 @ 发送者
                if random.random() < 0.5:
                    message = f"[CQ:at,qq={sender_id}] {message}"
                logger.info("关键词回复: 发送图片 xlwy.jpg")
            else:  # 90% 原有逻辑
                if random.random() < 0.7:
                    reply = "受着"
                else:
                    reply = "那咋了"
                # 50% 概率 @ 发送者
                if random.random() < 0.5:
                    message = f"[CQ:at,qq={sender_id}] {reply}"
                else:
                    message = reply
                logger.info(f"关键词回复: {reply}")
            # 使用 sender 发送
            await self.sender.send_group_message(group_id, message)
            return

        # 提取文本内容
        # (已在上方提取用于日志记录)

        # 检查是否 @ 了机器人
        is_at_bot = self.ai_coordinator._is_at_bot(message_content)

        # 只有被@时才处理斜杠命令
        if is_at_bot:
            command = self.command_dispatcher.parse_command(text)
            if command:
                await self.command_dispatcher.dispatch(group_id, sender_id, command)
                return

        # 自动回复处理
        display_name = sender_card or sender_nickname or str(sender_id)
        await self.ai_coordinator.handle_auto_reply(
            group_id,
            sender_id,
            text,
            message_content,
            sender_name=display_name,
            group_name=group_name,
            sender_role=sender_role,
            sender_title=sender_title,
        )

    async def close(self) -> None:
        """关闭消息处理器"""
        logger.info("正在关闭消息处理器...")
        await self.ai_coordinator.queue_manager.stop()
        logger.info("消息处理器已关闭")
