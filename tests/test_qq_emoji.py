"""QQ emoji 工具 单元测试"""

from __future__ import annotations


from Undefined.utils.qq_emoji import (
    get_emoji_alias_map,
    get_emoji_id_entries,
    resolve_emoji_id_by_alias,
    search_emoji_aliases,
)


# ---------------------------------------------------------------------------
# resolve_emoji_id_by_alias
# ---------------------------------------------------------------------------


class TestResolveEmojiIdByAlias:
    def test_known_chinese_alias(self) -> None:
        assert resolve_emoji_id_by_alias("微笑") == 14

    def test_known_english_alias(self) -> None:
        assert resolve_emoji_id_by_alias("smile") == 14

    def test_known_unicode_emoji(self) -> None:
        assert resolve_emoji_id_by_alias("👍") == 76

    def test_case_insensitive(self) -> None:
        assert resolve_emoji_id_by_alias("SMILE") == 14
        assert resolve_emoji_id_by_alias("Smile") == 14

    def test_whitespace_stripped(self) -> None:
        assert resolve_emoji_id_by_alias("  smile  ") == 14

    def test_unknown_alias(self) -> None:
        assert resolve_emoji_id_by_alias("completely_unknown_emoji_xyz") is None

    def test_empty_string(self) -> None:
        assert resolve_emoji_id_by_alias("") is None

    def test_whitespace_only(self) -> None:
        assert resolve_emoji_id_by_alias("   ") is None


# ---------------------------------------------------------------------------
# search_emoji_aliases
# ---------------------------------------------------------------------------


class TestSearchEmojiAliases:
    def test_search_finds_matching(self) -> None:
        results = search_emoji_aliases("笑")
        assert len(results) > 0
        for alias, _eid in results:
            assert "笑" in alias

    def test_search_limit(self) -> None:
        results = search_emoji_aliases("笑", limit=2)
        assert len(results) <= 2

    def test_search_no_match(self) -> None:
        results = search_emoji_aliases("zzz_no_match_xyz")
        assert results == []

    def test_search_empty_keyword(self) -> None:
        results = search_emoji_aliases("")
        assert results == []

    def test_search_returns_tuples(self) -> None:
        results = search_emoji_aliases("赞")
        assert len(results) > 0
        for item in results:
            assert isinstance(item, tuple)
            assert isinstance(item[0], str)
            assert isinstance(item[1], int)

    def test_search_case_insensitive(self) -> None:
        r1 = search_emoji_aliases("ok")
        r2 = search_emoji_aliases("OK")
        assert r1 == r2

    def test_search_sorted_by_id_then_alias(self) -> None:
        results = search_emoji_aliases("笑")
        if len(results) >= 2:
            for i in range(len(results) - 1):
                assert (results[i][1], results[i][0]) <= (
                    results[i + 1][1],
                    results[i + 1][0],
                )


# ---------------------------------------------------------------------------
# get_emoji_id_entries
# ---------------------------------------------------------------------------


class TestGetEmojiIdEntries:
    def test_returns_list(self) -> None:
        entries = get_emoji_id_entries()
        assert isinstance(entries, list)
        assert len(entries) > 0

    def test_entries_structure(self) -> None:
        entries = get_emoji_id_entries()
        for emoji_id, aliases in entries:
            assert isinstance(emoji_id, int)
            assert isinstance(aliases, list)
            assert all(isinstance(a, str) for a in aliases)

    def test_entries_sorted_by_id(self) -> None:
        entries = get_emoji_id_entries()
        ids = [eid for eid, _ in entries]
        assert ids == sorted(ids)

    def test_aliases_sorted(self) -> None:
        entries = get_emoji_id_entries()
        for _, aliases in entries:
            assert aliases == sorted(aliases)

    def test_known_emoji_in_entries(self) -> None:
        entries = get_emoji_id_entries()
        id_map = {eid: aliases for eid, aliases in entries}
        assert 76 in id_map
        assert "赞" in id_map[76]


# ---------------------------------------------------------------------------
# get_emoji_alias_map
# ---------------------------------------------------------------------------


class TestGetEmojiAliasMap:
    def test_returns_dict(self) -> None:
        m = get_emoji_alias_map()
        assert isinstance(m, dict)
        assert len(m) > 0

    def test_contains_known_entries(self) -> None:
        m = get_emoji_alias_map()
        assert m.get("微笑") == 14
        assert m.get("👍") == 76
