from __future__ import annotations

from typing import Any

import pytest
from jmcpy import (
    BookBrief,
    Genre,
    Listing,
    RankingSpan,
    SearchTarget,
    SortBy,
    SubGenre,
    Taxonomy,
    TimeRange,
)

from Undefined.jm import searcher


def _book(
    book_id: int,
    title: str,
    *,
    author: str = "",
    category: str = "",
    sub_category: str = "",
    updated_at: int | None = None,
) -> BookBrief:
    return BookBrief(
        book_id=book_id,
        title=title,
        author=author,
        category=Taxonomy(taxonomy_id="1", title=category) if category else None,
        sub_category=(
            Taxonomy(taxonomy_id="3", title=sub_category) if sub_category else None
        ),
        updated_at=updated_at,
    )


def test_format_listing_renders_book_details() -> None:
    listing: Listing[BookBrief] = Listing(
        items=(
            _book(
                1472715,
                "示例name",
                author="示例author",
                category="同人",
                sub_category="中文",
                updated_at=1789376791,
            ),
        ),
        total=261,
        page=1,
    )

    lines = searcher.format_listing(
        listing, heading="🔍 禁漫搜索「mana」", limit=5
    ).splitlines()

    assert lines[0] == "🔍 禁漫搜索「mana」：共 261 条，第 1/4 页"
    assert lines[1] == "1. 「JM1472715 示例name」"
    assert lines[2] == "   作者: 示例author | 分类: 同人 / 中文 | 更新: 2026-09-14"
    assert lines[-1] == "—— 还有更多结果，可用 page=2 继续"


def test_format_listing_omits_missing_fields() -> None:
    listing: Listing[BookBrief] = Listing(items=(_book(1, "   "),), total=1, page=1)

    text = searcher.format_listing(listing, heading="heading", limit=5)

    assert text.splitlines()[1] == "1. 「JM1 未知标题」"
    assert "作者" not in text
    assert "分类" not in text
    assert "更新" not in text


def test_format_listing_truncates_to_limit() -> None:
    items = tuple(_book(index, f"标题{index}") for index in range(1, 6))
    listing: Listing[BookBrief] = Listing(items=items, total=200, page=2)

    text = searcher.format_listing(listing, heading="heading", limit=2)

    assert "标题1" in text
    assert "标题2" in text
    assert "标题3" not in text
    assert text.splitlines()[0] == "heading：共 200 条，第 2/3 页"
    assert "page=3" in text


def test_format_listing_without_total_suggests_next_page() -> None:
    """分类页与排行榜不返回总数：只能说「需要更多时」翻页。"""
    listing: Listing[BookBrief] = Listing(items=(_book(1, "只有一页"),), total=None)

    lines = searcher.format_listing(
        listing, heading="🏆 禁漫周榜", limit=5
    ).splitlines()

    assert lines[0] == "🏆 禁漫周榜：第 1 页"
    assert lines[-1] == "—— 需要更多结果时可用 page=2 继续"


def test_format_listing_reports_empty_result() -> None:
    listing: Listing[BookBrief] = Listing(items=(), total=0, page=1)

    assert (
        searcher.format_listing(listing, heading="🔍 禁漫搜索「mana」", limit=5)
        == "🔍 禁漫搜索「mana」：没有找到结果。"
    )


def test_format_listing_hides_hint_on_last_known_page() -> None:
    items = tuple(_book(index, f"标题{index}") for index in range(1, 4))
    listing: Listing[BookBrief] = Listing(items=items, total=200, page=3)

    text = searcher.format_listing(listing, heading="heading", limit=5)

    assert "page=4" not in text


def test_describe_query_for_plain_search() -> None:
    assert searcher.describe_query(mode="search", query="mana") == "🔍 禁漫搜索「mana」"


def test_describe_query_lists_every_active_filter() -> None:
    heading = searcher.describe_query(
        mode="search",
        query="mana",
        target=SearchTarget.AUTHOR,
        sort=SortBy.VIEWS,
        time_range=TimeRange.WEEK,
        genre=Genre.DOUJIN,
        sub_genre=SubGenre.CHINESE,
    )

    assert heading == "🔍 禁漫搜索「mana」（作者，同人 / 中文，按观看数，近一周）"


