"""消息主流程与 ``MessageHandler`` 核心实现。

协调私聊/群聊事件分发、附件收集、管线与 AI 回复；拍一拍、复读、自动提取由 mixin 提供。
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
import random
from typing import Any, Coroutine, Literal

import Undefined.handlers as handlers_module
from Undefined.attachments import (
    append_attachment_text,
    build_attachment_scope,
    register_message_attachments,
)
from Undefined.attachments.models import RegisteredMessageAttachments
from Undefined.attachments.segments import normalize_message_segments
from Undefined.ai import AIClient
from Undefined.config import Config
from Undefined.faq import FAQStorage
from Undefined.handlers.auto_extract import AutoExtractMixin
from Undefined.handlers.poke import PokeMixin
from Undefined.handlers.repeat import RepeatMixin
from Undefined.onebot import (
    OneBotClient,
    get_message_content,
    get_message_sender_id,
)
from Undefined.rate_limit import RateLimiter
from Undefined.scheduled_task_storage import ScheduledTaskStorage
from Undefined.services.coordinator import AICoordinator
from Undefined.services.command import CommandDispatcher
from Undefined.services.message_batcher import MessageBatcher, make_scope
from Undefined.services.model_pool import ModelPoolService
from Undefined.services.queue_manager import QueueManager
from Undefined.services.security import SecurityService
from Undefined.skills.pipelines import PipelineRegistry
from Undefined.skills.pipelines.context import build_pipeline_context
from Undefined.utils.coerce import safe_int
from Undefined.utils.fake_at import BotNicknameCache, strip_fake_at
from Undefined.utils.history import MessageHistoryManager
from Undefined.utils.logging import log_debug_json, redact_string
from Undefined.utils.queue_intervals import build_model_queue_intervals
from Undefined.utils.resources import resolve_resource_path
from Undefined.utils.scheduler import TaskScheduler
from Undefined.utils.sender import MessageSender
from Undefined.utils.sender import AddressBoundSender
from Undefined.utils.message_targets import DeliveryAddress

logger = logging.getLogger(__name__)

KEYWORD_REPLY_HISTORY_PREFIX = "[系统关键词自动回复] "
FORWARD_MEME_SCAN_MAX_DEPTH = 3
FORWARD_MEME_SCAN_MAX_NODES = 50


def _is_private_model_pool_control_text(text: str) -> bool:
    return bool(ModelPoolService.is_private_control_text(text))


def _coerce_registered_attachments(value: Any) -> RegisteredMessageAttachments:
    """兼容测试替身：将旧的附件列表返回值转为注册结果对象。"""
    if isinstance(value, RegisteredMessageAttachments):
        return value
    if isinstance(value, list):
        return RegisteredMessageAttachments(
            attachments=[item for item in value if isinstance(item, dict)],
            normalized_text="",
            forward_refs=[],
        )
    return RegisteredMessageAttachments(
        attachments=[],
        normalized_text="",
        forward_refs=[],
    )


def _extract_forward_id_from_segment(segment: dict[str, Any]) -> str:
    raw_data = segment.get("data", {})
    data = raw_data if isinstance(raw_data, dict) else {}
    forward_id = data.get("id") or data.get("resid") or data.get("message_id")
    return str(forward_id).strip() if forward_id is not None else ""


class MessageHandler(PokeMixin, RepeatMixin, AutoExtractMixin):
    """消息处理器。

    接收 OneBot 事件、写入历史并协调命令分发、自动管线与 AI 回复；
    依赖 ``AICoordinator``、``CommandDispatcher`` 与 ``MessageBatcher``。
    """

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
        self.history_manager = MessageHistoryManager(config.history_max_records)
        self.sender = MessageSender(
            onebot,
            self.history_manager,
            config.bot_qq,
            config,
            attachment_registry=getattr(ai, "attachment_registry", None),
        )

        self.security = SecurityService(config, ai._http_client)
        self.rate_limiter = RateLimiter(config)
        self.queue_manager = QueueManager(
            max_retries=config.ai_request_max_retries,
        )
        self.queue_manager.update_model_intervals(build_model_queue_intervals(config))

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

        self.message_batcher = MessageBatcher(
            config.message_batcher,
            flush_callback=self.ai_coordinator.handle_batched_dispatch,
        )
        self.ai_coordinator.set_batcher(self.message_batcher)

        self._background_tasks: set[asyncio.Task[None]] = set()
        self._profile_name_refresh_cache: dict[tuple[str, int], str] = {}
        self._bot_nickname_cache = BotNicknameCache(onebot, config.bot_qq)
        self.pipeline_registry = PipelineRegistry()
        self._pipelines_initialized = False
        self._pipelines_init_lock = asyncio.Lock()

        self._repeat_counter: dict[
            int, list[tuple[str, int, tuple[tuple[str, str], ...]]]
        ] = {}
        self._repeat_locks: dict[int, asyncio.Lock] = {}
        self._repeat_cooldown: dict[int, dict[str, float]] = {}

        self.ai_coordinator.queue_manager.start(self.ai_coordinator.execute_reply)

    async def initialize(self) -> None:
        """完成需要事件循环承载的异步初始化。"""
        await self.init_pipelines()

    async def init_pipelines(self) -> None:
        """异步加载自动处理管线并按配置启动热重载。"""
        if getattr(self, "_pipelines_initialized", False):
            return
        init_lock = getattr(self, "_pipelines_init_lock", None)
        if init_lock is None:
            init_lock = asyncio.Lock()
            self._pipelines_init_lock = init_lock
        async with init_lock:
            if getattr(self, "_pipelines_initialized", False):
                return
            await self.pipeline_registry.load_items_async()
            self._pipelines_initialized = True
            if getattr(self.config, "skills_hot_reload", False):
                self.pipeline_registry.start_hot_reload(
                    interval=self.config.skills_hot_reload_interval,
                    debounce=self.config.skills_hot_reload_debounce,
                )

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
            # 仅 pic_ 前缀图片参与表情库匹配
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

            unique_hashes = set(uid_to_hash.values())
            hash_to_desc: dict[str, str] = {}
            for h in unique_hashes:
                meme = await meme_store.find_by_sha256(h)
                if meme and meme.description:
                    hash_to_desc[h] = meme.description

            if not hash_to_desc:
                return attachments

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
    ) -> RegisteredMessageAttachments:
        scope_key = build_attachment_scope(
            group_id=group_id,
            user_id=user_id,
            request_type=request_type,
        )
        if not scope_key:
            return RegisteredMessageAttachments(
                attachments=[],
                normalized_text="",
                forward_refs=[],
            )
        ai_client = getattr(self, "ai", None)
        attachment_registry = (
            getattr(ai_client, "attachment_registry", None) if ai_client else None
        )
        if attachment_registry is None:
            return RegisteredMessageAttachments(
                attachments=[],
                normalized_text="",
                forward_refs=[],
            )
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
            register_forward_refs=True,
            expand_forward_attachments=False,
            snapshot_forward_messages=True,
        )
        attachments = result.attachments
        # 命中表情库时为 AI 上下文补充 [表情包] 描述
        attachments = await self._annotate_meme_descriptions(attachments, scope_key)
        return RegisteredMessageAttachments(
            attachments=attachments,
            normalized_text=result.normalized_text,
            forward_refs=result.forward_refs,
        )

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
        # 后台异步入库，不阻塞主消息处理
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

    def _schedule_forward_meme_scan(
        self,
        *,
        message_content: list[dict[str, Any]],
        chat_type: str,
        chat_id: int,
        sender_id: int,
        message_id: int | None,
        scope_key: str | None,
    ) -> None:
        if not scope_key:
            return
        if not any(
            str(seg.get("type", "")).lower() == "forward" for seg in message_content
        ):
            return
        meme_service = getattr(self.ai, "_meme_service", None)
        if meme_service is None or not getattr(meme_service, "enabled", False):
            return
        self._spawn_background_task(
            f"forward_meme_scan:{chat_type}:{chat_id}:{sender_id}:{message_id or 0}",
            self._scan_forward_memes_for_ingest(
                message_content=message_content,
                chat_type=chat_type,
                chat_id=chat_id,
                sender_id=sender_id,
                message_id=message_id,
                scope_key=scope_key,
            ),
        )

    async def _scan_forward_memes_for_ingest(
        self,
        *,
        message_content: list[dict[str, Any]],
        chat_type: str,
        chat_id: int,
        sender_id: int,
        message_id: int | None,
        scope_key: str,
    ) -> None:
        ai_client = getattr(self, "ai", None)
        attachment_registry = (
            getattr(ai_client, "attachment_registry", None) if ai_client else None
        )
        if attachment_registry is None:
            return
        onebot = getattr(self, "onebot", None)
        if onebot is None:
            return
        get_forward_messages = getattr(onebot, "get_forward_msg", None)
        if not callable(get_forward_messages):
            return

        collected: list[dict[str, str]] = []
        visited: set[str] = set()
        node_count = 0

        async def _walk(segments: list[dict[str, Any]], depth: int) -> None:
            nonlocal node_count
            if depth > FORWARD_MEME_SCAN_MAX_DEPTH:
                return
            if depth > 0:
                direct = await register_message_attachments(
                    registry=attachment_registry,
                    segments=segments,
                    scope_key=scope_key,
                    resolve_image_url=getattr(onebot, "get_image", None),
                    get_forward_messages=None,
                    register_forward_refs=False,
                    expand_forward_attachments=False,
                )
                collected.extend(direct.attachments)
            if depth >= FORWARD_MEME_SCAN_MAX_DEPTH:
                return
            for segment in segments:
                if str(segment.get("type", "")).strip().lower() != "forward":
                    continue
                forward_id = _extract_forward_id_from_segment(segment)
                if not forward_id or forward_id in visited:
                    continue
                visited.add(forward_id)
                try:
                    raw_nodes = await get_forward_messages(forward_id)
                except Exception:
                    logger.debug(
                        "[memes] 合并转发表情包扫描拉取失败: id=%s",
                        forward_id,
                        exc_info=True,
                    )
                    continue
                if isinstance(raw_nodes, dict):
                    nodes = raw_nodes.get("messages")
                else:
                    nodes = raw_nodes
                if not isinstance(nodes, list):
                    continue
                for node in nodes:
                    if node_count >= FORWARD_MEME_SCAN_MAX_NODES:
                        return
                    if not isinstance(node, dict):
                        continue
                    node_count += 1
                    raw_message = (
                        node.get("content")
                        or node.get("message")
                        or node.get("raw_message")
                    )
                    nested_segments = [
                        dict(item)
                        for item in normalize_message_segments(raw_message)
                        if isinstance(item, dict)
                    ]
                    if nested_segments:
                        await _walk(nested_segments, depth + 1)

        try:
            await _walk(message_content, 0)
            image_attachments = [
                item
                for item in collected
                if str(item.get("media_type") or item.get("kind") or "") == "image"
            ]
            if not image_attachments:
                return
            annotated = await self._annotate_meme_descriptions(
                image_attachments,
                scope_key,
            )
            self._schedule_meme_ingest(
                attachments=annotated,
                chat_type=chat_type,
                chat_id=chat_id,
                sender_id=sender_id,
                message_id=message_id,
                scope_key=scope_key,
            )
        except Exception:
            logger.warning("[memes] 合并转发表情包扫描失败", exc_info=True)

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
                # 刷新失败时回滚内存缓存，避免脏昵称长期生效
                for key, previous in rollback:
                    if previous is None:
                        cache.pop(key, None)
                    else:
                        cache[key] = previous
                raise

        self._spawn_background_task(task_name, _run_refresh())

    async def handle_message(self, event: dict[str, Any]) -> None:
        """处理收到的消息事件。"""
        if logger.isEnabledFor(logging.DEBUG):
            log_debug_json(logger, "[事件数据]", event)
        post_type = event.get("post_type", "message")

        # 拍一拍走 notice 旁路，不进入普通消息流水线
        if post_type == "notice" and event.get("notice_type") == "poke":
            await self._handle_poke_notice(event)
            return

        if event.get("message_type") == "private":
            await self._handle_private_message(event)
            return

        if event.get("message_type") != "group":
            return

        await self._handle_group_message(event)

    async def _handle_private_message(self, event: dict[str, Any]) -> None:
        """处理私聊消息事件。"""
        private_sender_id: int = get_message_sender_id(event)
        private_message_content: list[dict[str, Any]] = get_message_content(event)
        trigger_message_id = event.get("message_id")

        if not self.config.is_private_allowed(private_sender_id):
            private_reason = (
                self.config.private_access_denied_reason(private_sender_id) or "unknown"
            )
            logger.debug(
                "[访问控制] 忽略私聊消息: user=%s reason=%s (access enabled=%s)",
                private_sender_id,
                private_reason,
                self.config.access_control_enabled(),
            )
            return

        private_sender: dict[str, Any] = event.get("sender", {})
        private_sender_nickname: str = private_sender.get("nickname", "")

        user_name = private_sender_nickname
        if not user_name:
            try:
                user_info = await self.onebot.get_stranger_info(private_sender_id)
                if user_info:
                    user_name = user_info.get("nickname", "")
            except Exception as exc:
                logger.warning("获取用户昵称失败: %s", exc)

        text = handlers_module.extract_text(private_message_content, self.config.bot_qq)
        private_registered_raw, parsed_content_raw = await asyncio.gather(
            self._collect_message_attachments(
                private_message_content,
                user_id=private_sender_id,
                request_type="private",
            ),
            handlers_module.parse_message_content_for_history(
                private_message_content,
                self.config.bot_qq,
                self.onebot.get_msg,
                self.onebot.get_forward_msg,
            ),
        )
        private_registered = _coerce_registered_attachments(private_registered_raw)
        private_attachments = private_registered.attachments
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

        prompt_refs = private_attachments + private_registered.forward_refs
        ai_content_base = private_registered.normalized_text or parsed_content_raw
        parsed_content = append_attachment_text(parsed_content_raw, private_attachments)
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

        # 机器人自身消息只写历史，不触发后续自动回复/入库
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
        self._schedule_forward_meme_scan(
            message_content=private_message_content,
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

        # 多模型池控制指令优先于斜杠命令与 AI 回复
        if (
            getattr(self.config, "model_pool_enabled", False)
            and _is_private_model_pool_control_text(text)
        ) and await self.ai_coordinator.model_pool.handle_private_message(
            private_sender_id,
            text,
        ):
            return

        private_command = self.command_dispatcher.parse_command(text)
        if private_command:
            await self._flush_command_buffer(
                scope=make_scope(user_id=private_sender_id),
                sender_id=private_sender_id,
            )
            await self.command_dispatcher.dispatch_private(
                user_id=private_sender_id,
                sender_id=private_sender_id,
                command=private_command,
            )
            return

        await self._run_pipelines(
            target_id=private_sender_id,
            target_type="private",
            text=text,
            message_content=private_message_content,
        )

        await self.ai_coordinator.handle_private_reply(
            private_sender_id,
            ai_content_base,
            private_message_content,
            attachments=prompt_refs,
            sender_name=user_name,
            trigger_message_id=trigger_message_id,
        )

    async def handle_weixin_private_message(
        self,
        *,
        qq_id: int,
        text: str,
        message_content: list[dict[str, Any]],
        attachments: list[dict[str, str]],
        sender_name: str,
        message_id: str | None,
        account_alias: str,
    ) -> None:
        """处理已完成绑定校验的微信私聊消息。"""
        if not self.config.is_private_allowed(qq_id):
            return
        address = DeliveryAddress("wechat", qq_id)
        route_sender = AddressBoundSender(self.sender, address)
        parsed_content = append_attachment_text(text, attachments)
        logger.info(
            "[微信私聊] 逻辑QQ=%s 帐号=%s 内容=%s",
            qq_id,
            account_alias,
            redact_string(text)[:100],
        )
        await self.history_manager.add_private_message(
            user_id=qq_id,
            text_content=parsed_content,
            display_name=sender_name,
            user_name=sender_name,
            message_id=message_id,
            attachments=attachments,
            transport={
                "channel": "wechat",
                "address": address.canonical,
                "account_alias": account_alias,
            },
        )
        self._schedule_meme_ingest(
            attachments=attachments,
            chat_type="private",
            chat_id=qq_id,
            sender_id=qq_id,
            message_id=None,
            scope_key=build_attachment_scope(user_id=qq_id, request_type="private"),
        )
        if not self.config.should_process_private_message():
            return

        if (
            getattr(self.config, "model_pool_enabled", False)
            and _is_private_model_pool_control_text(text)
        ) and await self.ai_coordinator.model_pool.handle_private_message(
            qq_id,
            text,
            sender=route_sender,
        ):
            return

        command = self.command_dispatcher.parse_command(text)
        batch_scope = f"private:{address.canonical}"
        if command:
            await self._flush_command_buffer(scope=batch_scope, sender_id=qq_id)

            async def send_private_callback(user_id: int, message: str) -> None:
                if user_id == qq_id:
                    await self.sender.send_address_message(address, message)
                else:
                    await self.sender.send_private_message(user_id, message)

            await self.command_dispatcher.dispatch_private(
                user_id=qq_id,
                sender_id=qq_id,
                command=command,
                send_private_callback=send_private_callback,
            )
            return

        await self._run_pipelines(
            target_id=qq_id,
            target_type="private",
            text=text,
            message_content=message_content,
            address=address,
        )
        await self.ai_coordinator.handle_private_reply(
            qq_id,
            text,
            message_content,
            attachments=attachments,
            sender_name=sender_name,
            trigger_message_id=message_id,
            channel="wechat",
            address=address.canonical,
            batch_scope=batch_scope,
        )

    async def _handle_group_message(self, event: dict[str, Any]) -> None:
        """处理群聊消息事件。"""
        group_id: int = event.get("group_id", 0)
        sender_id: int = get_message_sender_id(event)
        message_content: list[dict[str, Any]] = get_message_content(event)
        trigger_message_id = event.get("message_id")

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

        group_sender: dict[str, Any] = event.get("sender", {})
        sender_card: str = group_sender.get("card", "")
        sender_nickname: str = group_sender.get("nickname", "")
        sender_role: str = group_sender.get("role", "member")
        sender_title: str = group_sender.get("title", "")
        sender_level: str = str(group_sender.get("level", "")).strip()

        text = handlers_module.extract_text(message_content, self.config.bot_qq)
        safe_text = redact_string(text)
        logger.info(
            f"[群消息] group={group_id} sender={sender_id} name={sender_card or sender_nickname} "
            f"role={sender_role} | {safe_text[:100]}"
        )

        async def _fetch_group_name() -> str:
            try:
                info = await self.onebot.get_group_info(group_id)
                if info:
                    return str(info.get("group_name", "") or "")
            except Exception as e:
                logger.warning(f"获取群聊名失败: {e}")
            return ""

        group_registered_raw, group_name, parsed_content_raw = await asyncio.gather(
            self._collect_message_attachments(
                message_content,
                group_id=group_id,
                request_type="group",
            ),
            _fetch_group_name(),
            handlers_module.parse_message_content_for_history(
                message_content,
                self.config.bot_qq,
                self.onebot.get_msg,
                self.onebot.get_forward_msg,
            ),
        )
        group_registered = _coerce_registered_attachments(group_registered_raw)
        group_attachments = group_registered.attachments

        resolved_group_sender_name = (sender_card or sender_nickname or "").strip()
        self._schedule_profile_display_name_refresh(
            task_name=f"profile_name_refresh_group:{group_id}:{sender_id}",
            sender_id=sender_id,
            sender_name=resolved_group_sender_name,
            group_id=group_id,
            group_name=str(group_name or "").strip(),
        )

        prompt_refs = group_attachments + group_registered.forward_refs
        ai_content_base = group_registered.normalized_text or parsed_content_raw
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

        # 机器人发言计入复读计数，防止 bot 复读自身
        if sender_id == self.config.bot_qq:
            await self._append_bot_repeat_counter(group_id, parsed_content_raw)
            return

        self._schedule_meme_ingest(
            attachments=group_attachments,
            chat_type="group",
            chat_id=group_id,
            sender_id=sender_id,
            message_id=safe_int(trigger_message_id),
            scope_key=build_attachment_scope(group_id=group_id, request_type="group"),
        )
        self._schedule_forward_meme_scan(
            message_content=message_content,
            chat_type="group",
            chat_id=group_id,
            sender_id=sender_id,
            message_id=safe_int(trigger_message_id),
            scope_key=build_attachment_scope(group_id=group_id, request_type="group"),
        )

        is_at_bot = self.ai_coordinator._is_at_bot(message_content)

        # 文本 @ 未命中 CQ at 段时，尝试识别「假 @」昵称
        is_fake_at = False
        normalized_text = text
        if not is_at_bot and ("@" in text or "＠" in text):
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

        if not self.config.should_process_group_message(is_at_bot=is_at_bot):
            logger.debug(
                "[消息策略] 跳过群消息处理: group=%s sender=%s process_every_message=%s at_bot=%s",
                group_id,
                sender_id,
                self.config.process_every_message,
                is_at_bot,
            )
            return

        # 斜杠命令仅在 @bot 时生效；未 @ 时不拦截普通群聊
        if is_at_bot:
            command = self.command_dispatcher.parse_command(normalized_text)
            if command:
                await self._flush_command_buffer(
                    scope=make_scope(group_id=group_id),
                    sender_id=sender_id,
                )
                await self.command_dispatcher.dispatch(group_id, sender_id, command)
                return

        if self.config.keyword_reply_enabled and handlers_module.matches_xinliweiyuan(
            text
        ):
            if await self._handle_keyword_reply(group_id, sender_id):
                return

        # 复读命中则跳过管线与 AI 自动回复
        if await self._maybe_trigger_repeat(
            group_id,
            sender_id,
            ai_content_base,
            attachments=prompt_refs,
        ):
            return

        await self._run_pipelines(
            target_id=group_id,
            target_type="group",
            text=text,
            message_content=message_content,
        )

        display_name = sender_card or sender_nickname or str(sender_id)
        await self.ai_coordinator.handle_auto_reply(
            group_id,
            sender_id,
            normalized_text if not prompt_refs else ai_content_base,
            message_content,
            attachments=prompt_refs,
            sender_name=display_name,
            group_name=group_name,
            sender_role=sender_role,
            sender_title=sender_title,
            sender_level=sender_level,
            trigger_message_id=trigger_message_id,
            is_fake_at=is_fake_at,
        )

    async def _handle_keyword_reply(self, group_id: int, sender_id: int) -> bool:
        """处理心理委员关键词自动回复；若已发送回复则返回 True。"""
        rand_val = random.random()
        if rand_val < 0.01:
            message = f"[@{sender_id}] 再发让你飞起来"
            logger.info("关键词回复: 再发让你飞起来")
            await self.sender.send_group_message(
                group_id,
                message,
                history_prefix=KEYWORD_REPLY_HISTORY_PREFIX,
            )
            return True
        if rand_val < 0.11:
            try:
                image_path = resolve_resource_path("img/xlwy.jpg").resolve().as_uri()
            except Exception:
                image_path = Path(os.path.abspath("img/xlwy.jpg")).as_uri()
            message = f"[CQ:image,file={image_path}]"
            if random.random() < 0.5:
                message = f"[@{sender_id}] {message}"
            logger.info("关键词回复: 发送图片 xlwy.jpg")
        else:
            if random.random() < 0.7:
                reply = "受着"
            else:
                reply = "那咋了"
            if random.random() < 0.5:
                message = f"[@{sender_id}] {reply}"
            else:
                message = reply
            logger.info(f"关键词回复: {reply}")
        await self.sender.send_group_message(
            group_id,
            message,
            history_prefix=KEYWORD_REPLY_HISTORY_PREFIX,
        )
        return True

    async def _flush_command_buffer(self, *, scope: str, sender_id: int) -> None:
        batcher_config = getattr(self.config, "message_batcher", None)
        if not getattr(batcher_config, "flush_on_command", False):
            return
        batcher = getattr(self, "message_batcher", None)
        if batcher is None:
            return
        # 斜杠命令命中时强制 flush 未合并 buffer，避免命令与待发 batch 交错
        flushed = await batcher.flush_sender(scope, sender_id)
        if not flushed:
            logger.warning(
                "[MessageBatcher] 命令触发 flush 当前 buffer 失败: scope=%s sender=%s",
                scope,
                sender_id,
            )

    async def _run_pipelines(
        self,
        *,
        target_id: int,
        target_type: Literal["group", "private"],
        text: str,
        message_content: list[dict[str, Any]],
        address: DeliveryAddress | None = None,
    ) -> bool:
        """并行检测并处理所有命中的自动处理管线。"""
        if not getattr(self, "_pipelines_initialized", False):
            await self.init_pipelines()
        context = build_pipeline_context(
            self,
            target_id=target_id,
            target_type=target_type,
            text=text,
            message_content=message_content,
            address=address,
        )
        detections = await self.pipeline_registry.run(context)
        return bool(detections)

    async def apply_skills_hot_reload_config(
        self,
        *,
        enabled: bool,
        interval: float,
        debounce: float,
    ) -> None:
        """跟随全局 skills 热重载配置更新管线。"""
        if not enabled:
            await self.pipeline_registry.stop_hot_reload()
            logger.info("[pipelines] 热重载已随配置禁用")
            return

        await self.pipeline_registry.stop_hot_reload()
        self.pipeline_registry.start_hot_reload(
            interval=interval,
            debounce=debounce,
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
        """关闭消息处理器。"""
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
        await self.pipeline_registry.stop_hot_reload()
        await self.message_batcher.flush_all()
        # 关闭前排空 AI 队列并落盘历史，避免丢回复/丢记录
        await self.ai_coordinator.queue_manager.drain()
        await self.ai_coordinator.queue_manager.stop()
        await self.history_manager.flush_pending_saves()
        logger.info("消息处理器已关闭")
