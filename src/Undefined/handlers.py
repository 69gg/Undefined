"""消息处理和命令分发"""

import asyncio
import logging
import os
import random
import re
from datetime import datetime
from typing import Any

from .ai import AIClient
from .config import Config
from .faq import FAQStorage, extract_faq_title
from .injection_response_agent import InjectionResponseAgent
from .onebot import (
    OneBotClient,
    get_message_content,
    get_message_sender_id,
    parse_message_time,
)
from .rate_limit import RateLimiter
from .utils.common import extract_text, parse_message_content_for_history
from .utils.history import MessageHistoryManager
from .utils.scheduler import TaskScheduler
from .utils.sender import MessageSender

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
    ) -> None:
        self.config = config
        self.onebot = onebot
        self.ai = ai
        self.faq_storage = faq_storage
        self.rate_limiter = RateLimiter(config)
        # 注入攻击回复生成器
        self.injection_response_agent = InjectionResponseAgent(config.security_model)

        # 初始化 Utils
        self.history_manager = MessageHistoryManager()
        self.sender = MessageSender(onebot, self.history_manager, config.bot_qq)

        # 初始化定时任务调度器
        self.scheduler = TaskScheduler(ai, self)

        # AI 请求队列（四个队列）
        self._superadmin_queue: asyncio.Queue[dict[str, Any]] = (
            asyncio.Queue()
        )  # 超级管理员私聊队列（最高优先级）
        self._private_queue: asyncio.Queue[dict[str, Any]] = (
            asyncio.Queue()
        )  # 普通私聊队列（高优先级）
        self._group_mention_queue: asyncio.Queue[dict[str, Any]] = (
            asyncio.Queue()
        )  # 群聊被@队列（中等优先级）
        self._group_normal_queue: asyncio.Queue[dict[str, Any]] = (
            asyncio.Queue()
        )  # 群聊普通队列（最低优先级）
        # AI 请求间隔（秒）
        self.ai_request_interval = 1.0
        # 队列处理任务
        self._queue_processor_task: asyncio.Task[None] | None = None

        # 启动队列处理任务
        self._queue_processor_task = asyncio.create_task(
            self._process_ai_request_queue()
        )

    async def handle_message(self, event: dict[str, Any]) -> None:
        """处理收到的消息事件"""
        post_type = event.get("post_type", "message")

        # 处理拍一拍事件（效果同被 @）
        if post_type == "notice" and event.get("notice_type") == "poke":
            target_id = event.get("target_id", 0)
            # 只有拍机器人才响应
            if target_id != self.config.bot_qq:
                return

            logger.info(f"拍一拍事件完整数据: {event}")
            poke_group_id: int = event.get("group_id", 0)
            poke_sender_id: int = event.get("user_id", 0)

            logger.info(
                f"收到拍一拍事件: group={poke_group_id}, sender={poke_sender_id}"
            )

            # 如果 group_id 为 0，说明是私聊拍一拍
            if poke_group_id == 0:
                logger.info("私聊拍一拍，触发私聊回复")
                await self._handle_private_reply(
                    poke_sender_id,
                    "(拍了拍你)",  # 空消息文本
                    [],  # 空消息内容
                    is_poke=True,
                    sender_name=str(poke_sender_id),
                )
            else:
                # 群聊拍一拍，触发群聊自动回复
                await self._handle_auto_reply(
                    poke_group_id,
                    poke_sender_id,
                    "(拍了拍你)",  # 空消息文本
                    [],  # 空消息内容
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
                f"收到私聊消息: sender={private_sender_id}, text={text[:50]}..."
            )

            # 获取私聊用户昵称
            user_name = private_sender_nickname
            if not user_name:
                try:
                    user_info = await self.onebot.get_stranger_info(private_sender_id)
                    if user_info:
                        user_name = user_info.get("nickname", "")
                except Exception as e:
                    logger.warning(f"获取用户昵称失败: {e}")

            # 保存私聊消息到历史记录（保存处理后的内容）
            # 使用新的 utils
            parsed_content = await parse_message_content_for_history(
                processed_message_content, self.config.bot_qq, self.onebot.get_msg
            )
            self.history_manager.add_private_message(
                user_id=private_sender_id,
                text_content=parsed_content,
                display_name=private_sender_nickname,
                user_name=user_name,
            )

            # 如果是 bot 自己的消息，只保存不触发回复，避免无限循环
            if private_sender_id == self.config.bot_qq:
                return

            # 私聊消息直接触发回复（相当于被 @），使用处理后的内容
            await self._handle_private_reply(
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

        # 获取发送者昵称信息
        group_sender: dict[str, Any] = event.get("sender", {})
        sender_card: str = group_sender.get("card", "")
        sender_nickname: str = group_sender.get("nickname", "")

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
        self.history_manager.add_group_message(
            group_id=group_id,
            sender_id=sender_id,
            text_content=parsed_content,
            sender_card=sender_card,
            sender_nickname=sender_nickname,
            group_name=group_name,
        )

        # 如果是 bot 自己的消息，只保存不触发回复，避免无限循环
        if sender_id == self.config.bot_qq:
            return

        # 关键词自动回复：心理委员 (使用原始消息内容提取文本，保证关键词触发不受影响)
        text = extract_text(message_content, self.config.bot_qq)
        if "心理委员" in text:
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
        text = extract_text(message_content, self.config.bot_qq)

        # 检查是否 @ 了机器人
        is_at_bot = self._is_at_bot(message_content)

        # 只有被@时才处理斜杠命令
        if is_at_bot:
            command = self._parse_command(text)

            if command:
                # 有命令，执行命令
                logger.info(f"解析到命令: {command['name']}, args={command['args']}")

                # 分发命令
                cmd_name: str = command["name"]
                cmd_args: list[str] = command["args"]

                logger.info(f"执行命令: /{cmd_name} {' '.join(cmd_args)}")

                try:
                    # 公开命令 - 无权限限制但有速率限制
                    if cmd_name == "help":
                        await self._handle_help(group_id)
                    elif cmd_name == "lsfaq":
                        await self._check_rate_limit_and_handle(
                            group_id, sender_id, self._handle_lsfaq, group_id
                        )
                    elif cmd_name == "viewfaq":
                        await self._check_rate_limit_and_handle(
                            group_id,
                            sender_id,
                            self._handle_viewfaq,
                            group_id,
                            cmd_args,
                        )
                    elif cmd_name == "searchfaq":
                        await self._check_rate_limit_and_handle(
                            group_id,
                            sender_id,
                            self._handle_searchfaq,
                            group_id,
                            cmd_args,
                        )
                    elif cmd_name == "lsadmin":
                        await self._handle_lsadmin(group_id)

                    # 管理员命令
                    elif cmd_name == "delfaq":
                        if not self.config.is_admin(sender_id):
                            await self.sender.send_group_message(
                                group_id, "⚠️ 权限不足：只有管理员可以使用此命令"
                            )
                            return
                        await self._check_rate_limit_and_handle(
                            group_id, sender_id, self._handle_delfaq, group_id, cmd_args
                        )
                    elif cmd_name == "bugfix":
                        if not self.config.is_admin(sender_id):
                            await self.sender.send_group_message(
                                group_id, "⚠️ 权限不足：只有管理员可以使用此命令"
                            )
                            return
                        await self._check_rate_limit_and_handle(
                            group_id,
                            sender_id,
                            self._handle_bugfix,
                            group_id,
                            sender_id,
                            cmd_args,
                        )

                    # 超级管理员命令
                    elif cmd_name == "addadmin":
                        if not self.config.is_superadmin(sender_id):
                            await self.sender.send_group_message(
                                group_id, "⚠️ 权限不足：只有超级管理员可以使用此命令"
                            )
                            return
                        await self._handle_addadmin(group_id, cmd_args)
                    elif cmd_name == "rmadmin":
                        if not self.config.is_superadmin(sender_id):
                            await self.sender.send_group_message(
                                group_id, "⚠️ 权限不足：只有超级管理员可以使用此命令"
                            )
                            return
                        await self._handle_rmadmin(group_id, cmd_args)

                    else:
                        await self.sender.send_group_message(
                            group_id,
                            f"❌ 未知命令: {cmd_name}\n使用 /help 查看可用命令",
                        )
                    logger.info(f"命令执行完成: /{cmd_name}")
                except Exception as e:
                    logger.exception(f"命令执行失败: {e}")
                    await self.sender.send_group_message(
                        group_id, f"❌ 命令执行失败: {e}"
                    )
                return

        # 自动回复处理（没被@或被@但没有命令）
        # 注意：未被@的消息中的斜杠命令不会被处理，只作为普通文本
        display_name = sender_card or sender_nickname or str(sender_id)
        await self._handle_auto_reply(
            group_id,
            sender_id,
            text,
            message_content,
            sender_name=display_name,
            group_name=group_name,
        )

    def _trim_queue_if_needed(self) -> None:
        """如果群聊普通队列超过10个，仅保留最新的2个"""
        queue_size = self._group_normal_queue.qsize()
        if queue_size > 10:
            logger.info(f"群聊普通队列长度 {queue_size} 超过10，仅保留最新的2个")
            # 取出所有元素
            all_requests: list[dict[str, Any]] = []
            while not self._group_normal_queue.empty():
                all_requests.append(self._group_normal_queue.get_nowait())
            # 只保留最新的2个
            latest_requests = all_requests[-2:]
            # 放回队列
            for req in latest_requests:
                self._group_normal_queue.put_nowait(req)
            logger.info(
                f"群聊普通队列已修剪，当前长度: {self._group_normal_queue.qsize()}"
            )

    async def _process_ai_request_queue(self) -> None:
        """处理 AI 请求队列"""
        logger.info("AI 请求队列处理任务已启动")

        queues = [
            self._superadmin_queue,
            self._private_queue,
            self._group_mention_queue,
            self._group_normal_queue,
        ]
        queue_names = ["超级管理员私聊", "私聊", "群聊被@", "群聊普通"]

        current_queue_idx = 0
        current_queue_processed = 0
        last_transfer_to_normal = False
        transfer_count = 0

        try:
            while True:
                try:
                    current_queue = queues[current_queue_idx]

                    if current_queue.empty():
                        all_empty = all(q.empty() for q in queues)
                        if all_empty:
                            await asyncio.sleep(0.2)
                            continue

                        current_queue_idx = (current_queue_idx + 1) % 4
                        current_queue_processed = 0
                        transfer_count += 1
                        continue

                    request = await current_queue.get()
                    request_type = request.get("type", "unknown")

                    logger.info(
                        f"开始处理{queue_names[current_queue_idx]}请求: {request_type}, 队列剩余: {current_queue.qsize()}"
                    )

                    try:
                        if request_type == "auto_reply":
                            await self._execute_auto_reply(request)
                        elif request_type == "private_reply":
                            await self._execute_private_reply(request)
                        else:
                            logger.warning(f"未知的请求类型: {request_type}")
                    except Exception as e:
                        logger.exception(f"处理 AI 请求失败: {e}")
                    finally:
                        current_queue.task_done()

                    current_queue_processed += 1

                    if current_queue_processed >= 2:
                        next_queue_idx = (current_queue_idx + 1) % 4
                        logger.info(
                            f"{queue_names[current_queue_idx]}队列已处理2条，转移到{queue_names[next_queue_idx]}队列"
                        )

                        if next_queue_idx == 3:
                            last_transfer_to_normal = True
                        else:
                            last_transfer_to_normal = False

                        current_queue_idx = next_queue_idx
                        current_queue_processed = 0
                        transfer_count += 1

                    if (
                        transfer_count > 0
                        and transfer_count % 2 == 0
                        and not last_transfer_to_normal
                    ):
                        if not self._group_normal_queue.empty():
                            normal_request = await self._group_normal_queue.get()
                            normal_type = normal_request.get("type", "unknown")
                            logger.info(f"强制处理群聊普通请求: {normal_type}")
                            try:
                                if normal_type == "auto_reply":
                                    await self._execute_auto_reply(normal_request)
                                else:
                                    logger.warning(f"未知的请求类型: {normal_type}")
                            except Exception as e:
                                logger.exception(f"处理群聊普通请求失败: {e}")
                            finally:
                                self._group_normal_queue.task_done()
                        transfer_count = 0

                    await asyncio.sleep(self.ai_request_interval)

                except asyncio.CancelledError:
                    logger.info("AI 请求队列处理任务被取消")
                    break
                except Exception as e:
                    logger.exception(f"队列处理循环出错: {e}")
                    await asyncio.sleep(1.0)
        finally:
            logger.info("AI 请求队列处理任务已退出")

    async def _execute_auto_reply(self, request: dict[str, Any]) -> None:
        """执行自动回复请求"""
        group_id = request["group_id"]
        sender_id = request["sender_id"]
        full_question = request["full_question"]

        # 定义回调 - 使用 sender
        async def send_message_callback(
            message: str, at_user: int | None = None
        ) -> None:
            if at_user:
                message = f"[CQ:at,qq={at_user}] {message}"
            logger.debug(
                f"send_message_callback: group_id={group_id}, message={message[:50]}..."
            )
            await self.sender.send_group_message(group_id, message)

        # 使用 history_manager 获取历史
        async def get_recent_messages_callback(
            chat_id: str, msg_type: str, start: int, end: int
        ) -> list[dict[str, Any]]:
            return self.history_manager.get_recent(chat_id, msg_type, start, end)

        # 定义私聊发送回调
        async def send_private_message_callback(user_id: int, message: str) -> None:
            logger.debug(
                f"send_private_message_callback: user_id={user_id}, message={message[:50]}..."
            )
            await self.sender.send_private_message(user_id, message)

        # 定义发送图片回调
        async def send_image_callback(
            target_id: int, msg_type: str, image_path: str
        ) -> None:
            logger.debug(
                f"send_image_callback: target_id={target_id}, msg_type={msg_type}, image={image_path}"
            )
            await self._send_image(target_id, msg_type, image_path)

        # 定义点赞回调
        async def send_like_callback(target_user_id: int, times: int = 1) -> None:
            logger.debug(
                f"send_like_callback: target_user_id={target_user_id}, times={times}"
            )
            await self.onebot.send_like(target_user_id, times)

        try:
            self.ai.current_group_id = group_id
            self.ai.current_user_id = sender_id
            self.ai._send_private_message_callback = send_private_message_callback
            self.ai._send_image_callback = send_image_callback

            await self.ai.ask(
                full_question,
                send_message_callback=send_message_callback,
                get_recent_messages_callback=get_recent_messages_callback,
                get_image_url_callback=self.onebot.get_image,
                get_forward_msg_callback=self.onebot.get_forward_msg,
                send_like_callback=send_like_callback,
                sender=self.sender,
                history_manager=self.history_manager,
                onebot_client=self.onebot,
            )
        except Exception as e:
            logger.error(f"自动回复处理出错: {e}")

    async def _execute_private_reply(self, request: dict[str, Any]) -> None:
        """执行私聊回复请求"""
        user_id = request["user_id"]
        full_question = request["full_question"]

        # 定义回调 - 使用 sender (private)
        async def send_message_callback(
            message: str, at_user: int | None = None
        ) -> None:
            await self.sender.send_private_message(user_id, message)
            # sender 内部已经自动保存历史，不需要手动调用

        # 获取私聊历史消息
        async def get_recent_messages_callback(
            chat_id: str, msg_type: str, start: int, end: int
        ) -> list[dict[str, Any]]:
            return self.history_manager.get_recent(chat_id, msg_type, start, end)

        # 定义发送图片回调
        async def send_image_callback(
            target_id: int, msg_type: str, image_path: str
        ) -> None:
            logger.debug(
                f"send_image_callback: target_id={target_id}, msg_type={msg_type}, image={image_path}"
            )
            await self._send_image(target_id, msg_type, image_path)

        # 定义点赞回调
        async def send_like_callback(target_user_id: int, times: int = 1) -> None:
            logger.debug(
                f"send_like_callback: target_user_id={target_user_id}, times={times}"
            )
            await self.onebot.send_like(target_user_id, times)

        try:
            self.ai.current_group_id = None
            self.ai.current_user_id = user_id
            self.ai._send_image_callback = send_image_callback
            result = await self.ai.ask(
                full_question,
                send_message_callback=send_message_callback,
                get_recent_messages_callback=get_recent_messages_callback,
                get_image_url_callback=self.onebot.get_image,
                get_forward_msg_callback=self.onebot.get_forward_msg,
                send_like_callback=send_like_callback,
                sender=self.sender,
                history_manager=self.history_manager,
                onebot_client=self.onebot,
            )
            # 如果 AI 直接返回了文本（没有调用工具），自动发送
            if result:
                logger.info(f"AI 直接返回文本，自动发送私聊消息: {result[:50]}...")
                await self.sender.send_private_message(user_id, result)
                # sender 内部已经自动保存历史
        except Exception as e:
            logger.error(f"私聊回复处理出错: {e}")

    async def _handle_auto_reply(
        self,
        group_id: int,
        sender_id: int,
        text: str,
        message_content: list[dict[str, Any]],
        is_poke: bool = False,
        sender_name: str = "未知用户",
        group_name: str = "未知群聊",
    ) -> None:
        """自动回复处理：根据上下文决定是否回复"""
        is_at_bot = is_poke or self._is_at_bot(message_content)

        if sender_id != self.config.superadmin_qq:
            logger.info(
                f"对群聊消息进行注入检测: group_id={group_id}, sender_id={sender_id}, text={text[:50]}..."
            )
            is_injection = await self.ai.detect_injection(text, message_content)
            if is_injection:
                logger.warning(
                    f"检测到提示词注入攻击: group_id={group_id}, sender_id={sender_id}, text={text[:100]}..."
                )
                self.history_manager.modify_last_group_message(
                    group_id, sender_id, "<这句话检测到用户进行注入，已删除>"
                )

                if is_at_bot:
                    await self._handle_injection_response(
                        group_id, text, sender_id=sender_id
                    )
                return

        prompt_prefix = ""
        if is_poke:
            prompt_prefix = "(用户拍了拍你) "
        elif is_at_bot:
            prompt_prefix = "(用户 @ 了你) "

        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        location = group_name if group_name.endswith("群") else f"{group_name}群"

        full_question = f"""{prompt_prefix}<message sender="{sender_name}" sender_id="{sender_id}" location="{location}" time="{current_time}">
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

        self._trim_queue_if_needed()

        if is_at_bot:
            await self._group_mention_queue.put(
                {
                    "type": "auto_reply",
                    "group_id": group_id,
                    "sender_id": sender_id,
                    "text": text,
                    "full_question": full_question,
                    "is_at_bot": is_at_bot,
                }
            )
            logger.debug(
                f"AI 请求已加入群聊被@队列，当前队列长度: {self._group_mention_queue.qsize()}"
            )
        else:
            await self._group_normal_queue.put(
                {
                    "type": "auto_reply",
                    "group_id": group_id,
                    "sender_id": sender_id,
                    "text": text,
                    "full_question": full_question,
                    "is_at_bot": is_at_bot,
                }
            )
            logger.debug(
                f"AI 请求已加入群聊普通队列，当前队列长度: {self._group_normal_queue.qsize()}"
            )

    async def _handle_private_reply(
        self,
        user_id: int,
        text: str,
        message_content: list[dict[str, Any]],
        is_poke: bool = False,
        sender_name: str = "未知用户",
    ) -> None:
        """私聊回复处理"""
        is_superadmin = user_id == self.config.superadmin_qq

        if not is_superadmin:
            logger.info(
                f"对私聊消息进行注入检测: user_id={user_id}, text={text[:50]}..."
            )
            is_injection = await self.ai.detect_injection(text, message_content)
            if is_injection:
                logger.warning(
                    f"检测到提示词注入攻击: user_id={user_id}, text={text[:100]}..."
                )
                self.history_manager.modify_last_private_message(
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

        is_superadmin = user_id == self.config.superadmin_qq

        if is_superadmin:
            await self._superadmin_queue.put(
                {
                    "type": "private_reply",
                    "user_id": user_id,
                    "text": text,
                    "full_question": full_question,
                }
            )
            logger.debug(
                f"超级管理员私聊 AI 请求已加入超级管理员队列，当前队列长度: {self._superadmin_queue.qsize()}"
            )
        else:
            await self._private_queue.put(
                {
                    "type": "private_reply",
                    "user_id": user_id,
                    "text": text,
                    "full_question": full_question,
                }
            )
            logger.debug(
                f"私聊 AI 请求已加入私聊队列，当前队列长度: {self._private_queue.qsize()}"
            )

    async def _send_image(
        self, target_id: int, message_type: str, image_path: str
    ) -> None:
        """发送图片或音频到指定目标（群聊或私聊）

        Args:
            target_id: 目标 ID（群号或用户 QQ 号）
            message_type: 消息类型（group 或 private）
            image_path: 媒体文件路径
        """
        # 检查文件是否存在
        if not os.path.exists(image_path):
            logger.error(f"文件不存在: {image_path}")
            return

        # 使用绝对路径
        abs_path = os.path.abspath(image_path)
        # 根据文件扩展名确定消息类型
        ext = os.path.splitext(image_path)[1].lower()

        # 检查文件大小（限制在100MB以内）
        file_size = os.path.getsize(abs_path)
        MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB

        if file_size > MAX_FILE_SIZE:
            logger.error(f"文件过大: {file_size}字节 > {MAX_FILE_SIZE}字节限制")
            return

        if ext in [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"]:
            # 图片文件
            message = f"[CQ:image,file={abs_path}]"
            media_type = "图片"
        elif ext in [".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac"]:
            # 音频文件，统一使用record格式尝试发送
            message = f"[CQ:record,file={abs_path}]"
            media_type = "音频"
        else:
            logger.error(f"不支持的媒体文件格式: {ext}")
            return

        try:
            if message_type == "group":
                await self.onebot.send_group_message(target_id, message)
                logger.info(
                    f"已发送{media_type}到群聊 {target_id}: {image_path} (大小: {file_size}字节)"
                )
            elif message_type == "private":
                await self.onebot.send_private_message(target_id, message)
                logger.info(
                    f"已发送{media_type}到私聊 {target_id}: {image_path} (大小: {file_size}字节)"
                )
            else:
                logger.error(f"未知的消息类型: {message_type}")
        except Exception as e:
            logger.exception(f"发送{media_type}失败: {e}")
            # 重新抛出异常，让上层处理
            raise

    async def _handle_injection_response(
        self,
        target_id: int,
        original_message: str,
        is_private: bool = False,
        sender_id: int | None = None,
    ) -> None:
        """处理注入攻击的回复（使用 undefined 人设）"""
        reply = await self.injection_response_agent.generate_response(original_message)

        if is_private:
            await self.sender.send_private_message(target_id, reply, auto_history=False)
            # 历史记录中仅保留占位符
            self.history_manager.add_private_message(
                user_id=target_id,
                text_content="<对注入消息的回复>",
                display_name="Bot",
                user_name="Bot",
            )
            logger.info(f"已发送注入攻击警告（私聊）: user_id={target_id}")
        else:
            if sender_id:
                reply_with_at = f"[CQ:at,qq={sender_id}] {reply}"
                await self.sender.send_group_message(
                    target_id, reply_with_at, auto_history=False
                )
            else:
                await self.sender.send_group_message(
                    target_id, reply, auto_history=False
                )

            # 历史记录中仅保留占位符
            self.history_manager.add_group_message(
                group_id=target_id,
                sender_id=self.config.bot_qq,
                text_content="<对注入消息的回复>",
                sender_nickname="Bot",
                group_name="",
            )
            logger.info(
                f"已发送注入攻击警告（群聊）: group_id={target_id}, sender_id={sender_id}"
            )

    async def _check_rate_limit_and_handle(
        self, group_id: int, user_id: int, handler: Any, *args: Any
    ) -> None:
        """检查速率限制并执行处理器"""
        allowed, remaining = self.rate_limiter.check(user_id)

        if not allowed:
            await self.sender.send_group_message(
                group_id, f"⏳ 操作太频繁，请 {remaining} 秒后再试"
            )
            return

        self.rate_limiter.record(user_id)
        await handler(*args)

    def _is_at_bot(self, message_content: list[dict[str, Any]]) -> bool:
        """检查消息是否 @ 了机器人"""
        for segment in message_content:
            if segment.get("type") == "at":
                qq = segment.get("data", {}).get("qq", "")
                if str(qq) == str(self.config.bot_qq):
                    return True
        return False

    def _parse_command(self, text: str) -> dict[str, Any] | None:
        """解析命令"""
        clean_text = re.sub(r"\[@\s*\d+\]", "", text).strip()
        match = re.match(r"/(\w+)\s*(.*)", clean_text)
        if not match:
            return None

        cmd_name = match.group(1).lower()
        args_str = match.group(2).strip()

        return {
            "name": cmd_name,
            "args": args_str.split() if args_str else [],
        }

    async def _handle_help(self, group_id: int) -> None:
        """处理 /help 命令"""
        await self.sender.send_group_message(group_id, HELP_MESSAGE)

    async def _handle_lsfaq(self, group_id: int) -> None:
        """处理 /lsfaq 命令"""
        faqs = self.faq_storage.list_all(group_id)

        if not faqs:
            await self.sender.send_group_message(group_id, "📭 当前群组没有保存的 FAQ")
            return

        lines = ["📋 FAQ 列表：", ""]
        for faq in faqs[:20]:
            lines.append(f"📌 [{faq.id}] {faq.title}")
            lines.append(f"   创建时间: {faq.created_at[:10]}")
            lines.append("")

        if len(faqs) > 20:
            lines.append(f"... 还有 {len(faqs) - 20} 条")

        await self.sender.send_group_message(group_id, "\n".join(lines))

    async def _handle_viewfaq(self, group_id: int, args: list[str]) -> None:
        """处理 /viewfaq 命令"""
        if not args:
            await self.sender.send_group_message(
                group_id, "❌ 用法: /viewfaq <ID>\n示例: /viewfaq 20241205-001"
            )
            return

        faq_id = args[0]
        faq = self.faq_storage.get(group_id, faq_id)

        if not faq:
            await self.sender.send_group_message(group_id, f"❌ FAQ 不存在: {faq_id}")
            return

        message = f"""📖 FAQ: {faq.title}

🆔 ID: {faq.id}
👤 分析对象: {faq.target_qq}
📅 时间范围: {faq.start_time} ~ {faq.end_time}
🕐 创建时间: {faq.created_at}

{faq.content}"""

        await self.sender.send_group_message(group_id, message)

    async def _handle_searchfaq(self, group_id: int, args: list[str]) -> None:
        """处理 /searchfaq 命令"""
        if not args:
            await self.sender.send_group_message(
                group_id, "❌ 用法: /searchfaq <关键词>\n示例: /searchfaq 登录"
            )
            return

        keyword = " ".join(args)
        results = self.faq_storage.search(group_id, keyword)

        if not results:
            await self.sender.send_group_message(
                group_id, f'🔍 未找到包含 "{keyword}" 的 FAQ'
            )
            return

        lines = [f'🔍 搜索 "{keyword}" 找到 {len(results)} 条结果：', ""]
        for faq in results[:10]:
            lines.append(f"📌 [{faq.id}] {faq.title}")
            lines.append("")

        if len(results) > 10:
            lines.append(f"... 还有 {len(results) - 10} 条")

        lines.append("\n使用 /viewfaq <ID> 查看详情")

        await self.sender.send_group_message(group_id, "\n".join(lines))

    async def _handle_delfaq(self, group_id: int, args: list[str]) -> None:
        """处理 /delfaq 命令"""
        if not args:
            await self.sender.send_group_message(
                group_id, "❌ 用法: /delfaq <ID>\n示例: /delfaq 20241205-001"
            )
            return

        faq_id = args[0]

        faq = self.faq_storage.get(group_id, faq_id)
        if not faq:
            await self.sender.send_group_message(group_id, f"❌ FAQ 不存在: {faq_id}")
            return

        success = self.faq_storage.delete(group_id, faq_id)
        if success:
            await self.sender.send_group_message(
                group_id, f"✅ 已删除 FAQ: [{faq_id}] {faq.title}"
            )
        else:
            await self.sender.send_group_message(group_id, f"❌ 删除失败: {faq_id}")

    async def _handle_lsadmin(self, group_id: int) -> None:
        """处理 /lsadmin 命令"""
        lines: list[str] = []
        lines.append(f"👑 超级管理员: {self.config.superadmin_qq}")

        admins = [qq for qq in self.config.admin_qqs if qq != self.config.superadmin_qq]
        if admins:
            admin_list = "\n".join([f"- {qq}" for qq in admins])
            lines.append(f"\n📋 管理员列表：\n{admin_list}")
        else:
            lines.append("\n📋 暂无其他管理员")

        await self.sender.send_group_message(group_id, "\n".join(lines))

    async def _handle_addadmin(self, group_id: int, args: list[str]) -> None:
        """处理 /addadmin 命令"""
        if not args:
            await self.sender.send_group_message(
                group_id, "❌ 用法: /addadmin <QQ号>\n示例: /addadmin 123456789"
            )
            return

        try:
            new_admin_qq = int(args[0])
        except ValueError:
            await self.sender.send_group_message(
                group_id, "❌ QQ 号格式错误，必须为数字"
            )
            return

        if self.config.is_admin(new_admin_qq):
            await self.sender.send_group_message(
                group_id, f"⚠️ {new_admin_qq} 已经是管理员了"
            )
            return

        try:
            self.config.add_admin(new_admin_qq)
            await self.sender.send_group_message(
                group_id, f"✅ 已添加管理员: {new_admin_qq}"
            )
        except Exception as e:
            logger.exception(f"添加管理员失败: {e}")
            await self.sender.send_group_message(group_id, f"❌ 添加管理员失败: {e}")

    async def _handle_rmadmin(self, group_id: int, args: list[str]) -> None:
        """处理 /rmadmin 命令"""
        if not args:
            await self.sender.send_group_message(
                group_id, "❌ 用法: /rmadmin <QQ号>\n示例: /rmadmin 123456789"
            )
            return

        try:
            target_qq = int(args[0])
        except ValueError:
            await self.sender.send_group_message(
                group_id, "❌ QQ 号格式错误，必须为数字"
            )
            return

        if self.config.is_superadmin(target_qq):
            await self.sender.send_group_message(group_id, "❌ 无法移除超级管理员")
            return

        if not self.config.is_admin(target_qq):
            await self.sender.send_group_message(group_id, f"⚠️ {target_qq} 不是管理员")
            return

        try:
            self.config.remove_admin(target_qq)
            await self.sender.send_group_message(
                group_id, f"✅ 已移除管理员: {target_qq}"
            )
        except Exception as e:
            logger.exception(f"移除管理员失败: {e}")
            await self.sender.send_group_message(group_id, f"❌ 移除管理员失败: {e}")

    async def _handle_bugfix(
        self, group_id: int, admin_id: int, args: list[str]
    ) -> None:
        """处理 /bugfix 命令"""
        if len(args) < 3:
            await self.sender.send_group_message(
                group_id,
                "❌ 用法: /bugfix <QQ号1> [QQ号2] ... <开始时间> <结束时间>\n"
                "时间格式: YYYY/MM/DD/HH:MM，结束时间可用 now\n"
                "示例: /bugfix 123456 2024/12/01/09:00 now",
            )
            return

        target_qqs: list[int] = []
        time_args = args[-2:]
        qq_args = args[:-2]

        try:
            for arg in qq_args:
                target_qqs.append(int(arg))
        except ValueError:
            await self.sender.send_group_message(
                group_id, "❌ QQ 号格式错误，必须为数字"
            )
            return

        if not target_qqs:
            await self.sender.send_group_message(group_id, "❌ 请至少指定一个目标 QQ")
            return

        try:
            start_date = datetime.strptime(time_args[0], "%Y/%m/%d/%H:%M")
            if time_args[1].lower() == "now":
                end_date = datetime.now()
                end_date_str = "now"
            else:
                end_date = datetime.strptime(time_args[1], "%Y/%m/%d/%H:%M")
                end_date_str = time_args[1]
        except ValueError:
            await self.sender.send_group_message(
                group_id,
                "❌ 时间格式错误，请使用 YYYY/MM/DD/HH:MM 格式\n示例: 2024/12/01/09:00",
            )
            return

        targets_str = ", ".join(map(str, target_qqs))
        await self.sender.send_group_message(
            group_id,
            f"🔍 正在获取与 {targets_str} 在 {time_args[0]} ~ {end_date_str} 的对话记录...",
        )

        try:
            messages = await self._fetch_messages(
                group_id, target_qqs, start_date, end_date
            )
        except Exception as e:
            logger.exception(f"获取消息历史失败: {e}")
            await self.sender.send_group_message(group_id, f"❌ 获取消息历史失败: {e}")
            return

        if not messages:
            await self.sender.send_group_message(
                group_id, "❌ 未找到符合条件的对话记录"
            )
            return

        logger.info(f"找到 {len(messages)} 条消息，正在处理...")

        processed_text = await self._process_messages(messages)

        total_tokens = self.ai.count_tokens(processed_text)
        max_tokens = self.config.chat_model.max_tokens

        if total_tokens <= max_tokens:
            summary = await self.ai.summarize_chat(processed_text)
        else:
            await self.sender.send_group_message(
                group_id, f"📊 消息较长（{total_tokens} tokens），正在分段处理..."
            )

            chunks = self.ai.split_messages_by_tokens(processed_text, max_tokens)
            summaries: list[str] = []

            for i, chunk in enumerate(chunks):
                logger.info(f"处理分段 {i + 1}/{len(chunks)}...")
                chunk_summary = await self.ai.summarize_chat(chunk)
                summaries.append(chunk_summary)

            summary = await self.ai.merge_summaries(summaries)

        title = extract_faq_title(summary)
        if not title or title == "未命名问题":
            logger.info("无法提取标题，尝试使用 AI 生成...")
            title = await self.ai.generate_title(summary)

        faq = self.faq_storage.create(
            group_id=group_id,
            target_qq=target_qqs[0],
            start_time=time_args[0],
            end_time=end_date_str,
            title=title,
            content=summary,
        )

        result_message = f"""✅ Bug 修复分析完成！

📌 FAQ ID: {faq.id}
📋 标题: {title}

{summary}

💡 使用 /viewfaq {faq.id} 可以再次查看此 FAQ"""

        await self.sender.send_group_message(group_id, result_message)

    async def _fetch_messages(
        self,
        group_id: int,
        target_qqs: list[int],
        start_date: datetime,
        end_date: datetime,
    ) -> list[dict[str, Any]]:
        """获取指定时间段内与目标用户的对话"""
        all_messages: list[dict[str, Any]] = []

        logger.info(
            f"开始获取消息历史: group={group_id}, targets={target_qqs}, "
            f"start={start_date}, end={end_date}"
        )

        try:
            batch = await self.onebot.get_group_msg_history(
                group_id,
                count=2500,
            )
        except RuntimeError as e:
            logger.error(f"获取历史消息失败: {e}")
            raise

        if not batch:
            logger.info("没有获取到任何消息")
            return []

        first_time = parse_message_time(batch[0])
        last_time = parse_message_time(batch[-1])
        logger.info(f"获取到 {len(batch)} 条消息, 时间范围: {last_time} ~ {first_time}")

        for msg in batch:
            msg_time = parse_message_time(msg)
            sender_id = get_message_sender_id(msg)

            if msg_time < start_date:
                continue

            if msg_time > end_date:
                continue

            if sender_id in target_qqs:
                all_messages.append(msg)

        logger.info(f"共获取到 {len(all_messages)} 条符合条件的消息")

        all_messages.sort(key=lambda m: m.get("time", 0))
        return all_messages

    async def _process_messages(self, messages: list[dict[str, Any]]) -> str:
        """处理消息列表，将图片转换为文字描述"""
        lines: list[str] = []

        for msg in messages:
            sender_id = get_message_sender_id(msg)
            msg_time = parse_message_time(msg)
            content = get_message_content(msg)

            time_str = msg_time.strftime("%Y-%m-%d %H:%M:%S")
            text_parts: list[str] = []

            for segment in content:
                seg_type = segment.get("type", "")
                seg_data = segment.get("data", {})

                if seg_type == "text":
                    text_parts.append(seg_data.get("text", ""))

                elif seg_type == "image":
                    file = seg_data.get("file", "") or seg_data.get("url", "")
                    if file:
                        try:
                            image_url = await self.onebot.get_image(file)
                            if image_url:
                                result = await self.ai.analyze_multimodal(
                                    image_url, "image"
                                )
                                desc = result.get("description", "")
                                ocr = result.get("ocr_text", "")
                                text_parts.append(
                                    f"[pic]<desc>{desc}</desc><text>{ocr}</text>[/pic]"
                                )
                            else:
                                text_parts.append(
                                    "[pic]<desc>图片加载失败</desc>[/pic]"
                                )
                        except Exception as e:
                            logger.error(f"处理图片失败: {e}")
                            text_parts.append("[pic]<desc>图片处理失败</desc>[/pic]")

                elif seg_type == "at":
                    qq = seg_data.get("qq", "")
                    text_parts.append(f"@{qq}")

                elif seg_type == "face":
                    text_parts.append("[表情]")

                elif seg_type == "reply":
                    text_parts.append("[回复]")

            if text_parts:
                message_text = "".join(text_parts)
                lines.append(f"[{time_str}] {sender_id}: {message_text}")

        return "\n".join(lines)

    async def close(self) -> None:
        """关闭消息处理器，取消队列处理任务"""
        logger.info("正在关闭消息处理器...")
        if self._queue_processor_task and not self._queue_processor_task.done():
            self._queue_processor_task.cancel()
            try:
                await self._queue_processor_task
            except asyncio.CancelledError:
                logger.info("队列处理任务已取消")
        logger.info("消息处理器已关闭")