def test_describe_query_for_browse_and_ranking() -> None:
    assert searcher.describe_query(mode="browse", genre=Genre.HANMAN) == (
        "📚 禁漫分类浏览（汉漫）"
    )
    assert searcher.describe_query(mode="ranking") == "🏆 禁漫周榜"
    assert (
        searcher.describe_query(
            mode="ranking",
            time_range=TimeRange.DAY,
            genre=Genre.DOUJIN,
            sub_genre=SubGenre.CG,
        )
        == "🏆 禁漫日榜（同人 / CG）"
    )
    assert (
        searcher.describe_query(
            mode="browse", sort=SortBy.LIKES, time_range=TimeRange.MONTH
        )
        == "📚 禁漫分类浏览（按点赞数，近一月）"
    )


class _FakeClient:
    """记录初始化参数与列表调用的假 jmcpy 客户端。"""

    instances: list[_FakeClient] = []

    def __init__(self, settings: Any) -> None:
        self.settings = settings
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        _FakeClient.instances.append(self)

    def __enter__(self) -> _FakeClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def search(self, query: str, **kwargs: Any) -> Listing[BookBrief]:
        self.calls.append(("search", (query,), kwargs))
        return _LISTING

    def browse(self, **kwargs: Any) -> Listing[BookBrief]:
        self.calls.append(("browse", (), kwargs))
        return _LISTING

    def ranking(self, span: RankingSpan, **kwargs: Any) -> Listing[BookBrief]:
        self.calls.append(("ranking", (span,), kwargs))
        return _LISTING


_LISTING: Listing[BookBrief] = Listing(items=(_book(1, "x"),), total=1, page=1)


def _patched(monkeypatch: pytest.MonkeyPatch) -> object:
    _FakeClient.instances.clear()
    settings = object()
    monkeypatch.setattr(searcher, "Client", _FakeClient)
    monkeypatch.setattr(searcher, "build_settings", lambda config: settings)
    return settings


@pytest.mark.asyncio
async def test_fetch_listing_searches_with_all_filters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _patched(monkeypatch)

    result = await searcher.fetch_listing(
        config=object(),
        mode="search",
        query="mana",
        page=2,
        target=SearchTarget.AUTHOR,
        sort=SortBy.VIEWS,
        time_range=TimeRange.WEEK,
        genre=Genre.DOUJIN,
        sub_genre=SubGenre.CG,
    )

    assert result is _LISTING
    client = _FakeClient.instances[-1]
    assert client.settings is settings
    assert client.calls == [
        (
            "search",
            ("mana",),
            {
                "page": 2,
                "target": SearchTarget.AUTHOR,
                "sort": SortBy.VIEWS,
                "time_range": TimeRange.WEEK,
                "genre": Genre.DOUJIN,
                "sub_genre": SubGenre.CG,
            },
        )
    ]


@pytest.mark.asyncio
async def test_fetch_listing_browses_without_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patched(monkeypatch)

    await searcher.fetch_listing(
        config=object(),
        mode="browse",
        page=3,
        sort=SortBy.LIKES,
        time_range=TimeRange.MONTH,
        genre=Genre.HANMAN,
    )

    assert _FakeClient.instances[-1].calls == [
        (
            "browse",
            (),
            {
                "page": 3,
                "genre": Genre.HANMAN,
                "sub_genre": None,
                "sort": SortBy.LIKES,
                "time_range": TimeRange.MONTH,
            },
        )
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("time_range", "expected_span"),
    [
        (TimeRange.ALL, RankingSpan.WEEK),
        (TimeRange.DAY, RankingSpan.DAY),
        (TimeRange.WEEK, RankingSpan.WEEK),
        (TimeRange.MONTH, RankingSpan.MONTH),
    ],
)
async def test_fetch_listing_maps_ranking_span(
    monkeypatch: pytest.MonkeyPatch,
    time_range: TimeRange,
    expected_span: RankingSpan,
) -> None:
    _patched(monkeypatch)

    await searcher.fetch_listing(
        config=object(),
        mode="ranking",
        time_range=time_range,
        genre=Genre.DOUJIN,
        sub_genre=SubGenre.CHINESE,
    )

    assert _FakeClient.instances[-1].calls == [
        (
            "ranking",
            (expected_span,),
            {"page": 1, "genre": Genre.DOUJIN, "sub_genre": SubGenre.CHINESE},
        )
    ]


@pytest.mark.asyncio
async def test_fetch_listing_uses_documented_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patched(monkeypatch)

    await searcher.fetch_listing(config=object(), mode="search", query="mana")

    assert _FakeClient.instances[-1].calls == [
        (
            "search",
            ("mana",),
            {
                "page": 1,
                "target": SearchTarget.SITE,
                "sort": SortBy.LATEST,
                "time_range": TimeRange.ALL,
                "genre": Genre.ALL,
                "sub_genre": None,
            },
        )
    ]
