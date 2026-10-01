"""禁漫列表查询：关键词搜索、分类浏览与排行榜（只读列表，不下载任何图片）。

统一入口 :func:`fetch_listing` 按 ``mode`` 分派到 jmcpy 的 ``Client.search`` /
``browse`` / ``ranking``，返回一页 ``BookBrief``：只有车号、标题、作者、分类与
更新时间，不请求正文或图片。查询在 jmcpy 自己的线程里跑，与
:mod:`Undefined.jm.downloader` 的 ``fetch_book`` 同一形态，不阻塞事件循环。

副分类（``sub_genre``）只有网页端接口支持，门面会自动路由；网页端不可用时
jmcpy 抛 ``ChallengeBlocked`` 一类异常，由调用方转成可读提示。
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from jmcpy import (
    BookBrief,
    Client,
    Genre,
    Listing,
    RankingSpan,
    SearchTarget,
    SortBy,
    Settings,
    SubGenre,
    TimeRange,
)

from Undefined.jm.client import build_settings

#: 列表来源：关键词搜索 / 分类浏览 / 排行榜
JmListingMode = Literal["search", "browse", "ranking"]

#: 展示用时间统一按北京时间（站点面向中文用户，jmcpy 返回的是秒级时间戳）
_BEIJING_TIMEZONE = timezone(timedelta(hours=8))
#: 列表项标题缺失时的占位（与 ``sender.format_jm_book_info`` 同一文案）
_UNKNOWN_TITLE = "未知标题"

_TARGET_LABELS: dict[SearchTarget, str] = {
    SearchTarget.SITE: "站内",
    SearchTarget.WORK: "作品",
    SearchTarget.AUTHOR: "作者",
    SearchTarget.TAG: "标签",
    SearchTarget.ACTOR: "角色",
}

_SORT_LABELS: dict[SortBy, str] = {
    SortBy.LATEST: "最新",
    SortBy.VIEWS: "观看数",
    SortBy.PICTURES: "图片数",
    SortBy.LIKES: "点赞数",
    SortBy.SCORE: "评分",
    SortBy.COMMENTS: "评论数",
}

_TIME_LABELS: dict[TimeRange, str] = {
    TimeRange.DAY: "今日",
    TimeRange.WEEK: "近一周",
    TimeRange.MONTH: "近一月",
}

_GENRE_LABELS: dict[Genre, str] = {
    Genre.DOUJIN: "同人",
    Genre.SINGLE: "单行本",
    Genre.SHORT: "短篇",
    Genre.ANOTHER: "其他",
    Genre.HANMAN: "汉漫",
    Genre.MEIMAN: "美漫",
    Genre.DOUJIN_COSPLAY: "同人Cosplay",
    Genre.THREE_D: "3D",
    Genre.ENGLISH_SITE: "英译站",
}

_SUB_GENRE_LABELS: dict[SubGenre, str] = {
    SubGenre.CHINESE: "中文",
    SubGenre.JAPANESE: "日文",
    SubGenre.CG: "CG",
    SubGenre.YOUTH: "青年",
    SubGenre.OTHER: "其他",
    SubGenre.THREE_D: "3D",
    SubGenre.COSPLAY: "Cosplay",
}

#: 排行榜跨度：jmcpy 的 ``RankingSpan`` 与 ``TimeRange`` 的 day/week/month 取值一致
_RANKING_SPANS: dict[TimeRange, RankingSpan] = {
    TimeRange.DAY: RankingSpan.DAY,
    TimeRange.WEEK: RankingSpan.WEEK,
    TimeRange.MONTH: RankingSpan.MONTH,
}
_RANKING_LABELS: dict[TimeRange, str] = {
    TimeRange.DAY: "日榜",
    TimeRange.WEEK: "周榜",
    TimeRange.MONTH: "月榜",
}


def _fetch_sync(
    settings: Settings,
    *,
    mode: JmListingMode,
    query: str,
    page: int,
    target: SearchTarget,
    sort: SortBy,
    time_range: TimeRange,
    genre: Genre,
    sub_genre: SubGenre | None,
) -> Listing[BookBrief]:
    with Client(settings) as client:
        if mode == "ranking":
            span = _RANKING_SPANS.get(time_range, RankingSpan.WEEK)
            return client.ranking(span, page=page, genre=genre, sub_genre=sub_genre)
        if mode == "browse":
            return client.browse(
                page=page,
                genre=genre,
                sub_genre=sub_genre,
                sort=sort,
                time_range=time_range,
            )
        return client.search(
            query,
            page=page,
            target=target,
            sort=sort,
            time_range=time_range,
            genre=genre,
            sub_genre=sub_genre,
        )


async def fetch_listing(
    *,
    config: Any,
    mode: JmListingMode,
    query: str = "",
    page: int = 1,
    target: SearchTarget = SearchTarget.SITE,
    sort: SortBy = SortBy.LATEST,
    time_range: TimeRange = TimeRange.ALL,
    genre: Genre = Genre.ALL,
    sub_genre: SubGenre | None = None,
) -> Listing[BookBrief]:
    """按模式取一页本子列表（只查列表，线程里跑，不阻塞事件循环）。"""
    return await asyncio.to_thread(
        _fetch_sync,
        build_settings(config),
        mode=mode,
        query=query,
        page=page,
        target=target,
        sort=sort,
        time_range=time_range,
        genre=genre,
        sub_genre=sub_genre,
    )


def _format_updated_at(value: int | None) -> str:
    """把 ``update_at`` 秒级时间戳格式化为北京时间 ``YYYY-MM-DD``。

    缺失或越界的时间戳返回空串：列表里少一个日期，比展示错误时间安全。
    """
    if value is None or value <= 0:
        return ""
    try:
        moment = datetime.fromtimestamp(int(value), tz=_BEIJING_TIMEZONE)
    except (OverflowError, OSError, ValueError):
        return ""
    return moment.strftime("%Y-%m-%d")


def _taxonomy_titles(book: BookBrief) -> list[str]:
    """按「大分类 / 副分类」顺序收集非空分类名。"""
    titles: list[str] = []
    for taxonomy in (book.category, book.sub_category):
        if taxonomy is None:
            continue
        title = str(taxonomy).strip()
        if title:
            titles.append(title)
    return titles


def _format_item(index: int, book: BookBrief) -> str:
    """把一条结果渲染成「标题行 + 可选明细行」。

    车号写成 ``JM<数字>``：它是后续取详情/附件的标识，比站点链接更适合复制。
    """
    lines = [f"{index}. 「JM{book.book_id} {book.title.strip() or _UNKNOWN_TITLE}」"]
    details: list[str] = []
    author = book.author.strip()
    if author:
        details.append(f"作者: {author}")
    categories = " / ".join(_taxonomy_titles(book))
    if categories:
        details.append(f"分类: {categories}")
    updated = _format_updated_at(book.updated_at)
    if updated:
        details.append(f"更新: {updated}")
    if details:
        lines.append("   " + " | ".join(details))
    return "\n".join(lines)


def _category_label(genre: Genre, sub_genre: SubGenre | None) -> str:
    """把大分类与副分类拼成「同人 / 中文」形式的说明。"""
    labels = [_GENRE_LABELS.get(genre, "")]
    if sub_genre is not None:
        labels.append(_SUB_GENRE_LABELS.get(sub_genre, ""))
    return " / ".join(label for label in labels if label)


def _sort_label(sort: SortBy) -> str:
    """排序说明；默认的「最新」不写进表头，避免每个表头都挂一句废话。"""
    if sort is SortBy.LATEST:
        return ""
    label = _SORT_LABELS.get(sort, "")
    return f"按{label}" if label else ""


def describe_query(
    *,
    mode: JmListingMode,
    query: str = "",
    target: SearchTarget = SearchTarget.SITE,
    sort: SortBy = SortBy.LATEST,
    time_range: TimeRange = TimeRange.ALL,
    genre: Genre = Genre.ALL,
    sub_genre: SubGenre | None = None,
) -> str:
    """生成结果表头，说明这批车号是怎么来的（模式 + 生效的筛选条件）。"""
    if mode == "ranking":
        heading = f"🏆 禁漫{_RANKING_LABELS.get(time_range, '周榜')}"
        details = [_category_label(genre, sub_genre)]
    elif mode == "browse":
        heading = "📚 禁漫分类浏览"
        details = [
            _category_label(genre, sub_genre),
            _sort_label(sort),
            _TIME_LABELS.get(time_range, ""),
        ]
    else:
        heading = f"🔍 禁漫搜索「{query}」"
        details = [
            "" if target is SearchTarget.SITE else _TARGET_LABELS.get(target, ""),
            _category_label(genre, sub_genre),
            _sort_label(sort),
            _TIME_LABELS.get(time_range, ""),
        ]
    qualifiers = "，".join(item for item in details if item)
    return f"{heading}（{qualifiers}）" if qualifiers else heading


def format_listing(listing: Listing[BookBrief], *, heading: str, limit: int) -> str:
    """把一页结果渲染成可直接返回给模型/用户的文本。"""
    items = list(listing.items)[: max(0, int(limit))]
    if not items:
        return f"{heading}：没有找到结果。"

    header = heading
    page_count = listing.page_count
    if listing.total is None:
        header += f"：第 {listing.page} 页"
    else:
        header += f"：共 {listing.total} 条，第 {listing.page}"
        header += f"/{page_count} 页" if page_count else " 页"

    lines = [header]
    lines.extend(_format_item(index, book) for index, book in enumerate(items, start=1))
    if page_count is None:
        # 分类页与排行榜不返回总数：只能提示「需要更多时」翻页，不谎称一定还有
        lines.append(f"—— 需要更多结果时可用 page={listing.page + 1} 继续")
    elif listing.page < page_count:
        lines.append(f"—— 还有更多结果，可用 page={listing.page + 1} 继续")
    return "\n".join(lines)
