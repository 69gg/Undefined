from __future__ import annotations

import json
import sys
from pathlib import Path

from Undefined.skills.agents import AgentRegistry
from Undefined.skills.tools import ToolRegistry
from Undefined.skills.toolsets import ToolSetRegistry

PACKAGE_ROOT = Path(__file__).parents[1] / "src" / "Undefined"


def _write_skill(
    item_dir: Path,
    *,
    name: str,
    handler_source: str,
) -> None:
    item_dir.mkdir(parents=True, exist_ok=True)
    (item_dir / "config.json").write_text(
        json.dumps(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": "test skill",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ),
        encoding="utf-8",
    )
    (item_dir / "handler.py").write_text(handler_source, encoding="utf-8")


def test_all_registered_agents_import_handlers() -> None:
    """随包发布的 agent handler 都必须能导入（含使用相对导入的 agent）。"""
    registry = AgentRegistry(PACKAGE_ROOT / "skills" / "agents")

    assert registry.get_load_failures() == {}
    for name, item in registry._items.items():
        assert item.handler is not None, name
        assert item.loaded is True, name


def test_agent_relative_import_handler_loads() -> None:
    """handler.py 内的相对导入必须能解析到同目录模块。"""
    registry = AgentRegistry(PACKAGE_ROOT / "skills" / "agents")

    item = registry._items["code_delivery_agent"]
    assert item.module_name == "Undefined.skills.agents.code_delivery_agent.handler"
    assert item.handler is not None
    assert item.handler.__module__ == item.module_name


def test_handler_module_is_canonical_across_import_paths() -> None:
    """按文件路径加载与常规 import 必须得到同一个模块对象。"""
    registry = AgentRegistry(PACKAGE_ROOT / "skills" / "agents")
    item = registry._items["summary_agent"]

    import Undefined.skills.agents.summary_agent.handler as module

    assert item.module_name is not None
    assert sys.modules[item.module_name] is module


def test_toolset_handlers_load_with_canonical_names() -> None:
    registry = ToolSetRegistry(PACKAGE_ROOT / "skills" / "toolsets")

    assert registry.get_load_failures() == {}
    item = registry._items["render.render_latex"]
    assert item.module_name == "Undefined.skills.toolsets.render.render_latex.handler"
    assert item.handler is not None


def test_broken_handler_is_reported_and_hidden_from_schema(tmp_path: Path) -> None:
    tools_dir = tmp_path / "skills" / "tools"
    _write_skill(
        tools_dir / "broken_tool",
        name="broken_tool",
        handler_source=(
            "import definitely_not_installed_module\n\n"
            "async def execute(args, context):\n"
            "    return 'ok'\n"
        ),
    )
    _write_skill(
        tools_dir / "healthy_tool",
        name="healthy_tool",
        handler_source=("async def execute(args, context):\n    return 'ok'\n"),
    )

    registry = ToolRegistry(tools_dir)

    failures = registry.get_load_failures()
    assert "broken_tool" in failures
    assert "definitely_not_installed_module" in failures["broken_tool"]
    assert registry._items["healthy_tool"].load_error is None

    advertised = {schema["function"]["name"] for schema in registry.get_tools_schema()}
    assert advertised == {"healthy_tool"}


def test_handler_without_execute_is_reported(tmp_path: Path) -> None:
    tools_dir = tmp_path / "skills" / "tools"
    _write_skill(
        tools_dir / "no_execute",
        name="no_execute",
        handler_source="VALUE = 1\n",
    )

    registry = ToolRegistry(tools_dir)

    assert "no_execute" in registry.get_load_failures()
    assert registry.get_tools_schema() == []


def test_preload_handlers_returns_failures(tmp_path: Path) -> None:
    tools_dir = tmp_path / "skills" / "tools"
    _write_skill(
        tools_dir / "boom",
        name="boom",
        handler_source="raise RuntimeError('boom at import')\n",
    )

    registry = ToolRegistry(tools_dir)
    failures = registry.preload_handlers()

    assert any(name == "boom" and "boom at import" in error for name, error in failures)


def test_purge_submodules_covers_cross_level_relative_imports() -> None:
    """跨层相对导入的助手模块（from ...docker_utils import）也必须随技能失效。"""
    handler_module = (
        "Undefined.skills.agents.code_delivery_agent.tools.init_docker.handler"
    )
    helper_module = "Undefined.skills.agents.code_delivery_agent.docker_utils"

    registry = AgentRegistry(AgentRegistry(PACKAGE_ROOT / "skills" / "agents").base_dir)
    sys.modules.setdefault(helper_module, object())  # type: ignore[arg-type]
    try:
        registry._purge_submodules(handler_module)
        assert helper_module not in sys.modules
    finally:
        sys.modules.pop(helper_module, None)
