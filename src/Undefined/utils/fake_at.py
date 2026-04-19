"""假@检测：识别群聊中 ``@昵称`` 纯文本形式的"假 at"。

设计要点:
- ``BotNicknameCache`` 自动通过 OneBot API 获取 bot 在各群的群名片 / QQ 昵称，
  带 TTL 缓存 + per-group asyncio.Lock 防竞态。
- ``strip_fake_at`` 是无状态纯函数，负责文本匹配与剥离。
- 匹配规则：半角 ``@`` / 全角 ``＠`` + 昵称 (casefold) + 边界（空白/标点/行尾），
  昵称按长度降序匹配以避免短昵称吃掉长昵称的前缀。
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
import unicodedata
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from Undefined.onebot import OneBotClient

logger = logging.getLogger(__name__)

# 昵称后必须跟的边界：空白、常见标点、行尾
_BOUNDARY_RE = re.compile(r"[\s\u3000,.:;!?，。：；！？/\-\]）)>》]+|$")

# 缓存默认 TTL (秒)
_DEFAULT_TTL: float = 600.0


def _normalize(text: str) -> str:
    """将全角 ＠ 统一为半角 @，然后 casefold。"""
    return unicodedata.normalize("NFKC", text).casefold()


def _sorted_nicknames(names: frozenset[str]) -> tuple[str, ...]:
    """按长度降序排列，长昵称优先匹配。"""
    return tuple(sorted(names, key=len, reverse=True))


def strip_fake_at(
    text: str,
    nicknames: frozenset[str],
) -> tuple[bool, str]:
    """检测并剥离文本开头的假 @ 前缀。

    参数:
        text: 原始消息文本（已做 extract_text 处理）。
        nicknames: 当前群 bot 所有有效昵称 (已 casefold)。

    返回:
        (is_fake_at, stripped_text)
        - is_fake_at: 是否命中假 @。
        - stripped_text: 剥离假 @ 后的文本（未命中时返回原文）。
    """
    if not nicknames or not text:
        return False, text

    normalized = _normalize(text)
    # 以 @ 开头才可能是假 @
    if not normalized.startswith("@"):
        return False, text

    # 去掉开头的 @
    after_at = normalized[1:]
    raw_after_at = text[1:]  # 保持原始大小写的切片

    for nick in _sorted_nicknames(nicknames):
        if not after_at.startswith(nick):
            continue
        # 检查昵称后是否为合法边界
        rest_pos = len(nick)
        rest_normalized = after_at[rest_pos:]
        if rest_normalized and not _BOUNDARY_RE.match(rest_normalized):
            continue
        # 命中——用原始文本切出剥离后的内容
        stripped = raw_after_at[rest_pos:].lstrip()
        return True, stripped

    return False, text


class BotNicknameCache:
    """按群缓存 bot 昵称，用于假 @ 检测。

    线程安全性：
    - 只在单一 asyncio 事件循环中使用。
    - 每个 group_id 使用独立 ``asyncio.Lock``，保证同一群的并发
      消息不会触发重复 API 请求。
    - ``_global_lock`` 仅保护 ``_locks`` 字典本身的创建。
    """

    def __init__(
        self,
        onebot: OneBotClient,
        bot_qq: int,
        ttl: float = _DEFAULT_TTL,
    ) -> None:
        self._onebot = onebot
        self._bot_qq = bot_qq
        self._ttl = ttl
        # group_id → (nicknames_frozenset, timestamp)
        self._cache: dict[int, tuple[frozenset[str], float]] = {}
        # group_id → asyncio.Lock
        self._locks: dict[int, asyncio.Lock] = {}
        self._global_lock = asyncio.Lock()

    def _get_lock(self, group_id: int) -> asyncio.Lock:
        """获取指定群的锁（同步快路径 + 异步慢路径）。

        在 asyncio 单线程模型下，dict 读写本身是原子的，
        但为严谨起见仍使用 ``_global_lock`` 保护 ``_locks`` 的创建。
        注意：此方法不是 coroutine，但会在 _ensure_lock 里 await。
        """
        lock = self._locks.get(group_id)
        if lock is not None:
            return lock
        # 需要创建——由调用方在 _ensure_lock 中持有 _global_lock
        lock = asyncio.Lock()
        self._locks[group_id] = lock
        return lock

    async def _ensure_lock(self, group_id: int) -> asyncio.Lock:
        """确保 group lock 存在，如有必要在 global lock 下创建。"""
        lock = self._locks.get(group_id)
        if lock is not None:
            return lock
        async with self._global_lock:
            return self._get_lock(group_id)

    async def get_nicknames(self, group_id: int) -> frozenset[str]:
        """获取 bot 在指定群的所有有效昵称（含手动配置）。

        会自动缓存，过期后异步刷新。API 失败时返回上次缓存或仅手动昵称。
        """
        now = time.monotonic()
        cached = self._cache.get(group_id)
        if cached is not None:
            names, ts = cached
            if now - ts < self._ttl:
                return names

        lock = await self._ensure_lock(group_id)
        async with lock:
            # Double-check：可能在等锁期间已被其他协程刷新
            cached = self._cache.get(group_id)
            if cached is not None:
                names, ts = cached
                if now - ts < self._ttl:
                    return names

            fetched = await self._fetch(group_id)
            self._cache[group_id] = (fetched, time.monotonic())
            return fetched

    async def _fetch(self, group_id: int) -> frozenset[str]:
        """从 OneBot API 获取 bot 在指定群的群名片 + QQ 昵称。"""
        names: set[str] = set()
        try:
            info = await self._onebot.get_group_member_info(group_id, self._bot_qq)
            if isinstance(info, dict):
                for key in ("card", "nickname"):
                    val = str(info.get(key, "") or "").strip()
                    if val:
                        names.add(_normalize(val))
        except Exception as exc:
            logger.debug(
                "[假@] 获取 bot 群成员信息失败: group=%s err=%s",
                group_id,
                exc,
            )
        return frozenset(names)

    def invalidate(self, group_id: int | None = None) -> None:
        """手动失效缓存。group_id=None 清空全部。"""
        if group_id is None:
            self._cache.clear()
        else:
            self._cache.pop(group_id, None)
