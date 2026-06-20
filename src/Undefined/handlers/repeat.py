"""群聊复读功能 mixin。

按群跟踪连续相同消息并在阈值满足时复读；由 ``MessageHandler`` 混入使用。
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from Undefined.config import Config
    from Undefined.utils.sender import MessageSender

from Undefined.attachments import (
    build_attachment_scope,
    dispatch_pending_file_sends,
    render_message_with_attachments,
)
from Undefined.utils.logging import redact_string

logger = logging.getLogger(__name__)

REPEAT_REPLY_HISTORY_PREFIX = "[系统复读] "


class RepeatMixin:
    """群聊复读计数与触发 mixin。"""

    if TYPE_CHECKING:
        config: Config
        sender: MessageSender
        _repeat_counter: dict[int, list[tuple[str, int, tuple[tuple[str, str], ...]]]]
        _repeat_locks: dict[int, asyncio.Lock]
        _repeat_cooldown: dict[int, dict[str, float]]

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
        return bool((time.monotonic() - last_time) < cooldown_minutes * 60)

    def _record_repeat_cooldown(self, group_id: int, text: str) -> None:
        """记录复读冷却时间戳，同时清理已过期条目防止内存泄漏。"""
        cooldown_seconds = self.config.repeat_cooldown_minutes * 60
        if cooldown_seconds <= 0:
            return
        key = self._normalize_repeat_text(text)
        group_cd = self._repeat_cooldown.setdefault(group_id, {})
        now = time.monotonic()
        expired = [k for k, ts in group_cd.items() if (now - ts) >= cooldown_seconds]
        for k in expired:
            del group_cd[k]
        group_cd[key] = now

    async def _append_bot_repeat_counter(self, group_id: int, text: str) -> None:
        """将 bot 自身发言写入复读计数器，防止误触复读。"""
        if not self.config.repeat_enabled or not text:
            return
        async with self._get_repeat_lock(group_id):
            counter = self._repeat_counter.setdefault(group_id, [])
            counter.append((text, self.config.bot_qq, ()))
            n = self.config.repeat_threshold
            if len(counter) > n:
                self._repeat_counter[group_id] = counter[-n:]

    @staticmethod
    def _freeze_repeat_attachments(
        attachments: list[dict[str, str]] | None,
    ) -> tuple[tuple[str, str], ...]:
        """构建稳定、可比较且可恢复的附件引用快照。"""
        if not attachments:
            return ()
        frozen_items: list[tuple[str, str]] = []
        seen_uids: set[str] = set()
        for item in attachments:
            uid = str(item.get("uid", "") or "").strip()
            if not uid or uid in seen_uids:
                continue
            seen_uids.add(uid)
            for key, value in sorted(item.items()):
                text = str(value or "").strip()
                if text:
                    frozen_items.append((f"{uid}\x00{key}", text))
        return tuple(frozen_items)

    @staticmethod
    def _unfreeze_repeat_attachments(
        frozen: tuple[tuple[str, str], ...],
    ) -> list[dict[str, str]]:
        restored: dict[str, dict[str, str]] = {}
        order: list[str] = []
        for compound_key, value in frozen:
            uid, separator, key = compound_key.partition("\x00")
            if not separator or not uid or not key:
                continue
            if uid not in restored:
                restored[uid] = {"uid": uid}
                order.append(uid)
            restored[uid][key] = value
        return [restored[uid] for uid in order]

    async def _maybe_trigger_repeat(
        self,
        group_id: int,
        sender_id: int,
        text: str,
        *,
        attachments: list[dict[str, str]] | None = None,
    ) -> bool:
        """尝试触发群聊复读；若已发送复读消息则返回 True。"""
        if not self.config.repeat_enabled or not text:
            return False

        n = self.config.repeat_threshold
        frozen_attachments = self._freeze_repeat_attachments(attachments)
        async with self._get_repeat_lock(group_id):
            counter = self._repeat_counter.setdefault(group_id, [])
            counter.append((text, sender_id, frozen_attachments))
            if len(counter) > n:
                self._repeat_counter[group_id] = counter[-n:]
                counter = self._repeat_counter[group_id]

            if len(counter) < n:
                return False

            last_n = counter[-n:]
            texts = [t for t, _s, _a in last_n]
            senders = [s for _t, s, _a in last_n]
            # 连续 n 条文本相同且来自 n 个不同发送者，且 bot 未参与
            if not (
                len(set(texts)) == 1
                and len(set(senders)) == n
                and self.config.bot_qq not in senders
            ):
                return False

            reply_text = texts[0]
            if self._is_repeat_on_cooldown(group_id, reply_text):
                # 冷却期内清空计数，避免同一文本反复试探
                self._repeat_counter[group_id] = []
                logger.debug(
                    "[复读] 冷却中跳过: group=%s text=%s",
                    group_id,
                    redact_string(reply_text)[:50],
                )
                return False

            if self.config.inverted_question_enabled:
                stripped = reply_text.strip()
                # 纯问号复读时翻转成 ¿
                if set(stripped) <= {"?", "？"}:
                    reply_text = "¿" * len(stripped)

            self._repeat_counter[group_id] = []
            self._record_repeat_cooldown(group_id, texts[0])
            reply_attachments = self._unfreeze_repeat_attachments(last_n[-1][2])
            logger.info(
                "[复读] 触发复读: group=%s text=%s",
                group_id,
                redact_string(reply_text)[:50],
            )
            delivery_text = reply_text
            history_text = reply_text
            history_attachments = reply_attachments
            rendered = None
            if reply_attachments:
                registry = getattr(self.sender, "attachment_registry", None)
                if registry is None:
                    logger.warning(
                        "[复读] 附件注册表不可用，跳过附件复读发送: group=%s text=%s",
                        group_id,
                        redact_string(reply_text)[:50],
                    )
                    return False
                scope_key = build_attachment_scope(
                    group_id=group_id,
                    request_type="group",
                )
                try:
                    rendered = await render_message_with_attachments(
                        reply_text,
                        registry=registry,
                        scope_key=scope_key,
                        strict=False,
                    )
                    delivery_text = rendered.delivery_text
                    history_text = rendered.history_text
                    history_attachments = (
                        list(rendered.attachments) or reply_attachments
                    )
                except Exception:
                    logger.warning(
                        "[复读] 图片/附件渲染失败，跳过本次复读发送: group=%s text=%s",
                        group_id,
                        redact_string(reply_text)[:50],
                        exc_info=True,
                    )
                    return False
            await self.sender.send_group_message(
                group_id,
                delivery_text,
                history_prefix=REPEAT_REPLY_HISTORY_PREFIX,
                history_message=history_text,
                attachments=history_attachments,
            )
            if rendered is not None:
                await dispatch_pending_file_sends(
                    rendered,
                    sender=self.sender,
                    target_type="group",
                    target_id=group_id,
                    registry=getattr(self.sender, "attachment_registry", None),
                )
            return True
