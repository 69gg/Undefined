"""消息处理和命令分发"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
import os
from pathlib import Path
import random
import time
from typing import Any, Coroutine

from Undefined.attachments import (
    append_attachment_text,
    build_attachment_scope,
    register_message_attachments,
)
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
from Undefined.utils.fake_at import BotNicknameCache, strip_fake_at
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
from Undefined.utils.coerce import safe_int

logger = logging.getLogger(__name__)

KEYWORD_REPLY_HISTORY_PREFIX = "[系统关键词自动回复] "
REPEAT_REPLY_HISTORY_PREFIX = "[系统复读] "


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
    sender_level: str


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
            history_manager=self.history_manager,
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

        self._background_tasks: set[asyncio.Task[None]] = set()
        self._profile_name_refresh_cache: dict[tuple[str, int], str] = {}
        self._bot_nickname_cache = BotNicknameCache(onebot, config.bot_qq)

        # 复读功能状态（按群跟踪最近消息文本与发送者）
        self._repeat_counter: dict[int, list[tuple[str, int]]] = {}
        self._repeat_locks: dict[int, asyncio.Lock] = {}
        # 复读冷却：group_id → {normalized_text → monotonic_timestamp}
        self._repeat_cooldown: dict[int, dict[str, float]] = {}

        # 启动队列
        self.ai_coordinator.queue_manager.start(self.ai_coordinator.execute_reply)

    def _get_repeat_lock(self, group_id: int) -> asyncio.Lock:
        """获取或创建指定群的复读竞态保护锁。"""
        lock = self._repeat_locks.get(group_id)
        if lock is None:
            lock = asyncio.Lock()
            self._repeat_locks[group_id] = lock
        return lock

    @staticmethod
    def _normalize_repeat_text(text: str) -> str:
        """规范化复读文本用于冷却比较（？→?）。"""
        return text.replace("？", "?")

    def _is_repeat_on_cooldown(self, group_id: int, text: str) -> bool:
        """检查指定群的文本是否在复读冷却期内。"""
        cooldown_minutes = self.config.repeat_cooldown_minutes
        if cooldown_minutes <= 0:
            return False
        group_cd = self._repeat_cooldown.get(group_id)
        if not group_cd:
            return False
        key = self._normalize_repeat_text(text)
        last_time = group_cd.get(key)
        if last_time is None:
            return False
        return (time.monotonic() - last_time) < cooldown_minutes * 60

    def _record_repeat_cooldown(self, group_id: int, text: str) -> None:
        """记录复读冷却时间戳。"""
        key = self._normalize_repeat_text(text)
        group_cd = self._repeat_cooldown.setdefault(group_id, {})
        group_cd[key] = time.monotonic()

    async def _annotate_meme_descriptions(
        self,
        attachments: list[dict[str, str]],
        scope_key: str,
    ) -> list[dict[str, str]]:
        """为图片附件添加表情包描述（如果在表情库中找到）。

        采用批量查询：收集所有 SHA256 哈希值，一次性查询，然后映射结果。
        最佳努力：任何失败时返回原始列表。
        """
        if not attachments:
            return attachments

        ai_client = getattr(self, "ai", None)
        if ai_client is None:
            return attachments

        attachment_registry = getattr(ai_client, "attachment_registry", None)
        if attachment_registry is None:
            return attachments

        meme_service = getattr(ai_client, "_meme_service", None)
        if meme_service is None or not getattr(meme_service, "enabled", False):
            return attachments

        meme_store = getattr(meme_service, "_store", None)
        if meme_store is None:
            return attachments

        try:
            # 1. 从图片附件收集唯一的 SHA256 哈希值
            uid_to_hash: dict[str, str] = {}
            for att in attachments:
                uid = att.get("uid", "")
                if not uid.startswith("pic_"):
                    continue
                record = attachment_registry.resolve(uid, scope_key)
                if record and record.sha256:
                    uid_to_hash[uid] = record.sha256

            if not uid_to_hash:
                return attachments

            # 2. 批量查询：去重哈希值
            unique_hashes = set(uid_to_hash.values())
            hash_to_desc: dict[str, str] = {}
            for h in unique_hashes:
                meme = await meme_store.find_by_sha256(h)
                if meme and meme.description:
                    hash_to_desc[h] = meme.description

            if not hash_to_desc:
                return attachments

            # 3. 构建带注释的新列表
            result: list[dict[str, str]] = []
            for att in attachments:
                uid = att.get("uid", "")
                sha = uid_to_hash.get(uid, "")
                desc = hash_to_desc.get(sha, "")
                if desc:
                    new_att = dict(att)
                    new_att["description"] = f"[表情包] {desc}"
                    result.append(new_att)
                else:
                    result.append(att)
            return result
        except Exception:
            logger.warning("表情包自动匹配失败，跳过", exc_info=True)
            return attachments

    async def _collect_message_attachments(
        self,
        message_content: list[dict[str, Any]],
        *,
        group_id: int | None = None,
        user_id: int | None = None,
        request_type: str,
    ) -> list[dict[str, str]]:
        scope_key = build_attachment_scope(
            group_id=group_id,
            user_id=user_id,
            request_type=request_type,
        )
        if not scope_key:
            return []
        ai_client = getattr(self, "ai", None)
        attachment_registry = (
            getattr(ai_client, "attachment_registry", None) if ai_client else None
        )
        if attachment_registry is None:
            return []
        onebot = getattr(self, "onebot", None)
        resolve_image_url = getattr(onebot, "get_image", None) if onebot else None
        result = await register_message_attachments(
            registry=attachment_registry,
            segments=message_content,
            scope_key=scope_key,
            resolve_image_url=resolve_image_url,
            get_forward_messages=getattr(onebot, "get_forward_msg", None)
            if onebot
            else None,
        )
        attachments = result.attachments
        # 为图片附件添加表情包描述
        attachments = await self._annotate_meme_descriptions(attachments, scope_key)
        return attachments

    def _schedule_meme_ingest(
        self,
        *,
        attachments: list[dict[str, str]],
        chat_type: str,
        chat_id: int,
        sender_id: int,
        message_id: int | None,
        scope_key: str | None,
    ) -> None:
        if not attachments or not scope_key:
            return
        meme_service = getattr(self.ai, "_meme_service", None)
        if meme_service is None or not getattr(meme_service, "enabled", False):
            return
        self._spawn_background_task(
            f"meme_ingest:{chat_type}:{chat_id}:{sender_id}:{message_id or 0}",
            meme_service.enqueue_incoming_attachments(
                attachments=attachments,
                chat_type=chat_type,
                chat_id=chat_id,
                sender_id=sender_id,
                message_id=message_id,
                scope_key=scope_key,
            ),
        )

    async def _refresh_profile_display_names(
        self,
        *,
        sender_id: int | None = None,
        sender_name: str = "",
        group_id: int | None = None,
        group_name: str = "",
    ) -> None:
        ai_client = getattr(self, "ai", None)
        cognitive_service = getattr(ai_client, "_cognitive_service", None)
        if not cognitive_service or not getattr(cognitive_service, "enabled", False):
            return

        if sender_id and sender_name.strip():
            await cognitive_service.sync_profile_display_name(
                entity_type="user",
                entity_id=str(sender_id),
                preferred_name=sender_name.strip(),
            )
        if group_id and group_name.strip():
            await cognitive_service.sync_profile_display_name(
                entity_type="group",
                entity_id=str(group_id),
                preferred_name=group_name.strip(),
            )

    def _can_refresh_profile_display_names(self) -> bool:
        ai_client = getattr(self, "ai", None)
        cognitive_service = getattr(ai_client, "_cognitive_service", None)
        return bool(cognitive_service and getattr(cognitive_service, "enabled", False))

    def _schedule_profile_display_name_refresh(
        self,
        *,
        task_name: str,
        sender_id: int | None = None,
        sender_name: str = "",
        group_id: int | None = None,
        group_name: str = "",
    ) -> None:
        if not self._can_refresh_profile_display_names():
            return

        cache = getattr(self, "_profile_name_refresh_cache", None)
        if cache is None:
            cache = {}
            self._profile_name_refresh_cache = cache

        updates: dict[str, Any] = {}
        rollback: list[tuple[tuple[str, int], str | None]] = []

        normalized_sender_name = sender_name.strip()
        if sender_id and normalized_sender_name:
            sender_key = ("user", int(sender_id))
            previous = cache.get(sender_key)
            if previous != normalized_sender_name:
                cache[sender_key] = normalized_sender_name
                rollback.append((sender_key, previous))
                updates["sender_id"] = sender_id
                updates["sender_name"] = normalized_sender_name

        normalized_group_name = group_name.strip()
        if group_id and normalized_group_name:
            group_key = ("group", int(group_id))
            previous = cache.get(group_key)
            if previous != normalized_group_name:
                cache[group_key] = normalized_group_name
                rollback.append((group_key, previous))
                updates["group_id"] = group_id
                updates["group_name"] = normalized_group_name

        if not updates:
            return

        async def _run_refresh() -> None:
            try:
                await self._refresh_profile_display_names(**updates)
            except Exception:
                for key, previous in rollback:
                    if previous is None:
                        cache.pop(key, None)
                    else:
                        cache[key] = previous
                raise

        self._spawn_background_task(task_name, _run_refresh())

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

            # 访问控制：命中群黑名单或不满足白名单限制时忽略
            if poke_group_id == 0:
                if not self.config.is_private_allowed(poke_sender_id):
                    private_reason = (
                        self.config.private_access_denied_reason(poke_sender_id)
                        or "unknown"
                    )
                    logger.debug(
                        "[访问控制] 忽略私聊拍一拍: user=%s reason=%s (access enabled=%s)",
                        poke_sender_id,
                        private_reason,
                        self.config.access_control_enabled(),
                    )
                    return
            else:
                if not self.config.is_group_allowed(poke_group_id):
                    group_reason = (
                        self.config.group_access_denied_reason(poke_group_id)
                        or "unknown"
                    )
                    logger.debug(
                        "[访问控制] 忽略群聊拍一拍: group=%s sender=%s reason=%s (access enabled=%s)",
                        poke_group_id,
                        poke_sender_id,
                        group_reason,
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
                    sender_level=group_poke.sender_level,
                )
            return

        # 处理私聊消息
        if event.get("message_type") == "private":
            private_sender_id: int = get_message_sender_id(event)
            private_message_content: list[dict[str, Any]] = get_message_content(event)
            trigger_message_id = event.get("message_id")

            # 访问控制：命中黑/白名单规则时忽略（不入历史、不触发任何处理）
            if not self.config.is_private_allowed(private_sender_id):
                private_reason = (
                    self.config.private_access_denied_reason(private_sender_id)
                    or "unknown"
                )
                logger.debug(
                    "[访问控制] 忽略私聊消息: user=%s reason=%s (access enabled=%s)",
                    private_sender_id,
                    private_reason,
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
            # 并行执行附件收集和历史内容解析
            private_attachments, parsed_content_raw = await asyncio.gather(
                self._collect_message_attachments(
                    private_message_content,
                    user_id=private_sender_id,
                    request_type="private",
                ),
                parse_message_content_for_history(
                    private_message_content,
                    self.config.bot_qq,
                    self.onebot.get_msg,
                    self.onebot.get_forward_msg,
                ),
            )
            safe_text = redact_string(text)
            logger.info(
                "[私聊消息] 发送者=%s 昵称=%s 内容=%s",
                private_sender_id,
                user_name or private_sender_nickname,
                safe_text[:100],
            )
            resolved_private_name = (user_name or private_sender_nickname or "").strip()
            self._schedule_profile_display_name_refresh(
                task_name=f"profile_name_refresh_private:{private_sender_id}",
                sender_id=private_sender_id,
                sender_name=resolved_private_name,
            )

            # 保存私聊消息到历史记录
            parsed_content = append_attachment_text(
                parsed_content_raw, private_attachments
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
                message_id=trigger_message_id,
                attachments=private_attachments,
            )

            # 如果是 bot 自己的消息，只保存不触发回复，避免无限循环
            if private_sender_id == self.config.bot_qq:
                return

            self._schedule_meme_ingest(
                attachments=private_attachments,
                chat_type="private",
                chat_id=private_sender_id,
                sender_id=private_sender_id,
                message_id=safe_int(trigger_message_id),
                scope_key=build_attachment_scope(
                    user_id=private_sender_id,
                    request_type="private",
                ),
            )

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
                        self._spawn_background_task(
                            "bilibili_auto_extract_private",
                            self._handle_bilibili_extract(
                                private_sender_id, bvids, "private"
                            ),
                        )
                        return

            # arXiv 论文自动提取（私聊）
            if self.config.arxiv_auto_extract_enabled:
                if self.config.is_arxiv_auto_extract_allowed_private(private_sender_id):
                    paper_ids = self._extract_arxiv_ids(text, private_message_content)
                    if paper_ids:
                        self._spawn_background_task(
                            "arxiv_auto_extract_private",
                            self._handle_arxiv_extract(
                                private_sender_id, paper_ids, "private"
                            ),
                        )
                        return

            # 私聊消息直接触发回复
            if await self.ai_coordinator.model_pool.handle_private_message(
                private_sender_id, text
            ):
                return

            private_command = self.command_dispatcher.parse_command(text)
            if private_command:
                await self.command_dispatcher.dispatch_private(
                    user_id=private_sender_id,
                    sender_id=private_sender_id,
                    command=private_command,
                )
                return

            await self.ai_coordinator.handle_private_reply(
                private_sender_id,
                text,
                private_message_content,
                attachments=private_attachments,
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

        # 访问控制：命中黑/白名单规则时忽略（不入历史、不触发任何处理）
        if not self.config.is_group_allowed(group_id):
            group_reason = self.config.group_access_denied_reason(group_id) or "unknown"
            logger.debug(
                "[访问控制] 忽略群消息: group=%s sender=%s reason=%s (access enabled=%s)",
                group_id,
                sender_id,
                group_reason,
                self.config.access_control_enabled(),
            )
            return

        # 获取发送者信息
        group_sender: dict[str, Any] = event.get("sender", {})
        sender_card: str = group_sender.get("card", "")
        sender_nickname: str = group_sender.get("nickname", "")
        sender_role: str = group_sender.get("role", "member")
        sender_title: str = group_sender.get("title", "")
        sender_level: str = str(group_sender.get("level", "")).strip()

        # 提取文本内容
        text = extract_text(message_content, self.config.bot_qq)
        safe_text = redact_string(text)
        logger.info(
            f"[群消息] group={group_id} sender={sender_id} name={sender_card or sender_nickname} "
            f"role={sender_role} | {safe_text[:100]}"
        )

        # 并行执行 3 个独立的异步操作：附件收集、群信息获取、历史内容解析
        async def _fetch_group_name() -> str:
            try:
                info = await self.onebot.get_group_info(group_id)
                if info:
                    return str(info.get("group_name", "") or "")
            except Exception as e:
                logger.warning(f"获取群聊名失败: {e}")
            return ""

        group_attachments, group_name, parsed_content_raw = await asyncio.gather(
            self._collect_message_attachments(
                message_content,
                group_id=group_id,
                request_type="group",
            ),
            _fetch_group_name(),
            parse_message_content_for_history(
                message_content,
                self.config.bot_qq,
                self.onebot.get_msg,
                self.onebot.get_forward_msg,
            ),
        )

        resolved_group_sender_name = (sender_card or sender_nickname or "").strip()
        self._schedule_profile_display_name_refresh(
            task_name=f"profile_name_refresh_group:{group_id}:{sender_id}",
            sender_id=sender_id,
            sender_name=resolved_group_sender_name,
            group_id=group_id,
            group_name=str(group_name or "").strip(),
        )

        # 保存消息到历史记录
        parsed_content = append_attachment_text(parsed_content_raw, group_attachments)
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
            level=sender_level,
            message_id=trigger_message_id,
            attachments=group_attachments,
        )

        # 如果是 bot 自己的消息，只保存不触发回复，避免无限循环
        # 同时把 bot 自身的发言写入复读计数器，使窗口中留有 bot 标记，
        # 后续触发检查时会排除含 bot 的窗口，防止"bot 先发 → 用户跟发"或
        # "用户发到一半 bot 插入"等情况误触复读。
        if sender_id == self.config.bot_qq:
            if self.config.repeat_enabled and text:
                async with self._get_repeat_lock(group_id):
                    counter = self._repeat_counter.setdefault(group_id, [])
                    counter.append((text, sender_id))
                    n = self.config.repeat_threshold
                    if len(counter) > n:
                        self._repeat_counter[group_id] = counter[-n:]
            return

        self._schedule_meme_ingest(
            attachments=group_attachments,
            chat_type="group",
            chat_id=group_id,
            sender_id=sender_id,
            message_id=safe_int(trigger_message_id),
            scope_key=build_attachment_scope(group_id=group_id, request_type="group"),
        )

        # 检查是否 @ 了机器人（后续分流共用）
        is_at_bot = self.ai_coordinator._is_at_bot(message_content)

        # 假@检测：识别 "@昵称" 纯文本形式
        # normalized_text 用于命令解析和 AI 路由，原始 text 已用于历史/日志
        is_fake_at = False
        normalized_text = text
        if not is_at_bot:
            nicknames = await self._bot_nickname_cache.get_nicknames(group_id)
            if nicknames:
                is_fake_at, normalized_text = strip_fake_at(text, nicknames)
                if is_fake_at:
                    is_at_bot = True
                    logger.info(
                        "[假@] 识别到假@: group=%s sender=%s",
                        group_id,
                        sender_id,
                    )

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
                    image_path = (
                        resolve_resource_path("img/xlwy.jpg").resolve().as_uri()
                    )
                except Exception:
                    image_path = Path(os.path.abspath("img/xlwy.jpg")).as_uri()
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

        # 复读功能：连续 N 条相同消息（来自不同发送者）时复读，N = repeat_threshold
        if self.config.repeat_enabled and text:
            n = self.config.repeat_threshold
            async with self._get_repeat_lock(group_id):
                counter = self._repeat_counter.setdefault(group_id, [])
                counter.append((text, sender_id))
                # 只保留最近 n 条
                if len(counter) > n:
                    self._repeat_counter[group_id] = counter[-n:]
                    counter = self._repeat_counter[group_id]

                if len(counter) >= n:
                    last_n = counter[-n:]
                    texts = [t for t, _ in last_n]
                    senders = [s for _, s in last_n]
                    if (
                        len(set(texts)) == 1
                        and len(set(senders)) == n
                        and self.config.bot_qq not in senders
                    ):
                        reply_text = texts[0]
                        # 冷却检查：同一内容在冷却期内不再复读
                        if self._is_repeat_on_cooldown(group_id, reply_text):
                            self._repeat_counter[group_id] = []
                            logger.debug(
                                "[复读] 冷却中跳过: group=%s text=%s",
                                group_id,
                                redact_string(reply_text)[:50],
                            )
                        else:
                            if self.config.inverted_question_enabled:
                                stripped = reply_text.strip()
                                if set(stripped) <= {"?", "？"}:
                                    reply_text = "¿" * len(stripped)
                            # 清空计数器防止重复触发
                            self._repeat_counter[group_id] = []
                            self._record_repeat_cooldown(group_id, texts[0])
                            logger.info(
                                "[复读] 触发复读: group=%s text=%s",
                                group_id,
                                redact_string(reply_text)[:50],
                            )
                            await self.sender.send_group_message(
                                group_id,
                                reply_text,
                                history_prefix=REPEAT_REPLY_HISTORY_PREFIX,
                            )
                            return

        # Bilibili 视频自动提取
        if self.config.bilibili_auto_extract_enabled:
            if self.config.is_bilibili_auto_extract_allowed_group(group_id):
                bvids = await self._extract_bilibili_ids(text, message_content)
                if bvids:
                    self._spawn_background_task(
                        "bilibili_auto_extract_group",
                        self._handle_bilibili_extract(group_id, bvids, "group"),
                    )
                    return

        # arXiv 论文自动提取
        if self.config.arxiv_auto_extract_enabled:
            if self.config.is_arxiv_auto_extract_allowed_group(group_id):
                paper_ids = self._extract_arxiv_ids(text, message_content)
                if paper_ids:
                    self._spawn_background_task(
                        "arxiv_auto_extract_group",
                        self._handle_arxiv_extract(group_id, paper_ids, "group"),
                    )
                    return

        # 提取文本内容
        # (已在上方提取用于日志记录)

        # 只有被@时才处理斜杠命令（使用 normalized_text 以支持假@后的命令）
        if is_at_bot:
            command = self.command_dispatcher.parse_command(normalized_text)
            if command:
                await self.command_dispatcher.dispatch(group_id, sender_id, command)
                return

        # 自动回复处理（使用 normalized_text 以去除假@前缀）
        display_name = sender_card or sender_nickname or str(sender_id)
        await self.ai_coordinator.handle_auto_reply(
            group_id,
            sender_id,
            normalized_text,
            message_content,
            attachments=group_attachments,
            sender_name=display_name,
            group_name=group_name,
            sender_role=sender_role,
            sender_title=sender_title,
            sender_level=sender_level,
            trigger_message_id=trigger_message_id,
            is_fake_at=is_fake_at,
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

        resolved_sender_name = (sender_nickname or user_name).strip()
        display_name = resolved_sender_name or f"QQ{user_id}"
        normalized_user_name = user_name or display_name
        poke_text = _format_poke_history_text(display_name, user_id)
        self._schedule_profile_display_name_refresh(
            task_name=f"profile_name_refresh_private_poke:{user_id}",
            sender_id=user_id,
            sender_name=resolved_sender_name,
        )

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
        sender_level = ""
        if isinstance(sender, dict):
            sender_card = str(sender.get("card", "")).strip()
            sender_nickname = str(sender.get("nickname", "")).strip()
            sender_role = str(sender.get("role", "member")).strip() or "member"
            sender_title = str(sender.get("title", "")).strip()
            sender_level = str(sender.get("level", "")).strip()

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
                    sender_level = str(member_info.get("level", "")).strip()
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

        resolved_sender_name = (sender_card or sender_nickname).strip()
        resolved_group_name = group_name.strip()
        display_name = resolved_sender_name or f"QQ{sender_id}"
        poke_text = _format_poke_history_text(display_name, sender_id)
        normalized_group_name = resolved_group_name or f"群{group_id}"
        self._schedule_profile_display_name_refresh(
            task_name=f"profile_name_refresh_group_poke:{group_id}:{sender_id}",
            sender_id=sender_id,
            sender_name=resolved_sender_name,
            group_id=group_id,
            group_name=resolved_group_name,
        )

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
                level=sender_level,
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
            sender_level=sender_level,
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

    def _extract_arxiv_ids(
        self, text: str, message_content: list[dict[str, Any]]
    ) -> list[str]:
        """从文本和消息段中提取 arXiv 论文 ID。"""
        from Undefined.arxiv.parser import extract_arxiv_ids, extract_from_json_message

        paper_ids: list[str] = []
        seen: set[str] = set()

        for paper_id in extract_arxiv_ids(text):
            if paper_id in seen:
                continue
            seen.add(paper_id)
            paper_ids.append(paper_id)

        for paper_id in extract_from_json_message(message_content):
            if paper_id in seen:
                continue
            seen.add(paper_id)
            paper_ids.append(paper_id)

        return paper_ids

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

    async def _handle_arxiv_extract(
        self,
        target_id: int,
        paper_ids: list[str],
        target_type: str,
    ) -> None:
        """处理 arXiv 论文自动提取和发送。"""
        from Undefined.arxiv.sender import send_arxiv_paper

        max_items = max(1, int(self.config.arxiv_auto_extract_max_items))

        for paper_id in paper_ids[:max_items]:
            try:
                result = await send_arxiv_paper(
                    paper_id=paper_id,
                    sender=self.sender,
                    target_type=target_type,  # type: ignore[arg-type]
                    target_id=target_id,
                    max_file_size=self.config.arxiv_max_file_size,
                    author_preview_limit=self.config.arxiv_author_preview_limit,
                    summary_preview_chars=self.config.arxiv_summary_preview_chars,
                    context={
                        "request_id": (
                            f"arxiv_auto_extract:{target_type}:{target_id}:{paper_id}"
                        )
                    },
                )
                logger.info(
                    "[arXiv] 自动提取完成 %s → %s:%s: %s",
                    paper_id,
                    target_type,
                    target_id,
                    result,
                )
            except Exception:
                logger.exception(
                    "[arXiv] 自动提取失败 %s → %s:%s",
                    paper_id,
                    target_type,
                    target_id,
                )

    def _spawn_background_task(
        self,
        name: str,
        coroutine: Coroutine[Any, Any, None],
    ) -> None:
        task = asyncio.create_task(coroutine, name=name)
        self._background_tasks.add(task)

        def _finalize(done_task: asyncio.Task[None]) -> None:
            self._background_tasks.discard(done_task)
            try:
                exc = done_task.exception()
            except asyncio.CancelledError:
                logger.debug("[后台任务] 已取消: %s", name)
                return
            if exc is not None:
                logger.exception(
                    "[后台任务] 执行失败: name=%s",
                    name,
                    exc_info=(type(exc), exc, exc.__traceback__),
                )

        task.add_done_callback(_finalize)

    async def close(self) -> None:
        """关闭消息处理器"""
        logger.info("正在关闭消息处理器...")
        if self._background_tasks:
            logger.info(
                "[后台任务] 等待自动提取任务收敛: count=%s",
                len(self._background_tasks),
            )
            await asyncio.gather(
                *list(self._background_tasks),
                return_exceptions=True,
            )
        await self.ai_coordinator.queue_manager.stop()
        logger.info("消息处理器已关闭")
