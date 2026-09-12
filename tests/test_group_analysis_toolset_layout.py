from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
TOOLSETS_DIR = ROOT_DIR / "src" / "Undefined" / "skills" / "toolsets"

GROUP_ANALYSIS_TOOLS = {
    "activity_trend",
    "filter_members",
    "inactive_risk",
    "join_statistics",
    "level_distribution",
    "member_activity",
    "member_messages",
    "member_structure",
    "message_mix",
    "new_member_activity",
    "rank_members",
}

MOVED_ANALYSIS_TOOL_DIRS = {
    "activity_trend",
    "detect_inactive_risk",
    "filter_members",
    "get_member_activity",
    "level_distribution",
    "rank_members",
}


def _load_config(tool_dir: Path) -> dict[str, Any]:
    with (tool_dir / "config.json").open("r", encoding="utf-8") as file:
        data = json.load(file)
    assert isinstance(data, dict)
    return data


def _function_name(config: dict[str, Any]) -> str:
    function_config = config.get("function")
    assert isinstance(function_config, dict)
    name = function_config.get("name")
    assert isinstance(name, str)
    return name


def test_group_analysis_tools_are_colocated_and_named() -> None:
    group_analysis_dir = TOOLSETS_DIR / "group_analysis"
    actual_tool_dirs = {
        path.name
        for path in group_analysis_dir.iterdir()
        if path.is_dir() and (path / "config.json").exists()
    }

    assert GROUP_ANALYSIS_TOOLS <= actual_tool_dirs
    for tool_name in GROUP_ANALYSIS_TOOLS:
        assert _function_name(_load_config(group_analysis_dir / tool_name)) == tool_name


def test_group_toolset_keeps_analysis_tools_out() -> None:
    group_dir = TOOLSETS_DIR / "group"
    group_tool_dirs = {path.name for path in group_dir.iterdir() if path.is_dir()}

    assert group_tool_dirs.isdisjoint(MOVED_ANALYSIS_TOOL_DIRS)


def test_member_activity_schema_distinguishes_recency_and_frequency() -> None:
    config = _load_config(TOOLSETS_DIR / "group_analysis" / "member_activity")
    function = config["function"]
    properties = function["parameters"]["properties"]

    assert "不能据此判断谁发言最多或当前在线" in function["description"]
    assert "查询窗口内谁发言最多用 history" in function["description"]
    assert "最近发言榜不等于发言数量榜" in properties["source"]["description"]
    assert "相对当前时间" in properties["threshold_days"]["description"]
    assert "0 不代表整个窗口没有发言" in properties["include_zero"]["description"]
    assert properties["source"]["default"] == "hybrid"
