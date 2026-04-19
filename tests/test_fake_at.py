"""Tests for Undefined.utils.fake_at."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from Undefined.utils.fake_at import (
    BotNicknameCache,
    _normalize,
    _sorted_nicknames,
    strip_fake_at,
)


# ---------------------------------------------------------------------------
# _normalize
# ---------------------------------------------------------------------------


class TestNormalize:
    def test_fullwidth_at_to_halfwidth(self) -> None:
        assert "@" in _normalize("＠")

    def test_casefold(self) -> None:
        assert _normalize("ABC") == "abc"

    def test_nfkc_normalization(self) -> None:
        # Fullwidth letters → ASCII
        assert _normalize("Ａ") == "a"

    def test_combined(self) -> None:
        result = _normalize("＠Ｈｅｌｌｏ")
        assert result == "@hello"


# ---------------------------------------------------------------------------
# _sorted_nicknames
# ---------------------------------------------------------------------------


class TestSortedNicknames:
    def test_sorted_by_length_desc(self) -> None:
        names = frozenset({"ab", "abcd", "a"})
        result = _sorted_nicknames(names)
        assert result == ("abcd", "ab", "a")

    def test_empty(self) -> None:
        assert _sorted_nicknames(frozenset()) == ()


# ---------------------------------------------------------------------------
# strip_fake_at
# ---------------------------------------------------------------------------


class TestStripFakeAt:
    def test_empty_nicknames(self) -> None:
        hit, text = strip_fake_at("@bot hello", frozenset())
        assert hit is False
        assert text == "@bot hello"

    def test_empty_text(self) -> None:
        hit, text = strip_fake_at("", frozenset({"bot"}))
        assert hit is False
        assert text == ""

    def test_no_at_prefix(self) -> None:
        hit, text = strip_fake_at("hello bot", frozenset({"bot"}))
        assert hit is False
        assert text == "hello bot"

    def test_simple_match(self) -> None:
        hit, text = strip_fake_at("@bot hello", frozenset({"bot"}))
        assert hit is True
        assert text == "hello"

    def test_match_with_fullwidth_at(self) -> None:
        hit, text = strip_fake_at("＠bot hello", frozenset({"bot"}))
        assert hit is True
        assert text == "hello"

    def test_case_insensitive(self) -> None:
        hit, text = strip_fake_at("@BOT hello", frozenset({"bot"}))
        assert hit is True
        assert text == "hello"

    def test_longer_nickname_preferred(self) -> None:
        nicks = frozenset({"bot", "bot助手"})
        hit, text = strip_fake_at("@bot助手 hello", nicks)
        assert hit is True
        assert text == "hello"

    def test_no_boundary_after_nickname(self) -> None:
        hit, text = strip_fake_at("@botextrastuff", frozenset({"bot"}))
        assert hit is False
        assert text == "@botextrastuff"

    def test_boundary_punctuation(self) -> None:
        hit, text = strip_fake_at("@bot，你好", frozenset({"bot"}))
        assert hit is True

    def test_boundary_end_of_string(self) -> None:
        hit, text = strip_fake_at("@bot", frozenset({"bot"}))
        assert hit is True
        assert text == ""

    def test_no_match_returns_original(self) -> None:
        hit, text = strip_fake_at("@nobody hello", frozenset({"bot"}))
        assert hit is False
        assert text == "@nobody hello"

    def test_stripped_text_lstripped(self) -> None:
        hit, text = strip_fake_at("@bot   hello", frozenset({"bot"}))
        assert hit is True
        assert text == "hello"


# ---------------------------------------------------------------------------
# BotNicknameCache
# ---------------------------------------------------------------------------


class TestBotNicknameCache:
    @pytest.fixture()
    def mock_onebot(self) -> MagicMock:
        ob = MagicMock()
        ob.get_group_member_info = AsyncMock(
            return_value={"card": "BotCard", "nickname": "BotNick"}
        )
        return ob

    async def test_get_nicknames_fetches_and_caches(
        self, mock_onebot: MagicMock
    ) -> None:
        cache = BotNicknameCache(mock_onebot, bot_qq=10000, ttl=60.0)
        names = await cache.get_nicknames(12345)
        assert "botcard" in names
        assert "botnick" in names
        mock_onebot.get_group_member_info.assert_awaited_once_with(12345, 10000)

    async def test_get_nicknames_uses_cache(self, mock_onebot: MagicMock) -> None:
        cache = BotNicknameCache(mock_onebot, bot_qq=10000, ttl=600.0)
        await cache.get_nicknames(12345)
        await cache.get_nicknames(12345)
        # Should only call API once thanks to caching
        mock_onebot.get_group_member_info.assert_awaited_once()

    async def test_invalidate_specific_group(self, mock_onebot: MagicMock) -> None:
        cache = BotNicknameCache(mock_onebot, bot_qq=10000, ttl=600.0)
        await cache.get_nicknames(12345)
        cache.invalidate(12345)
        await cache.get_nicknames(12345)
        assert mock_onebot.get_group_member_info.await_count == 2

    async def test_invalidate_all(self, mock_onebot: MagicMock) -> None:
        cache = BotNicknameCache(mock_onebot, bot_qq=10000, ttl=600.0)
        await cache.get_nicknames(111)
        await cache.get_nicknames(222)
        cache.invalidate()
        await cache.get_nicknames(111)
        # 111 fetched twice, 222 fetched once = 3
        assert mock_onebot.get_group_member_info.await_count == 3

    async def test_api_failure_returns_empty(self) -> None:
        ob: Any = MagicMock()
        ob.get_group_member_info = AsyncMock(side_effect=RuntimeError("API error"))
        cache = BotNicknameCache(ob, bot_qq=10000, ttl=60.0)
        names = await cache.get_nicknames(99999)
        assert names == frozenset()

    async def test_empty_card_and_nickname(self) -> None:
        ob: Any = MagicMock()
        ob.get_group_member_info = AsyncMock(return_value={"card": "", "nickname": ""})
        cache = BotNicknameCache(ob, bot_qq=10000, ttl=60.0)
        names = await cache.get_nicknames(123)
        assert names == frozenset()
