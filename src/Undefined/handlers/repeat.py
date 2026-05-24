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

from Undefined.utils.logging import redact_string

logger = logging.getLogger(__name__)

REPEAT_REPLY_HISTORY_PREFIX = "[系统复读] "


class RepeatMixin:
    """群聊复读计数与触发 mixin。"""

    if TYPE_CHECKING:
        config: Config
        sender: MessageSender
        _repeat_counter: dict[int, list[tuple[str, int]]]
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
            counter.append((text, self.config.bot_qq))
            n = self.config.repeat_threshold
            if len(counter) > n:
                self._repeat_counter[group_id] = counter[-n:]

    async def _maybe_trigger_repeat(
        self,
        group_id: int,
        sender_id: int,
        text: str,
    ) -> bool:
        """尝试触发群聊复读；若已发送复读消息则返回 True。"""
        if not self.config.repeat_enabled or not text:
            return False

        n = self.config.repeat_threshold
        async with self._get_repeat_lock(group_id):
            counter = self._repeat_counter.setdefault(group_id, [])
            counter.append((text, sender_id))
            if len(counter) > n:
                self._repeat_counter[group_id] = counter[-n:]
                counter = self._repeat_counter[group_id]

            if len(counter) < n:
                return False

            last_n = counter[-n:]
            texts = [t for t, _ in last_n]
            senders = [s for _, s in last_n]
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
            return True
