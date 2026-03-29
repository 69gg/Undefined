from __future__ import annotations

import json

import pytest

from Undefined.changelog import ChangelogEntry
from Undefined.skills.tools.changelog_query import handler as changelog_tool_handler


def _entry(version: str, title: str) -> ChangelogEntry:
    return ChangelogEntry(
        version=version,
        title=title,
        summary=f"{title} 摘要",
        changes=(f"{title} 变更一", f"{title} 变更二", f"{title} 变更三"),
    )


@pytest.mark.asyncio
async def test_changelog_tool_latest_returns_structured_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        changelog_tool_handler,
        "get_latest_entry",
        lambda: _entry("v3.2.6", "标题甲"),
    )

    result = await changelog_tool_handler.execute({}, {})
    payload = json.loads(result)

    assert payload["ok"] is True
    assert payload["action"] == "latest"
    assert payload["entry"]["version"] == "v3.2.6"
    assert payload["entry"]["summary"] == "标题甲 摘要"
    assert payload["entry"]["changes"] == [
        "标题甲 变更一",
        "标题甲 变更二",
        "标题甲 变更三",
    ]


@pytest.mark.asyncio
async def test_changelog_tool_list_defaults_to_compact_items(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        changelog_tool_handler,
        "list_entries",
        lambda limit: (_entry("v3.2.6", "标题甲"), _entry("v3.2.5", "标题乙"))[:limit],
    )

    result = await changelog_tool_handler.execute({"action": "list", "limit": 1}, {})
    payload = json.loads(result)

    assert payload["ok"] is True
    assert payload["count"] == 1
    assert payload["items"] == [{"version": "v3.2.6", "title": "标题甲"}]


@pytest.mark.asyncio
async def test_changelog_tool_show_honors_detail_flags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        changelog_tool_handler,
        "get_entry",
        lambda version: _entry("v3.2.6", "标题甲"),
    )

    result = await changelog_tool_handler.execute(
        {
            "action": "show",
            "version": "3.2.6",
            "include_summary": False,
            "include_changes": True,
            "max_changes": 2,
        },
        {},
    )
    payload = json.loads(result)

    assert payload["ok"] is True
    assert "summary" not in payload["entry"]
    assert payload["entry"]["changes"] == ["标题甲 变更一", "标题甲 变更二"]
    assert payload["entry"]["change_count"] == 3


@pytest.mark.asyncio
async def test_changelog_tool_rejects_invalid_action() -> None:
    result = await changelog_tool_handler.execute({"action": "unknown"}, {})
    payload = json.loads(result)

    assert payload == {
        "ok": False,
        "action": "unknown",
        "error": "action 只能是 latest、list 或 show",
    }


@pytest.mark.asyncio
async def test_changelog_tool_requires_version_for_show() -> None:
    result = await changelog_tool_handler.execute({"action": "show"}, {})
    payload = json.loads(result)

    assert payload["ok"] is False
    assert payload["error"] == "show 动作必须提供 version"
