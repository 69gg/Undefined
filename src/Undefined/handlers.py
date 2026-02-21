"""消息处理和命令分发"""

import asyncio
from dataclasses import dataclass
import logging
import os
import random
from typing import Any

from Undefined.ai import AIClient
from Undefined.config import Config
from Undefined.faq import FAQStorage
from Undefined.rate_limit import RateLimiter
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
from Undefined.utils.resources import resolve_resource_path
from Undefined.utils.queue_intervals import build_model_queue_intervals

from Undefined.scheduled_task_storage import ScheduledTaskStorage
from Undefined.utils.logging import log_debug_json, redact_string

logger = logging.getLogger(__name__)

KEYWORD_REPLY_HISTORY_PREFIX = "[系统关键词自动回复] "


def _format_poke_history_text(display_name: str, user_id: int) -> str:
    """格式化拍一拍历史文本。"""
    return f"{display_name}(暱称)[{user_id}(QQ号)] 拍了拍你。"


@dataclass(frozen=True)
class PrivatePokeRecord:
    poke_text: str
    sender_name: str


@dataclass(frozen=True)
class GroupPokeRecord:
    poke_text: str
    sender_name: str
    group_name: str
    sender_role: str
    sender_title: str


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
        # 初始化工具组件
        self.history_manager = MessageHistoryManager(config.history_max_records)
        self.sender = MessageSender(onebot, self.history_manager, config.bot_qq, config)

        # 初始化服务
        self.security = SecurityService(config, ai._http_client)
        self.rate_limiter = RateLimiter(config)
        self.queue_manager = QueueManager(
            max_retries=config.ai_request_max_retries,
        )
        self.queue_manager.update_model_intervals(build_model_queue_intervals(config))

        # 设置队列管理器到 AIClient（触发 Agent 介绍生成器启动）
        ai.set_queue_manager(self.queue_manager)

        self.command_dispatcher = CommandDispatcher(
            config,
            self.sender,
            ai,
            faq_storage,
            onebot,
            self.security,
            queue_manager=self.queue_manager,
            rate_limiter=self.rate_limiter,
        )
        self.ai_coordinator = AICoordinator(
            config,
            ai,
            self.queue_manager,
            self.history_manager,
            self.sender,
            onebot,
            TaskScheduler(ai, self.sender, onebot, self.history_manager, task_storage),
            self.security,
            command_dispatcher=self.command_dispatcher,
        )

        # 启动队列
        self.ai_coordinator.queue_manager.start(self.ai_coordinator.execute_reply)

    async def handle_message(self, event: dict[str, Any]) -> None:
        """处理收到的消息事件"""
        if logger.isEnabledFor(logging.DEBUG):
            log_debug_json(logger, "[事件数据]", event)
        post_type = event.get("post_type", "message")

        # 处理拍一拍事件（效果同被 @）
        if post_type == "notice" and event.get("notice_type") == "poke":
            target_id = event.get("target_id", 0)
            # 只有拍机器人才响应
            if target_id != self.config.bot_qq:
                logger.debug(
                    "[通知] 忽略拍一拍目标非机器人: target=%s",
                    target_id,
                )
                return

            if not self.config.should_process_poke_message():
                logger.debug("[消息策略] 已关闭拍一拍处理，忽略此次 poke 事件")
                return

            poke_group_id: int = event.get("group_id", 0)
            poke_sender_id: int = event.get("user_id", 0)

            # 会话白名单：不在允许列表则忽略
            if poke_group_id == 0:
                if not self.config.is_private_allowed(poke_sender_id):
                    logger.debug(
                        "[访问控制] 忽略私聊拍一拍: user=%s (allowlist enabled=%s)",
                        poke_sender_id,
                        self.config.access_control_enabled(),
                    )
                    return
            else:
                if not self.config.is_group_allowed(poke_group_id):
                    logger.debug(
                        "[访问控制] 忽略群聊拍一拍: group=%s sender=%s (allowlist enabled=%s)",
                        poke_group_id,
                        poke_sender_id,
                        self.config.access_control_enabled(),
                    )
                    return

            logger.info(
                "[通知] 收到拍一拍: group=%s sender=%s",
                poke_group_id,
                poke_sender_id,
            )
            logger.debug("[通知] 拍一拍事件数据: %s", str(event)[:200])

            if poke_group_id == 0:
                private_poke = await self._record_private_poke_history(
                    poke_sender_id, event
                )
                logger.info("[通知] 私聊拍一拍，触发私聊回复")
                await self.ai_coordinator.handle_private_reply(
                    poke_sender_id,
                    private_poke.poke_text,
                    [],
                    is_poke=True,
                    sender_name=private_poke.sender_name,
                )
            else:
                group_poke = await self._record_group_poke_history(
                    poke_group_id,
                    poke_sender_id,
                    event,
                )
                logger.info(
                    "[通知] 群聊拍一拍，触发群聊回复: group=%s",
                    poke_group_id,
                )
                await self.ai_coordinator.handle_auto_reply(
                    poke_group_id,
                    poke_sender_id,
                    group_poke.poke_text,
                    [],
                    is_poke=True,
                    sender_name=group_poke.sender_name,
                    group_name=group_poke.group_name,
                    sender_role=group_poke.sender_role,
                    sender_title=group_poke.sender_title,
                )
            return

        # 处理私聊消息
        if event.get("message_type") == "private":
            private_sender_id: int = get_message_sender_id(event)
            private_message_content: list[dict[str, Any]] = get_message_content(event)
            trigger_message_id = event.get("message_id")

            # 会话白名单：不在允许列表则忽略（不入历史、不触发任何处理）
            if not self.config.is_private_allowed(private_sender_id):
                logger.debug(
                    "[访问控制] 忽略私聊消息: user=%s (allowlist enabled=%s)",
                    private_sender_id,
                    self.config.access_control_enabled(),
                )
                return

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
                except Exception as exc:
                    logger.warning("获取用户昵称失败: %s", exc)

            text = extract_text(private_message_content, self.config.bot_qq)
            safe_text = redact_string(text)
            logger.info(
                "[私聊消息] 发送者=%s 昵称=%s 内容=%s",
                private_sender_id,
                user_name or private_sender_nickname,
                safe_text[:100],
            )

            # 保存私聊消息到历史记录（保存处理后的内容）
            # 使用新的工具函数解析内容
            parsed_content = await parse_message_content_for_history(
                private_message_content,
                self.config.bot_qq,
                self.onebot.get_msg,
                self.onebot.get_forward_msg,
            )
            safe_parsed = redact_string(parsed_content)
            logger.debug(
                "[历史记录] 保存私聊: user=%s content=%s...",
                private_sender_id,
                safe_parsed[:50],
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

            if not self.config.should_process_private_message():
                logger.debug(
                    "[消息策略] 已关闭私聊处理: user=%s",
                    private_sender_id,
                )
                return

            # Bilibili 视频自动提取（私聊）
            if self.config.bilibili_auto_extract_enabled:
                if self.config.is_bilibili_auto_extract_allowed_private(
                    private_sender_id
                ):
                    bvids = await self._extract_bilibili_ids(
                        text, private_message_content
                    )
                    if bvids:
                        asyncio.create_task(
                            self._handle_bilibili_extract(
                                private_sender_id, bvids, "private"
                            )
                        )
                        return

            # 私聊消息直接触发回复
            if await self.ai_coordinator.model_pool.handle_private_message(
                private_sender_id, text
            ):
                return
            await self.ai_coordinator.handle_private_reply(
                private_sender_id,
                text,
                private_message_content,
                sender_name=user_name,
                trigger_message_id=trigger_message_id,
            )
            return

        # 只处理群消息
        if event.get("message_type") != "group":
            return

        group_id: int = event.get("group_id", 0)
        sender_id: int = get_message_sender_id(event)
        message_content: list[dict[str, Any]] = get_message_content(event)
        trigger_message_id = event.get("message_id")

        # 会话白名单：不在允许列表则忽略（不入历史、不触发任何处理）
        if not self.config.is_group_allowed(group_id):
            logger.debug(
                "[访问控制] 忽略群消息: group=%s sender=%s (allowlist enabled=%s)",
                group_id,
                sender_id,
                self.config.access_control_enabled(),
            )
            return

        # 获取发送者信息
        group_sender: dict[str, Any] = event.get("sender", {})
        sender_card: str = group_sender.get("card", "")
        sender_nickname: str = group_sender.get("nickname", "")
        sender_role: str = group_sender.get("role", "member")
        sender_title: str = group_sender.get("title", "")

        # 提取文本内容
        text = extract_text(message_content, self.config.bot_qq)
        safe_text = redact_string(text)
        logger.info(
            f"[群消息] group={group_id} sender={sender_id} name={sender_card or sender_nickname} "
            f"role={sender_role} | {safe_text[:100]}"
        )

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
            message_content,
            self.config.bot_qq,
            self.onebot.get_msg,
            self.onebot.get_forward_msg,
        )
        safe_parsed = redact_string(parsed_content)
        logger.debug(
            f"[历史记录] 保存群聊: group={group_id}, sender={sender_id}, content={safe_parsed[:50]}..."
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

        # 检查是否 @ 了机器人（后续分流共用）
        is_at_bot = self.ai_coordinator._is_at_bot(message_content)

        # 关闭“每条消息处理”后，仅处理 @ 消息（私聊/拍一拍在其他分支中处理）
        if not self.config.should_process_group_message(is_at_bot=is_at_bot):
            logger.debug(
                "[消息策略] 跳过群消息处理: group=%s sender=%s process_every_message=%s at_bot=%s",
                group_id,
                sender_id,
                self.config.process_every_message,
                is_at_bot,
            )
            return

        # 关键词自动回复：心理委员 (使用原始消息内容提取文本，保证关键词触发不受影响)
        if self.config.keyword_reply_enabled and matches_xinliweiyuan(text):
            rand_val = random.random()
            if rand_val < 0.01:  # 1% 飞起来
                message = f"[@{sender_id}] 再发让你飞起来"
                logger.info("关键词回复: 再发让你飞起来")
                await self.sender.send_group_message(
                    group_id,
                    message,
                    history_prefix=KEYWORD_REPLY_HISTORY_PREFIX,
                )
                return
            elif rand_val < 0.11:  # 10% 发送图片
                try:
                    image_path = str(resolve_resource_path("img/xlwy.jpg").resolve())
                except Exception:
                    image_path = os.path.abspath("img/xlwy.jpg")
                message = f"[CQ:image,file={image_path}]"
                # 50% 概率 @ 发送者
                if random.random() < 0.5:
                    message = f"[@{sender_id}] {message}"
                logger.info("关键词回复: 发送图片 xlwy.jpg")
            else:  # 90% 原有逻辑
                if random.random() < 0.7:
                    reply = "受着"
                else:
                    reply = "那咋了"
                # 50% 概率 @ 发送者
                if random.random() < 0.5:
                    message = f"[@{sender_id}] {reply}"
                else:
                    message = reply
                logger.info(f"关键词回复: {reply}")
            # 使用 sender 发送
            await self.sender.send_group_message(
                group_id,
                message,
                history_prefix=KEYWORD_REPLY_HISTORY_PREFIX,
            )
            return

        # Bilibili 视频自动提取
        if self.config.bilibili_auto_extract_enabled:
            if self.config.is_bilibili_auto_extract_allowed_group(group_id):
                bvids = await self._extract_bilibili_ids(text, message_content)
                if bvids:
                    asyncio.create_task(
                        self._handle_bilibili_extract(group_id, bvids, "group")
                    )
                    return

        # 提取文本内容
        # (已在上方提取用于日志记录)

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
            trigger_message_id=trigger_message_id,
        )

    async def _record_private_poke_history(
        self, user_id: int, event: dict[str, Any]
    ) -> PrivatePokeRecord:
        """记录私聊拍一拍到历史。"""
        sender = event.get("sender", {})
        sender_nickname = ""
        if isinstance(sender, dict):
            sender_nickname = str(sender.get("nickname", "")).strip()

        user_name = sender_nickname
        if not user_name:
            try:
                user_info = await self.onebot.get_stranger_info(user_id)
                if isinstance(user_info, dict):
                    user_name = str(user_info.get("nickname", "")).strip()
            except Exception as exc:
                logger.warning(
                    "[通知] 获取私聊拍一拍用户昵称失败: user=%s err=%s",
                    user_id,
                    exc,
                )

        display_name = sender_nickname or user_name or f"QQ{user_id}"
        normalized_user_name = user_name or display_name
        poke_text = _format_poke_history_text(display_name, user_id)

        try:
            await self.history_manager.add_private_message(
                user_id=user_id,
                text_content=poke_text,
                display_name=display_name,
                user_name=normalized_user_name,
            )
        except Exception as exc:
            logger.warning(
                "[历史记录] 写入私聊拍一拍失败: user=%s err=%s",
                user_id,
                exc,
            )
        return PrivatePokeRecord(poke_text=poke_text, sender_name=display_name)

    async def _record_group_poke_history(
        self,
        group_id: int,
        sender_id: int,
        event: dict[str, Any],
    ) -> GroupPokeRecord:
        """记录群聊拍一拍到历史。"""
        sender = event.get("sender", {})
        sender_card = ""
        sender_nickname = ""
        sender_role = "member"
        sender_title = ""
        if isinstance(sender, dict):
            sender_card = str(sender.get("card", "")).strip()
            sender_nickname = str(sender.get("nickname", "")).strip()
            sender_role = str(sender.get("role", "member")).strip() or "member"
            sender_title = str(sender.get("title", "")).strip()

        if not sender_card and not sender_nickname:
            try:
                member_info = await self.onebot.get_group_member_info(
                    group_id, sender_id
                )
                if isinstance(member_info, dict):
                    sender_card = str(member_info.get("card", "")).strip()
                    sender_nickname = str(member_info.get("nickname", "")).strip()
                    sender_role = (
                        str(member_info.get("role", "member")).strip() or "member"
                    )
                    sender_title = str(member_info.get("title", "")).strip()
            except Exception as exc:
                logger.warning(
                    "[通知] 获取拍一拍群成员信息失败: group=%s user=%s err=%s",
                    group_id,
                    sender_id,
                    exc,
                )

        group_name = ""
        try:
            group_info = await self.onebot.get_group_info(group_id)
            if isinstance(group_info, dict):
                group_name = str(group_info.get("group_name", "")).strip()
        except Exception as exc:
            logger.warning(
                "[通知] 获取拍一拍群名失败: group=%s err=%s",
                group_id,
                exc,
            )

        display_name = sender_card or sender_nickname or f"QQ{sender_id}"
        poke_text = _format_poke_history_text(display_name, sender_id)
        normalized_group_name = group_name or f"群{group_id}"

        try:
            await self.history_manager.add_group_message(
                group_id=group_id,
                sender_id=sender_id,
                text_content=poke_text,
                sender_card=sender_card,
                sender_nickname=sender_nickname,
                group_name=normalized_group_name,
                role=sender_role,
                title=sender_title,
            )
        except Exception as exc:
            logger.warning(
                "[历史记录] 写入群聊拍一拍失败: group=%s sender=%s err=%s",
                group_id,
                sender_id,
                exc,
            )
        return GroupPokeRecord(
            poke_text=poke_text,
            sender_name=display_name,
            group_name=normalized_group_name,
            sender_role=sender_role,
            sender_title=sender_title,
        )

    async def _extract_bilibili_ids(
        self, text: str, message_content: list[dict[str, Any]]
    ) -> list[str]:
        """从文本和消息段中提取 B 站视频 BV 号。"""
        from Undefined.bilibili.parser import (
            extract_bilibili_ids,
            extract_from_json_message,
        )

        bvids = await extract_bilibili_ids(text)
        if not bvids:
            bvids = await extract_from_json_message(message_content)
        return bvids

    async def _handle_bilibili_extract(
        self,
        target_id: int,
        bvids: list[str],
        target_type: str,
    ) -> None:
        """处理 bilibili 视频自动提取和发送。"""
        from Undefined.bilibili.sender import send_bilibili_video

        for bvid in bvids[:3]:  # 最多同时处理 3 个
            try:
                await send_bilibili_video(
                    video_id=bvid,
                    sender=self.sender,
                    onebot=self.onebot,
                    target_type=target_type,  # type: ignore[arg-type]
                    target_id=target_id,
                    cookie=self.config.bilibili_cookie,
                    prefer_quality=self.config.bilibili_prefer_quality,
                    max_duration=self.config.bilibili_max_duration,
                    max_file_size=self.config.bilibili_max_file_size,
                    oversize_strategy=self.config.bilibili_oversize_strategy,
                )
            except Exception as exc:
                logger.error(
                    "[Bilibili] 自动提取失败 %s → %s:%s: %s",
                    bvid,
                    target_type,
                    target_id,
                    exc,
                )
                try:
                    error_msg = f"视频提取失败: {exc}"
                    if target_type == "group":
                        await self.sender.send_group_message(
                            target_id, error_msg, auto_history=False
                        )
                    else:
                        await self.sender.send_private_message(
                            target_id, error_msg, auto_history=False
                        )
                except Exception:
                    pass

    async def close(self) -> None:
        """关闭消息处理器"""
        logger.info("正在关闭消息处理器...")
        await self.ai_coordinator.queue_manager.stop()
        logger.info("消息处理器已关闭")
