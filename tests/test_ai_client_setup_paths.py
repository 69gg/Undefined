from __future__ import annotations

import asyncio
from pathlib import Path

import Undefined
from Undefined.services.commands.registry import CommandRegistry
from Undefined.skills.agents import AgentRegistry
from Undefined.skills.pipelines.registry import PipelineRegistry
from Undefined.skills.tools import ToolRegistry
from Undefined.utils.paths import PACKAGE_ROOT


def _skill_dirs(base: Path) -> set[str]:
    if not base.is_dir():
        return set()
    return {
        item.name
        for item in base.iterdir()
        if item.is_dir() and (item / "config.json").exists()
    }


def _toolset_tool_names(base: Path) -> set[str]:
    if not base.is_dir():
        return set()
    names: set[str] = set()
    for config_path in base.rglob("config.json"):
        rel = config_path.parent.relative_to(base)
        if len(rel.parts) == 2:
            names.add(".".join(rel.parts))
    return names


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
    tools_dir = PACKAGE_ROOT / "skills" / "tools"
    toolsets_dir = PACKAGE_ROOT / "skills" / "toolsets"
    registry = ToolRegistry(tools_dir)
    basic = [name for name in registry._items if "." not in name]
    toolsets = [
        name for name in registry._items if "." in name and not name.startswith("mcp.")
    ]

    basic_dirs = _skill_dirs(tools_dir)
    toolset_names = _toolset_tool_names(toolsets_dir)

    assert len(basic) == len(basic_dirs)
    assert len(toolsets) == len(toolset_names)
    assert len(registry._items) == len(basic) + len(toolsets)
    assert set(basic) == basic_dirs
    assert set(toolsets) == toolset_names


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
    agents_dir = PACKAGE_ROOT / "skills" / "agents"
    registry = AgentRegistry(agents_dir)
    assert len(registry._items) == len(_skill_dirs(agents_dir))
    assert set(registry._items) == _skill_dirs(agents_dir)


def test_command_registry_loads_expected_commands() -> None:
    commands_dir = PACKAGE_ROOT / "skills" / "commands"
    registry = CommandRegistry(commands_dir)
    registry.load_commands()
    command_dirs = {
        item.name
        for item in commands_dir.iterdir()
        if item.is_dir() and (item / "handler.py").exists()
    }
    assert len(registry._commands) == len(command_dirs)
    assert set(registry._commands) == command_dirs


def test_pipeline_registry_loads_expected_pipelines() -> None:
    async def _load() -> PipelineRegistry:
        registry = PipelineRegistry(PACKAGE_ROOT / "skills" / "pipelines")
        await registry.load_items_async()
        return registry

    registry = asyncio.run(_load())
    assert set(registry._items) == {"arxiv", "bilibili", "github"}
