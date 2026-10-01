from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from jmcpy import Genre, SearchTarget, SortBy, SubGenre, TimeRange

from Undefined.skills.agents.info_agent.tools.jm_search import handler as jm_search


def _patch_success(
    monkeypatch: pytest.MonkeyPatch, result: str = "查询结果"
) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    async def _fake(query: str, **kwargs: Any) -> str:
        captured["query"] = query
        captured.update(kwargs)
        return result

    monkeypatch.setattr(jm_search, "jm_search_text", _fake)
    return captured


def _context() -> dict[str, Any]:
    return {"runtime_config": SimpleNamespace()}


@pytest.mark.asyncio
async def test_jm_search_forwards_search_filters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _patch_success(monkeypatch)
    config = _context()["runtime_config"]

    result = await jm_search.execute(
        {
            "mode": "search",
            "msg": "  mana   作者  ",
            "page": 2,
            "n": 3,
            "target": "AUTHOR",
            "sort": "views",
            "time_range": "week",
            "genre": "doujin",
            "sub_genre": "CG",
        },
        {"runtime_config": config},
    )

    assert result == "查询结果"
    assert captured["query"] == "mana 作者"
    assert captured["mode"] == "search"
    assert captured["page"] == 2
    assert captured["limit"] == 3
    assert captured["target"] is SearchTarget.AUTHOR
    assert captured["sort"] is SortBy.VIEWS
    assert captured["time_range"] is TimeRange.WEEK
    assert captured["genre"] is Genre.DOUJIN
    assert captured["sub_genre"] is SubGenre.CG
    assert captured["config"] is config


@pytest.mark.asyncio
async def test_jm_search_defaults_and_limit_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _patch_success(monkeypatch)

    await jm_search.execute({"msg": "mana"}, _context())
    assert captured["mode"] == "search"
    assert captured["page"] == 1
    assert captured["limit"] == 5
    assert captured["target"] is SearchTarget.SITE
    assert captured["sort"] is SortBy.LATEST
    assert captured["time_range"] is TimeRange.ALL
    assert captured["genre"] is Genre.ALL
    assert captured["sub_genre"] is None

    await jm_search.execute({"msg": "mana", "n": 999}, _context())
    assert captured["limit"] == 20


@pytest.mark.asyncio
async def test_jm_search_browses_without_keyword(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _patch_success(monkeypatch)

    await jm_search.execute(
        {
            "mode": "browse",
            "genre": "hanman",
            "sub_genre": "chinese",
            "sort": "likes",
            "time_range": "month",
        },
        _context(),
    )

    assert captured["query"] == ""
    assert captured["mode"] == "browse"
    assert captured["genre"] is Genre.HANMAN
    assert captured["sub_genre"] is SubGenre.CHINESE
    assert captured["sort"] is SortBy.LIKES
    assert captured["time_range"] is TimeRange.MONTH


@pytest.mark.asyncio
async def test_jm_search_ranking_accepts_views_sort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _patch_success(monkeypatch)

    await jm_search.execute(
        {"mode": "ranking", "time_range": "day", "sort": "views"}, _context()
    )

    assert captured["mode"] == "ranking"
    assert captured["time_range"] is TimeRange.DAY
    assert captured["sort"] is SortBy.VIEWS


@pytest.mark.asyncio
async def test_jm_search_rejects_empty_or_short_keyword(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _patch_success(monkeypatch)

    assert await jm_search.execute({"msg": "   "}, _context()) == (
        "mode=search 需要提供搜索关键词（msg）。"
    )
    short = await jm_search.execute({"msg": "海"}, _context())
    assert "至少需要 2 个字" in short
    assert captured == {}


@pytest.mark.asyncio
async def test_jm_search_rejects_keyword_outside_search_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _patch_success(monkeypatch)

    assert await jm_search.execute({"mode": "browse", "msg": "mana"}, _context()) == (
        "mode=browse 不使用关键词；要按关键词搜索请用 mode=search。"
    )
    assert captured == {}


@pytest.mark.asyncio
async def test_jm_search_rejects_unknown_mode_and_enums(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _patch_success(monkeypatch)

    assert await jm_search.execute({"mode": "hot", "msg": "mana"}, _context()) == (
        "mode 仅支持 search、browse、ranking。"
    )
    assert await jm_search.execute({"msg": "mana", "target": "movie"}, _context()) == (
        "target 仅支持 site、work、author、tag、actor。"
    )
    assert await jm_search.execute({"msg": "mana", "sort": "random"}, _context()) == (
        "sort 仅支持 latest、views、pictures、likes、score、comments。"
    )
    assert await jm_search.execute({"msg": "mana", "genre": "comic"}, _context()) == (
        "genre 仅支持 all、doujin、single、short、another、hanman、meiman、"
        "doujin_cosplay、3d、english_site。"
    )
    assert captured == {}


@pytest.mark.asyncio
async def test_jm_search_validates_filter_combinations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _patch_success(monkeypatch)

    assert (
        await jm_search.execute({"msg": "mana", "sub_genre": "cg"}, _context())
        == "sub_genre 需要同时指定 genre（副分类必须配合大分类使用）。"
    )

    ranking = await jm_search.execute(
        {"mode": "ranking", "sort": "likes", "genre": "doujin"}, _context()
    )
    assert "mode=ranking 固定按观看数排序" in ranking
    assert captured == {}


@pytest.mark.asyncio
async def test_jm_search_rejects_invalid_paging(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _patch_success(monkeypatch)

    assert await jm_search.execute({"msg": "mana", "page": 0}, _context()) == (
        "page 必须是正整数"
    )
    assert await jm_search.execute({"msg": "mana", "n": "x"}, _context()) == (
        "n 必须是整数"
    )
    assert captured == {}


@pytest.mark.asyncio
async def test_jm_search_requires_runtime_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _patch_success(monkeypatch)

    result = await jm_search.execute({"msg": "mana"}, {})

    assert result == "缺少必要的运行时组件（runtime_config）"
    assert captured == {}


@pytest.mark.asyncio
async def test_jm_search_reports_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _boom(query: str, **kwargs: Any) -> str:
        raise RuntimeError("站点不可用")

    monkeypatch.setattr(jm_search, "jm_search_text", _boom)

    assert await jm_search.execute({"msg": "mana"}, _context()) == (
        "禁漫查询失败: 站点不可用"
    )
