from __future__ import annotations

import asyncio
from pathlib import Path

import Undefined
from Undefined.services.commands.registry import CommandRegistry
from Undefined.skills.agents import AgentRegistry
from Undefined.skills.pipelines.registry import PipelineRegistry
from Undefined.skills.tools import ToolRegistry
from Undefined.utils.paths import PACKAGE_ROOT

# Snapshot counts from skills/*/config.json inventory (excluding MCP).
EXPECTED_BASIC_TOOL_COUNT = 15
EXPECTED_TOOLSET_COUNT = 53
EXPECTED_AGENT_COUNT = 8
EXPECTED_COMMAND_COUNT = 12
EXPECTED_PIPELINE_COUNT = 3


def test_package_root_matches_undefined_package_directory() -> None:
    assert PACKAGE_ROOT == Path(Undefined.__file__).resolve().parent


def test_package_root_contains_skills_directories() -> None:
    assert (PACKAGE_ROOT / "skills" / "tools").is_dir()
    assert (PACKAGE_ROOT / "skills" / "agents").is_dir()
    assert (PACKAGE_ROOT / "skills" / "anthropic_skills").is_dir()
    assert (PACKAGE_ROOT / "skills" / "toolsets").is_dir()
    assert (PACKAGE_ROOT / "skills" / "pipelines").is_dir()
    assert (PACKAGE_ROOT / "skills" / "commands").is_dir()


def test_setup_wrong_path_does_not_exist() -> None:
    """Regression: ai/client/setup.py used parents[1] and pointed at ai/skills."""
    wrong_root = Path(__file__).resolve().parents[2] / "src" / "Undefined" / "ai"
    assert not (wrong_root / "skills" / "tools").exists()


def test_tool_registry_loads_all_skill_directories() -> None:
    registry = ToolRegistry(PACKAGE_ROOT / "skills" / "tools")
    basic = [name for name in registry._items if "." not in name]
    toolsets = [
        name for name in registry._items if "." in name and not name.startswith("mcp.")
    ]

    assert len(basic) == EXPECTED_BASIC_TOOL_COUNT
    assert len(toolsets) == EXPECTED_TOOLSET_COUNT
    assert len(registry._items) == EXPECTED_BASIC_TOOL_COUNT + EXPECTED_TOOLSET_COUNT

    tool_dirs = [
        item.name
        for item in (PACKAGE_ROOT / "skills" / "tools").iterdir()
        if item.is_dir() and (item / "config.json").exists()
    ]
    assert len(tool_dirs) == EXPECTED_BASIC_TOOL_COUNT
    assert set(basic) == set(tool_dirs)


def test_all_registered_tools_import_handlers() -> None:
    registry = ToolRegistry(PACKAGE_ROOT / "skills" / "tools")
    errors: list[str] = []

    for name, item in sorted(registry._items.items()):
        try:
            registry._load_handler_for_item(item)
            if item.handler is None:
                errors.append(f"{name}: handler is None")
        except Exception as exc:
            errors.append(f"{name}: {exc}")

    assert errors == []


def test_agent_registry_loads_expected_agents() -> None:
    registry = AgentRegistry(PACKAGE_ROOT / "skills" / "agents")
    assert len(registry._items) == EXPECTED_AGENT_COUNT


def test_command_registry_loads_expected_commands() -> None:
    registry = CommandRegistry(PACKAGE_ROOT / "skills" / "commands")
    registry.load_commands()
    assert len(registry._commands) == EXPECTED_COMMAND_COUNT


def test_pipeline_registry_loads_expected_pipelines() -> None:
    async def _load() -> PipelineRegistry:
        registry = PipelineRegistry(PACKAGE_ROOT / "skills" / "pipelines")
        await registry.load_items_async()
        return registry

    registry = asyncio.run(_load())
    assert len(registry._items) == EXPECTED_PIPELINE_COUNT
    assert set(registry._items) == {"arxiv", "bilibili", "github"}
