"""info_agent 的禁漫（JM / 18comic）列表查询工具。

三种模式共用一组筛选参数：``search`` 关键词检索、``browse`` 分类浏览、
``ranking`` 日/周/月排行。查询与渲染都在 ``Undefined.jm.searcher``，这里只做
参数校验、字符串→枚举映射与失败文案；不下载、不发送，因此不需要 sender。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Literal, TypeVar

from jmcpy import Genre, SearchTarget, SortBy, SubGenre, TimeRange

from Undefined.skills.shared import jm_search_text, parse_positive_int

logger = logging.getLogger(__name__)

#: 默认返回条数与单次返回上限
_DEFAULT_LIMIT = 5
_MAX_LIMIT = 20
#: 站点要求关键词至少两个字，过短会被自己的错误页拦下
_MIN_QUERY_CHARS = 2

_Mode = Literal["search", "browse", "ranking"]

_MODES: dict[str, _Mode] = {
    "search": "search",
    "browse": "browse",
    "ranking": "ranking",
}

_TARGETS: dict[str, SearchTarget] = {
    "site": SearchTarget.SITE,
    "work": SearchTarget.WORK,
    "author": SearchTarget.AUTHOR,
    "tag": SearchTarget.TAG,
    "actor": SearchTarget.ACTOR,
}

_SORTS: dict[str, SortBy] = {
    "latest": SortBy.LATEST,
    "views": SortBy.VIEWS,
    "pictures": SortBy.PICTURES,
    "likes": SortBy.LIKES,
    "score": SortBy.SCORE,
    "comments": SortBy.COMMENTS,
}

_TIME_RANGES: dict[str, TimeRange] = {
    "all": TimeRange.ALL,
    "day": TimeRange.DAY,
    "week": TimeRange.WEEK,
    "month": TimeRange.MONTH,
}

_GENRES: dict[str, Genre] = {
    "all": Genre.ALL,
    "doujin": Genre.DOUJIN,
    "single": Genre.SINGLE,
    "short": Genre.SHORT,
    "another": Genre.ANOTHER,
    "hanman": Genre.HANMAN,
    "meiman": Genre.MEIMAN,
    "doujin_cosplay": Genre.DOUJIN_COSPLAY,
    "3d": Genre.THREE_D,
    "english_site": Genre.ENGLISH_SITE,
}

_SUB_GENRES: dict[str, SubGenre] = {
    "chinese": SubGenre.CHINESE,
    "japanese": SubGenre.JAPANESE,
    "cg": SubGenre.CG,
    "youth": SubGenre.YOUTH,
    "other": SubGenre.OTHER,
    "3d": SubGenre.THREE_D,
    "cosplay": SubGenre.COSPLAY,
}

_EnumT = TypeVar("_EnumT")


@dataclass(frozen=True)
class _Filters:
    """一次查询的筛选条件（已由字符串映射成 jmcpy 枚举）。"""

    target: SearchTarget
    sort: SortBy
    time_range: TimeRange
    genre: Genre
    sub_genre: SubGenre | None


def _parse_enum(
    value: Any,
    mapping: dict[str, _EnumT],
    *,
    name: str,
    default: str,
) -> _EnumT:
    """把字符串参数映射成 jmcpy 枚举；非法值抛 ``ValueError``。"""
    key = str(value or default).strip().lower()
    parsed = mapping.get(key)
    if parsed is None:
        raise ValueError(f"{name} 仅支持 {'、'.join(mapping)}。")
    return parsed


def _parse_filters(args: dict[str, Any], *, mode: _Mode) -> _Filters:
    """解析筛选参数；非法取值与非法组合抛 ``ValueError``（由调用方转成提示）。"""
    target = _parse_enum(args.get("target"), _TARGETS, name="target", default="site")
    sort_raw = str(args.get("sort") or "").strip().lower()
    sort = _parse_enum(sort_raw, _SORTS, name="sort", default="latest")
    time_range = _parse_enum(
        args.get("time_range"), _TIME_RANGES, name="time_range", default="all"
    )
    genre = _parse_enum(args.get("genre"), _GENRES, name="genre", default="all")

    sub_genre_raw = args.get("sub_genre")
    sub_genre = (
        None
        if sub_genre_raw is None or not str(sub_genre_raw).strip()
        else _parse_enum(sub_genre_raw, _SUB_GENRES, name="sub_genre", default="")
    )

    if sub_genre is not None and genre is Genre.ALL:
        raise ValueError("sub_genre 需要同时指定 genre（副分类必须配合大分类使用）。")
    if mode == "ranking" and sort_raw and sort is not SortBy.VIEWS:
        raise ValueError(
            "mode=ranking 固定按观看数排序；要按其它排序请改用 mode=browse"
            "（配合 sort 与 time_range）。"
        )
    return _Filters(
        target=target,
        sort=sort,
        time_range=time_range,
        genre=genre,
        sub_genre=sub_genre,
    )


async def execute(args: dict[str, Any], context: dict[str, Any]) -> str:
    """查询禁漫本子列表（关键词搜索 / 分类浏览 / 排行），返回车号与基本信息。"""
    mode_raw = str(args.get("mode") or "search").strip().lower()
    mode = _MODES.get(mode_raw)
    if mode is None:
        return f"mode 仅支持 {'、'.join(_MODES)}。"

    query = " ".join(str(args.get("msg") or "").split())
    if mode == "search":
        if not query:
            return "mode=search 需要提供搜索关键词（msg）。"
        if len(query) < _MIN_QUERY_CHARS:
            return (
                f"搜索关键词至少需要 {_MIN_QUERY_CHARS} 个字"
                "（也可以直接输入纯数字车号）。"
            )
    elif query:
        return f"mode={mode} 不使用关键词；要按关键词搜索请用 mode=search。"

    page, error = parse_positive_int(args.get("page"), "page")
    if error:
        return error
    limit, error = parse_positive_int(args.get("n"), "n")
    if error:
        return error

    try:
        filters = _parse_filters(args, mode=mode)
    except ValueError as exc:
        return str(exc)

    runtime_config = context.get("runtime_config")
    if runtime_config is None:
        return "缺少必要的运行时组件（runtime_config）"

    try:
        return await jm_search_text(
            query,
            config=runtime_config,
            mode=mode,
            page=page or 1,
            limit=min(limit or _DEFAULT_LIMIT, _MAX_LIMIT),
            target=filters.target,
            sort=filters.sort,
            time_range=filters.time_range,
            genre=filters.genre,
            sub_genre=filters.sub_genre,
        )
    except Exception as exc:
        logger.exception("[jm_search] 查询失败: %s", exc)
        return f"禁漫查询失败: {exc}"
